# TDD Portal (Technical Marketing Hub)

One searchable home for all PTC Technical Demo Development content — Videos, LDKs, VDKs and
Virtual Machines — replacing today's split across SharePoint, Brightcove, Consensus and
Seismic / PTC Velocity.

The Portal is an **index and dispatcher**: it never stores content. SharePoint stays the system
of record; Consensus and PTC Velocity stay the external-share mechanisms.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design.

## Run it

```bash
pip install -r requirements.txt
python -m uvicorn app:app --reload --port 8000
```

- App (Elio's UI) — http://127.0.0.1:8000
- **Data inspector (dev)** — http://127.0.0.1:8000/debug
- Interactive API docs — http://127.0.0.1:8000/docs

No configuration needed. Storage defaults to JSON files under `data/runtime/`, seeded from
`data/seed/assets.json` on first run.

```bash
python -m pytest tests/ -q
```

## Layout

```
app.py                     FastAPI entry point
backend/
  config.py                env-driven settings (see .env.example)
  models.py                Pydantic — the shape of data at the API edges
  tables.py                SQLAlchemy — storage, split mirror / Portal-owned
  db.py  deps.py           engine, session, get_current_user stub
  repositories/            AssetRepository interface + SQL implementation
  routers/                 REST endpoints
data/seed/assets.json      28 assets extracted from the original mockup
static/                    css, js, and the 19 extracted thumbnails
scripts/
  split_mockup.py          one-off: single-file mockup -> static assets
  extract_seed.py          one-off: mockup markup -> seed JSON
tests/
```

### The one rule worth knowing before touching storage

Data is split into two groups and **they must never share a record**:

```
data/runtime/
  mirror/   rebuildable cache of SharePoint — sync replaces it wholesale
  owned/    Portal is the system of record — sync must NEVER touch it
```

Put a human-authored value in a mirror record and the next sync destroys it, silently, weeks later.
`replace_source_rows()` is the only sanctioned writer of mirror data, and
`tests/test_repository.py` guards the boundary — **running against both backends**, so the two
implementations cannot drift apart.

`owned/identity.json` is the most important file: it pins a stable slug to a source item, so a link
shared in March still resolves in December after the file has been renamed. Lose it and every link
ever shared breaks.

### Swapping the storage backend

`STORAGE_BACKEND=json` (default) or `sql`. Both implement `AssetRepository` and both are covered by
the same parametrised tests, so switching is a config change.

## Status

| | |
|---|---|
| Frontend | Mockup split into static files. **Not** API-driven yet — Elio is still iterating on `index.html`, so it is deliberately untouched. |
| Data inspector | `/debug` — plain page for viewing the data. Not the product UI. |
| API | Catalogue, facets, rails and Consensus over the seed data. |
| Storage | JSON files behind the repository interface. No Azure SQL. `DATA_DIR` must point at an Azure Files mount before real users submit anything — App Service local disk is ephemeral. |
| SharePoint / Graph | Waiting on IT — `Sites.Selected`, app-only. |
| Consensus | Client, matching and reconciliation built. Running on the stub until credentials are set. |
| Auth | Stub. Must be real before any SharePoint write path ships. |

### Wiring up Consensus

Built against the OpenAPI spec at
`https://app.goconsensus.com/api-documentation/openapi.yaml`. Three things about
that API are unusual enough to trip you up:

- **Auth is a body object, not a header.** Every call carries
  `auth: {api_key, api_secret, user_email, source_name}`. The spec declares no
  `securitySchemes` and every path is `security: []`.
- **Everything is POST**, including search.
- **Responses wrap twice**: `{"data": {"items": [...]}, "status": 200}`, and the
  `status` *inside the body* is authoritative — a 400 can arrive over HTTP 200.

Set the five `CONSENSUS_*` variables from `.env.example`, then run this first:

```bash
curl localhost:8000/api/consensus/probe
```

It calls `info/userInfo` (cheapest authenticated call) to verify credentials,
then one `demo/search`, and prints the live field names beside our mapping.

Two things the spec does not pin down, so both are handled as config rather than
assumptions: the `share_to` item shape (sent as `{email, first_name, last_name}`,
inferred from the documented *response*), and the viewer URL — sends return only
a hash, so the URL comes from `CONSENSUS_VIEWER_URL_TEMPLATE`.

**Sharing.** `POST /api/share/consensus` with `trackable: true` creates a
DemoBoard and **requires `organization`** — the customer the board is for.
`trackable: false` returns an untracked marketing link instead. Pass
`is_test: true` to exercise the whole path without polluting real reporting;
test sends deliberately do not increment share counts.

Engagement metrics are **not available** from `demo/search` or `demosDetails`.
`view_count` stays null rather than being faked; it would need `trackDemoBoards`.
