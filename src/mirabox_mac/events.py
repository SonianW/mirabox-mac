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


_DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _days_match(spec: str, d: dt.date) -> bool:
    spec = (spec or "daily").lower()
    if spec == "daily":
        return True
    if spec == "weekdays":
        return d.weekday() < 5
    return _DAY_NAMES[d.weekday()] in {x.strip()[:3] for x in spec.split(",")}


def reminder_events(reminders: list[dict], today: dt.date) -> list[Event]:
    """Expand recurring local reminders into concrete events for today and tomorrow."""
    out: list[Event] = []
    for r in reminders:
        hh, mm = (int(x) for x in str(r["time"]).split(":"))
        for d in (today, today + dt.timedelta(days=1)):
            if _days_match(r.get("days", "daily"), d):
                start = dt.datetime.combine(d, dt.time(hh, mm))
                out.append(Event(id=f"reminder:{r['title']}@{start:%Y-%m-%d %H:%M}", title=str(r["title"]), start=start, end=None, url=None))
    return out
