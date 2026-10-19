"""OAuth for the MCP endpoint, so claude.ai can reach it from Anthropic's cloud.

The rest of the app sits behind the proxy's login; /mcp and the resource metadata are let
through, and this middleware checks the bearer token itself. Claude discovers the
authorization server from the metadata (RFC 9728) that a 401 points to, signs the
learner in there as the public client SIP_MCP_CLIENT with PKCE, and sends the access
token it gets. The token is checked with the authorization server's introspection
endpoint (RFC 7662), as the confidential client SIP_INTROSPECT_CLIENT, and accepted when
it is active and was issued to SIP_MCP_CLIENT.

Claude Code sessions on the learner's machines send a fixed token instead
(SIP_MCP_TOKEN_FILE), set in their MCP configuration, since they hold no browser login.

Environment: SIP_OAUTH_ISSUER (unset: /mcp is open, for local development),
SIP_PUBLIC_URL, SIP_MCP_CLIENT, SIP_INTROSPECT_CLIENT, SIP_INTROSPECT_SECRET_FILE,
SIP_MCP_TOKEN_FILE.
"""

import base64
import hmac
import json
import os
import time
import urllib.parse
import urllib.request

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

ISSUER = os.environ.get("SIP_OAUTH_ISSUER")
PUBLIC = os.environ.get("SIP_PUBLIC_URL", "http://127.0.0.1:8097")
MCP_CLIENT = os.environ.get("SIP_MCP_CLIENT", "claude-spanish")
CACHE_SECONDS = 300
METADATA = "/.well-known/oauth-protected-resource"


def metadata(request):
    return JSONResponse({
        "resource": f"{PUBLIC}/mcp",
        "authorization_servers": [ISSUER] if ISSUER else [],
        "scopes_supported": ["openid", "offline_access"],
        "bearer_methods_supported": ["header"],
    })


class Introspection:
    def __init__(self):
        self.cache = {}
        meta = json.load(urllib.request.urlopen(f"{ISSUER}/.well-known/oauth-authorization-server", timeout=10))
        self.endpoint = meta["introspection_endpoint"]
        secret = open(os.environ["SIP_INTROSPECT_SECRET_FILE"]).read().strip()
        pair = f"{urllib.parse.quote(os.environ['SIP_INTROSPECT_CLIENT'])}:{urllib.parse.quote(secret)}"
        self.basic = "Basic " + base64.b64encode(pair.encode()).decode()

    def valid(self, token):
        hit = self.cache.get(token)
        if hit and hit[1] > time.time():
            return hit[0]
        req = urllib.request.Request(self.endpoint, data=urllib.parse.urlencode({"token": token}).encode(),
                                     headers={"Authorization": self.basic,
                                              "Content-Type": "application/x-www-form-urlencoded"})
        try:
            info = json.load(urllib.request.urlopen(req, timeout=10))
        except OSError:
            return False
        ok = bool(info.get("active")) and info.get("client_id") == MCP_CLIENT
        expires = min(time.time() + CACHE_SECONDS, info.get("exp") or time.time() + CACHE_SECONDS)
        self.cache[token] = (ok, expires)
        return ok


class GuardMcp:
    """ASGI middleware: requests to /mcp need a valid bearer token when an issuer is set."""

    def __init__(self, app):
        self.app = app
        self.check = Introspection() if ISSUER else None
        path = os.environ.get("SIP_MCP_TOKEN_FILE")
        self.fixed = open(path).read().strip() if path else None

    async def __call__(self, scope, receive, send):
        if self.check and scope["type"] == "http" and scope["path"].startswith("/mcp"):
            auth = dict(scope["headers"]).get(b"authorization", b"").decode()
            token = auth[7:] if auth.lower().startswith("bearer ") else ""
            fixed = bool(self.fixed) and hmac.compare_digest(token, self.fixed)
            if not token or not (fixed or await run_in_threadpool(self.check.valid, token)):
                response = JSONResponse({"error": "invalid_token"}, status_code=401, headers={
                    "WWW-Authenticate": f'Bearer resource_metadata="{PUBLIC}{METADATA}"'})
                return await response(scope, receive, send)
        return await self.app(scope, receive, send)
