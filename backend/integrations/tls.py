"""Which certificates to trust for outbound HTTPS beyond Microsoft Graph.

Measured 2026-09-29 on Liwei's workstation: PTC's Zscaler proxy re-signs
Brightcove's HTTPS with "Zscaler Intermediate Root CA". Windows trusts it
(IT deploys the root); Python's own certifi bundle does not, so every call
failed with CERTIFICATE_VERIFY_FAILED. graph.microsoft.com is not inspected,
which is why Graph never showed this.

The answer is to trust what the operating system trusts -- `truststore` --
never to switch verification off. On App Service there is no Zscaler and the
system store is the ordinary public one, so behaviour there is unchanged.
When truststore is not installed, certifi is used as before.
"""
from __future__ import annotations

import ssl


def system_trust() -> ssl.SSLContext | bool:
    """An httpx `verify=` value: the OS trust store if available, else certifi."""
    try:
        import truststore
    except ImportError:
        return True
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
