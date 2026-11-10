"""OAuth 2.1 client for an MCP endpoint behind the office gateway.

Flow (same as office-mcp's mcpOauth.ts): probe the MCP URL for a 401 with
`resource_metadata`, read protected-resource and authorization-server
metadata, dynamically register a public client with a loopback redirect,
PKCE authorization-code grant, store the token per gateway host:

    <root>/<host>/client.json   client_id + redirect_uri
    <root>/<host>/token.json    access_token, token_type, expires_at (seconds), mode 600

The token endpoint issues no refresh_token; tokens last about 5.6 days and a
new login is needed afterwards.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_ROOT = Path("~/.config/mirabox-mac/oauth").expanduser()
CALLBACK_PORT = 51733
CLIENT_NAME = "mirabox-mac"


class OauthError(Exception):
    pass


@dataclass
class Endpoints:
    resource: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str


@dataclass
class Token:
    access_token: str
    token_type: str
    expires_at: int

    def remaining(self) -> int:
        return max(0, self.expires_at - int(time.time()))


def host_of(url: str) -> str:
    return urllib.parse.urlparse(url).netloc


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _request(url: str, method: str = "GET", headers: dict | None = None, body: bytes | None = None) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, method=method, headers=headers or {}, data=body)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def _get_json(url: str, what: str) -> dict:
    status, _, body = _request(url, headers={"accept": "application/json"})
    if status != 200:
        raise OauthError(f"{what} HTTP {status}")
    try:
        d = json.loads(body)
    except json.JSONDecodeError:
        raise OauthError(f"{what} is not JSON") from None
    if not isinstance(d, dict):
        raise OauthError(f"{what} is not an object")
    return d


def discover(mcp_url: str) -> Endpoints:
    status, headers, _ = _request(
        mcp_url, "POST",
        {"accept": "application/json, text/event-stream", "content-type": "application/json"},
        b"{}",
    )
    auth = next((v for k, v in headers.items() if k.lower() == "www-authenticate"), "")
    m = re.search(r'resource_metadata="([^"]+)"', auth)
    if status != 401 or not m:
        raise OauthError(f"endpoint returned no OAuth challenge: HTTP {status}")
    rm = _get_json(m.group(1), "protected resource metadata")
    servers = rm.get("authorization_servers") or []
    as_url = servers[0] if servers and isinstance(servers[0], str) else ""
    if not as_url:
        raise OauthError("protected resource metadata has no authorization_servers")
    meta_url = as_url if "/.well-known/" in as_url else as_url.rstrip("/") + "/.well-known/oauth-authorization-server"
    am = _get_json(meta_url, "authorization server metadata")

    def pick(k: str) -> str:
        v = am.get(k)
        if not isinstance(v, str) or not v:
            raise OauthError(f"authorization server metadata lacks {k}")
        return v

    return Endpoints(
        resource=rm.get("resource") if isinstance(rm.get("resource"), str) else "",
        authorization_endpoint=pick("authorization_endpoint"),
        token_endpoint=pick("token_endpoint"),
        registration_endpoint=pick("registration_endpoint"),
    )


def register(ep: Endpoints, redirect_uri: str) -> dict:
    payload = json.dumps({
        "client_name": CLIENT_NAME,
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }).encode()
    status, _, body = _request(ep.registration_endpoint, "POST", {"content-type": "application/json", "accept": "application/json"}, payload)
    if status not in (200, 201):
        raise OauthError(f"dynamic registration HTTP {status}")
    d = json.loads(body)
    if not isinstance(d.get("client_id"), str):
        raise OauthError("registration response has no client_id")
    return {"client_id": d["client_id"], "redirect_uri": redirect_uri}


class TokenStore:
    def __init__(self, root: Path = DEFAULT_ROOT):
        self.root = root

    def _path(self, host: str, name: str) -> Path:
        return self.root / re.sub(r"[^\w.-]", "_", host) / name

    def _read(self, host: str, name: str) -> dict | None:
        p = self._path(host, name)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def _write(self, host: str, name: str, data: dict, mode: int) -> None:
        p = self._path(host, name)
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.chmod(tmp, mode)
        tmp.replace(p)

    def client(self, host: str) -> dict | None:
        c = self._read(host, "client.json")
        return c if c and isinstance(c.get("client_id"), str) else None

    def set_client(self, host: str, c: dict) -> None:
        self._write(host, "client.json", c, 0o600)

    def token(self, host: str) -> Token | None:
        t = self._read(host, "token.json")
        if not t or not isinstance(t.get("access_token"), str):
            return None
        return Token(t["access_token"], t.get("token_type", "Bearer"), int(t.get("expires_at", 0)))

    def set_token(self, host: str, t: Token) -> None:
        self._write(host, "token.json", {"access_token": t.access_token, "token_type": t.token_type, "expires_at": t.expires_at}, 0o600)

    def forget(self, host: str) -> None:
        p = self._path(host, "token.json")
        if p.exists():
            p.unlink()


class _Callback(http.server.BaseHTTPRequestHandler):
    result: dict = {}
    done = threading.Event()

    def do_GET(self):  # noqa: N802
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _Callback.result = {k: v[0] for k, v in q.items()}
        msg = "登录完成，可以关闭此页。" if "code" in q else f"授权失败：{q.get('error', ['?'])[0]}"
        body = f"<html><body style='font-family:sans-serif'><h2>mirabox-mac</h2><p>{msg}</p></body></html>".encode()
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        _Callback.done.set()

    def log_message(self, *a):  # silence
        pass


def login(mcp_url: str, store: TokenStore, open_browser: bool = True, timeout: int = 900) -> Token:
    """Interactive login: prints the authorization URL, waits for the loopback callback, stores the token."""
    host = host_of(mcp_url)
    ep = discover(mcp_url)
    redirect_uri = f"http://localhost:{CALLBACK_PORT}/callback"
    client = store.client(host)
    if not client or client.get("redirect_uri") != redirect_uri:
        client = register(ep, redirect_uri)
        store.set_client(host, client)

    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    state = _b64url(secrets.token_bytes(18))
    q = {
        "response_type": "code", "client_id": client["client_id"], "redirect_uri": redirect_uri,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
    }
    if ep.resource:
        q["resource"] = ep.resource
    url = f"{ep.authorization_endpoint}?{urllib.parse.urlencode(q)}"

    _Callback.result = {}
    _Callback.done.clear()
    server = http.server.HTTPServer(("127.0.0.1", CALLBACK_PORT), _Callback)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        print(f"Open this URL to authorize {host}:\n{url}\n", flush=True)
        if open_browser:
            webbrowser.open(url)
        if not _Callback.done.wait(timeout):
            raise OauthError("login timed out waiting for the browser callback")
    finally:
        server.shutdown()
        server.server_close()

    r = _Callback.result
    if r.get("state") != state:
        raise OauthError("callback state mismatch")
    if "code" not in r:
        raise OauthError(f"authorization failed: {r.get('error')} {r.get('error_description', '')}".strip())

    form = {"grant_type": "authorization_code", "code": r["code"], "redirect_uri": redirect_uri, "client_id": client["client_id"], "code_verifier": verifier}
    if ep.resource:
        form["resource"] = ep.resource
    status, _, body = _request(ep.token_endpoint, "POST", {"content-type": "application/x-www-form-urlencoded", "accept": "application/json"}, urllib.parse.urlencode(form).encode())
    if status != 200:
        raise OauthError(f"token exchange HTTP {status}: {body[:200]!r}")
    d = json.loads(body)
    if not isinstance(d.get("access_token"), str):
        raise OauthError("token response has no access_token")
    expires_in = int(d.get("expires_in") or 3600)
    token = Token(d["access_token"], d.get("token_type", "Bearer"), int(time.time()) + expires_in)
    store.set_token(host, token)
    log.info("logged in to %s, token valid for %.1f days", host, expires_in / 86400)
    return token
