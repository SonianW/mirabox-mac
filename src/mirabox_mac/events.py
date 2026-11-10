"""Calendar events feed: a JSON file written by an external sync, read by the daemon.

File layout:

{
  "generated_at": "2026-11-10 09:00",
  "events": [
    {"id": "ev_...", "title": "Web domain 周会", "start": "2026-11-10 10:45", "end": "2026-11-10 11:30",
     "url": "https://..."}
  ]
}

Times are local wall-clock, minute precision. Unknown fields are ignored.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Event:
    id: str
    title: str
    start: dt.datetime
    end: dt.datetime | None
    url: str | None


def _parse_time(v: str) -> dt.datetime:
    return dt.datetime.strptime(v, "%Y-%m-%d %H:%M")


def load_events(path: Path) -> list[Event]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        log.error("events file %s unreadable: %s", path, e)
        return []
    out: list[Event] = []
    for i, r in enumerate(raw.get("events", [])):
        try:
            start = _parse_time(r["start"])
            end = _parse_time(r["end"]) if r.get("end") else None
            out.append(Event(id=str(r.get("id") or f"{r['title']}@{r['start']}"), title=str(r["title"]), start=start, end=end, url=r.get("url")))
        except (KeyError, ValueError) as e:
            log.warning("events[%d] skipped: %s", i, e)
    out.sort(key=lambda e: e.start)
    return out


def next_event(events: list[Event], now: dt.datetime) -> Event | None:
    for e in events:
        if e.start >= now:
            return e
    return None
