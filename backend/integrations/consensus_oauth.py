"""OAuth 2.0 for the Consensus V2 API — Authorization Code with PKCE.

Why this exists at all
----------------------
V1 authenticates with an api_key/api_secret pair in the request body. V2 wants
a Bearer JWT, and the only way to mint one is the Authorization Code flow.
Verified against the live tenant 2026-08-27: the token endpoint answers

    unsupported_grant_type: only authorization_code, refresh_token

so **there is no client-credentials grant and no daemon flow.** A person
authorises once in a browser; from then on the app lives on the refresh token.

Three consequences, all of them operational rather than technical:

1. **The sync runs as whoever authorised.** Use a shared or service account, not
   somebody's personal login, or the integration dies when they change role.
2. **Refresh tokens rotate.** Every refresh may return a new one, and the old
   one stops working. Persisting the new value is not optional — miss it once
   and the next refresh fails.
3. **Losing the stored token costs a human.** There is no way to re-mint it
   without another browser round trip, which is why it is written to
   `owned/` and why `DATA_DIR` must point at durable storage before this
   ships.

What is deliberately NOT here
-----------------------------
Sharing. `createsenddemo` and `createlink` are V1-only, so both clients run
side by side; this one is read-only, and the requested scopes say so
(`public:api:read read:read`, no `read:write`).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from backend.config import settings

log = logging.getLogger(__name__)

OAUTH_ROOT = "/api/auth/v1.0/oauth2"

#: Refresh this far before expiry rather than waiting for a 401. One hour of
#: token life makes five minutes plenty, and it keeps a slow sync from dying
#: halfway through.
_REFRESH_MARGIN_SECONDS = 300

#: How long a half-finished authorisation stays valid. The browser round trip
#: takes seconds; anything older is abandoned and should not linger.
_PENDING_TTL_SECONDS = 600


class ConsensusOAuthError(RuntimeError):
    pass


class NotAuthorised(ConsensusOAuthError):
    """No refresh token stored yet — somebody has to visit the start URL."""


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@dataclass(frozen=True)
class Pending:
    """One in-flight authorisation, held between the redirect out and back."""
    verifier: str
    created_at: float


class _PendingStore:
    """PKCE verifiers awaiting their callback.

    In memory on purpose: the value is useless after a few seconds and must
    never be written anywhere, since holding it alongside an intercepted code
    is what PKCE exists to prevent. The cost is that a restart mid-flow means
    starting over, and that a scaled-out deployment needs the callback to land
    on the same instance — acceptable for an action a person performs once.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, Pending] = {}

    def put(self, state: str, verifier: str) -> None:
        with self._lock:
            self._expire()
            self._pending[state] = Pending(verifier, time.time())

    def take(self, state: str) -> str | None:
        """Consume one. Single use — a replayed state must not work twice."""
        with self._lock:
            self._expire()
            found = self._pending.pop(state, None)
            return found.verifier if found else None

    def _expire(self) -> None:
        cutoff = time.time() - _PENDING_TTL_SECONDS
        for state in [s for s, p in self._pending.items() if p.created_at < cutoff]:
            del self._pending[state]


class TokenStore:
    """The refresh token, on disk under `owned/`.

    Not in the asset repository: this is a credential, not catalogue data, and
    putting it behind the repository interface would imply a sync could touch
    it. It sits in `owned/` because it cannot be rebuilt from any source —
    losing it requires a person to authorise again.
    """

    def __init__(self, data_dir: str | None = None):
        base = data_dir or settings.data_dir
        self.path = os.path.join(base, "owned", "consensus_oauth.json")
        self._lock = threading.Lock()

    def read(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as fh:
                return json.load(fh)
        except (FileNotFoundError, ValueError, OSError):
            return {}

    def write(self, **fields) -> None:
        with self._lock:
            current = self.read()
            current.update(fields)
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = f"{self.path}.tmp"
            with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(current, fh, indent=2)
            os.replace(tmp, self.path)      # atomic: never a half-written token

    def clear(self) -> None:
        with self._lock:
            try:
                os.remove(self.path)
            except FileNotFoundError:
                pass


class ConsensusOAuth:
    def __init__(self, client_id: str | None = None, client_secret: str | None = None,
                 redirect_uri: str | None = None, base_url: str | None = None,
                 store: TokenStore | None = None,
                 transport: httpx.BaseTransport | None = None):
        self.client_id = client_id or settings.consensus_oauth_client_id
        self.client_secret = client_secret or settings.consensus_oauth_client_secret
        self.redirect_uri = redirect_uri or settings.consensus_oauth_redirect_uri
        self.base_url = (base_url or settings.consensus_base_url).rstrip("/")
        self.store = store or TokenStore()
        self.pending = _PendingStore()
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=30, transport=self._transport)

    # ------------------------------------------------------------- step 1 & 2
    def authorization_url(self) -> tuple[str, str]:
        """Where to send the browser, plus the `state` to expect back."""
        if not self.configured:
            raise ConsensusOAuthError(
                "Consensus OAuth is not configured. Set "
                "CONSENSUS_OAUTH_CLIENT_ID and CONSENSUS_OAUTH_CLIENT_SECRET.")

        verifier = _b64url(secrets.token_bytes(32))
        challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
        state = _b64url(secrets.token_bytes(16))
        self.pending.put(state, verifier)

        query = urlencode({
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": settings.consensus_oauth_scopes,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
        return f"{self.base_url}{OAUTH_ROOT}/authorize?{query}", state

    # ----------------------------------------------------------------- step 3
    def exchange(self, code: str, state: str) -> dict:
        """Swap the authorisation code for tokens.

        The state must match one we issued, and it is consumed here — a
        replayed callback fails rather than starting a second exchange.
        """
        verifier = self.pending.take(state)
        if verifier is None:
            raise ConsensusOAuthError(
                "unknown or expired `state`. Either this callback did not come "
                "from an authorisation this server started, or more than 10 "
                "minutes passed. Start again at /api/consensus/oauth/start.")

        tokens = self._token_request({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code_verifier": verifier,
        })
        self._persist(tokens)
        return tokens

    # ----------------------------------------------------------------- step 5
    def access_token(self) -> str:
        """A valid access token, refreshing first if it is close to expiry."""
        stored = self.store.read()
        if not stored.get("refresh_token"):
            raise NotAuthorised(
                "Consensus V2 has never been authorised on this instance. There "
                "is no client-credentials grant, so a person must visit "
                "/api/consensus/oauth/start once; after that the refresh token "
                "keeps it alive.")

        expires_at = stored.get("expires_at") or 0
        if stored.get("access_token") and time.time() < expires_at - _REFRESH_MARGIN_SECONDS:
            return stored["access_token"]

        tokens = self._token_request({
            "grant_type": "refresh_token",
            "refresh_token": stored["refresh_token"],
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        })
        self._persist(tokens)
        return tokens["access_token"]

    def _persist(self, tokens: dict) -> None:
        """Store what came back.

        `refresh_token` is only overwritten when a new one is present: the spec
        says rotation MAY happen, so a response without one means keep the
        existing value. Blindly writing None there would lock us out and cost a
        manual re-authorisation.
        """
        fields = {
            "access_token": tokens.get("access_token"),
            "expires_at": time.time() + float(tokens.get("expires_in") or 3600),
            "obtained_at": time.time(),
            "scope": tokens.get("scope") or settings.consensus_oauth_scopes,
        }
        if tokens.get("refresh_token"):
            fields["refresh_token"] = tokens["refresh_token"]
        self.store.write(**fields)

    def _token_request(self, form: dict) -> dict:
        with self._client() as client:
            response = client.post(
                f"{self.base_url}{OAUTH_ROOT}/token", data=form,
                headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            payload = response.json()
        except ValueError:
            raise ConsensusOAuthError(
                f"HTTP {response.status_code} from the token endpoint, and the "
                f"body was not JSON: {response.text[:200]}") from None

        if response.status_code >= 400 or "access_token" not in payload:
            detail = payload.get("error_description") or payload.get("error") or payload
            grant = form.get("grant_type")
            hint = ""
            if grant == "refresh_token":
                hint = (" The stored refresh token may have been revoked or "
                        "rotated away — re-authorise at "
                        "/api/consensus/oauth/start.")
            raise ConsensusOAuthError(
                f"{grant} failed: HTTP {response.status_code} {detail}.{hint}")
        return payload

    # ---------------------------------------------------------- introspection
    def status(self) -> dict:
        """What a diagnostics page needs, and no token values."""
        stored = self.store.read()
        expires_at = stored.get("expires_at")
        return {
            "configured": self.configured,
            "authorised": bool(stored.get("refresh_token")),
            "redirect_uri": self.redirect_uri,
            "scopes": settings.consensus_oauth_scopes,
            "access_token_expires_in": (
                int(expires_at - time.time()) if expires_at else None),
            "authorised_at": stored.get("obtained_at"),
        }


_singleton: ConsensusOAuth | None = None


def get_oauth() -> ConsensusOAuth:
    """Process-wide instance, because the pending PKCE verifiers must survive
    from the start request to the callback."""
    global _singleton
    if _singleton is None:
        _singleton = ConsensusOAuth()
    return _singleton
