"""Pull today's and tomorrow's calendar events from the Wave MCP and write the events file."""

from __future__ import annotations

import datetime as dt
import json
import logging
import urllib.error
import urllib.request
from pathlib import Path

from .wave_oauth import OauthError, Token, TokenStore, host_of

log = logging.getLogger(__name__)


class McpClient:
    """Minimal MCP streamable-HTTP client: initialize once, then tools/call."""

    def __init__(self, url: str, token: Token, extra_headers: dict[str, str] | None = None):
        self.url = url
        self.token = token
        self.extra = extra_headers or {}
        self.session_id: str | None = None
        self._id = 0

    def _post(self, payload: dict) -> dict | None:
        headers = {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
            "authorization": f"{self.token.token_type} {self.token.access_token}",
            **self.extra,
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        req = urllib.request.Request(self.url, method="POST", headers=headers, data=json.dumps(payload).encode())
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                sid = r.headers.get("mcp-session-id")
                if sid:
                    self.session_id = sid
                ctype = r.headers.get("content-type", "")
                raw = r.read().decode()
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise OauthError("token rejected (401); run `mirabox-mac wave login`") from None
            raise RuntimeError(f"MCP HTTP {e.code}: {e.read()[:200]!r}") from None
        if not raw.strip():
            return None
        if "text/event-stream" in ctype:
            for line in raw.splitlines():
                if line.startswith("data:"):
                    msg = json.loads(line[5:].strip())
                    if "result" in msg or "error" in msg:
                        return msg
            return None
        return json.loads(raw)

    def _call(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        msg = self._post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}})
        if msg is None:
            raise RuntimeError(f"no response to {method}")
        if "error" in msg:
            raise RuntimeError(f"{method} failed: {msg['error']}")
        return msg["result"]

    def initialize(self) -> None:
        self._call("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "mirabox-mac", "version": "0.1"}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def tool(self, name: str, arguments: dict) -> dict:
        res = self._call("tools/call", {"name": name, "arguments": arguments})
        if res.get("isError"):
            raise RuntimeError(f"tool {name} error: {res}")
        if isinstance(res.get("structuredContent"), dict):
            return res["structuredContent"]
        for c in res.get("content", []):
            if c.get("type") == "text":
                return json.loads(c["text"])
        raise RuntimeError(f"tool {name} returned no content")


def fetch_events(mcp_url: str, token: Token, days: int = 2, tz: str = "Asia/Shanghai") -> list[dict]:
    client = McpClient(mcp_url, token)
    client.initialize()
    today = dt.date.today()
    start = f"{today:%Y-%m-%d} 00:00"
    end = f"{today + dt.timedelta(days=days - 1):%Y-%m-%d} 23:59"
    out: list[dict] = []
    cursor = None
    while True:
        args = {"start_time": start, "end_time": end, "time_zone": tz, "limit": 50}
        if cursor:
            args["cursor"] = cursor
        data = client.tool("getCalendarDefaultEventList", args)
        for it in data.get("items", []):
            st, en = it.get("start_time") or {}, it.get("end_time") or {}
            if it.get("is_all_day") or not st.get("datetime"):
                continue
            url = None
            mi = it.get("meeting_info") or {}
            for line in (mi.get("other_meeting_info") or "").splitlines():
                if line.startswith("http"):
                    url = line.strip()
                    break
            out.append({
                "id": it.get("event_id"),
                "title": it.get("title") or "(无标题)",
                "start": st["datetime"],
                "end": en.get("datetime"),
                "url": url,
                "reply_status": it.get("reply_status"),
            })
        pg = data.get("pagenation") or {}
        cursor = pg.get("next_cursor")
        if not cursor:
            break
    out.sort(key=lambda e: e["start"])
    return out


def sync(mcp_url: str, events_file: Path, store: TokenStore | None = None, skip_declined: bool = True) -> int:
    store = store or TokenStore()
    token = store.token(host_of(mcp_url))
    if token is None or token.remaining() <= 0:
        raise OauthError(f"no valid token for {host_of(mcp_url)}; run `mirabox-mac wave login`")
    events = fetch_events(mcp_url, token)
    if skip_declined:
        events = [e for e in events if e.get("reply_status") != "declined"]
    events_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = events_file.with_suffix(".tmp")
    tmp.write_text(json.dumps({"generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "events": events}, ensure_ascii=False, indent=2))
    tmp.replace(events_file)
    log.info("synced %d events to %s (token %.1f days left)", len(events), events_file, token.remaining() / 86400)
    return len(events)
