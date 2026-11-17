"""One login entry for every gateway token this machine depends on.

Two token stores are involved:

- local: the Wave calendar token mirabox-mac itself holds (`wave_oauth.TokenStore`);
- remote: the office-mcp plugin on the dev box, which keeps one token per gateway host
  for the MCP proxy that Claude Code, apato and the km-publish scripts use. Its API is
  reachable from this machine through an SSH tunnel; the OAuth callback also comes back
  through that tunnel, so the browser login can be driven from here.

`login_all` checks both, starts a browser login only for what is missing or expiring,
then closes the callback tabs and restores the previously active app.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass

from .wave_oauth import OauthError, TokenStore, _close_callback_tabs, _frontmost_app, _restore_front, host_of, login

log = logging.getLogger(__name__)


@dataclass
class TokenState:
    name: str
    host: str
    remaining_s: int

    @property
    def ok(self) -> bool:
        return self.remaining_s > 0


def _http(url: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, method=method, data=data, headers={"content-type": "application/json", "accept": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read() or b"{}")


def local_state(mcp_url: str, store: TokenStore | None = None) -> TokenState:
    store = store or TokenStore()
    host = host_of(mcp_url)
    t = store.token(host)
    return TokenState("local-wave", host, t.remaining() if t else 0)


def hb_states(api_base: str) -> list[TokenState]:
    """Token state per target from the dev box's office-mcp. Raises on network failure."""
    d = _http(f"{api_base.rstrip('/')}/mcp/status")
    return [TokenState(t["name"], t["host"], int(t.get("remainingS", 0))) for t in d.get("targets", [])]


def hb_login(api_base: str, target: str, open_browser: bool = True, timeout: int = 600) -> None:
    """Start the dev box's login for one target; its callback page chains to the other gateways.
    Waits until every target has a token."""
    d = _http(f"{api_base.rstrip('/')}/mcp/login", "POST", {"target": target})
    url = d["url"]
    print(f"Open this URL to authorize {d.get('host')} for the dev box:\n{url}\n", flush=True)
    if open_browser:
        webbrowser.open(url)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(2)
        try:
            if all(s.ok for s in hb_states(api_base)):
                return
        except (urllib.error.URLError, OSError):
            pass
    raise OauthError("dev box login timed out")


def login_all(mcp_url: str | None, api_base: str | None, min_hours: float = 0, open_browser: bool = True, force: bool = False) -> list[str]:
    """Log in wherever needed. Returns the names that were (re)logged."""
    done: list[str] = []
    previous = _frontmost_app() if open_browser else None
    threshold = min_hours * 3600
    try:
        if mcp_url:
            st = local_state(mcp_url)
            if force or st.remaining_s <= threshold:
                log.info("local Wave token: %.1fh left, logging in", st.remaining_s / 3600)
                login(mcp_url, TokenStore(), open_browser=open_browser, tidy_browser=False)
                done.append(st.name)
        if api_base:
            try:
                states = hb_states(api_base)
            except (urllib.error.URLError, OSError) as e:
                raise OauthError(f"dev box unreachable at {api_base}: {e}") from None
            need = [s for s in states if force or s.remaining_s <= threshold]
            if need:
                log.info("dev box tokens needing login: %s", ", ".join(f"{s.name}({s.remaining_s / 3600:.1f}h)" for s in need))
                hb_login(api_base, need[0].name, open_browser=open_browser)
                done += [s.name for s in need]
    finally:
        if open_browser and done:
            time.sleep(0.6)
            _close_callback_tabs()
            _restore_front(previous)
    return done


def needs_login(mcp_url: str | None, api_base: str | None) -> bool:
    """True when any token is missing or expired. Dev box unreachable counts as not needing login."""
    if mcp_url and not local_state(mcp_url).ok:
        return True
    if api_base:
        try:
            return any(not s.ok for s in hb_states(api_base))
        except (urllib.error.URLError, OSError):
            return False
    return False
