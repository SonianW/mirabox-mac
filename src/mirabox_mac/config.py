"""Load and validate the key-map config.

Config file layout (JSON):

{
  "brightness": 80,
  "led": [0, 0, 0],
  "default_page": "main",
  "clock": {"idle_seconds": 30, "show_date": true},
  "pages": {
    "main": {
      "keys": {
        "1":  {"label": "Term", "icon": "icons/terminal.png", "bg": "#1e5aa8",
               "action": {"type": "open", "target": "Terminal"}},
        "2":  {"label": "Lock", "action": {"type": "shell", "command": "pmset displaysleepnow"}},
        "15": {"label": "More", "action": {"type": "page", "page": "tools"}},
        "16": {"action": {"type": "page", "page": "main"}}
      }
    }
  }
}

Keys 1-15 are the LCD keys (5 x 3, left to right, top to bottom) and carry an
image. Keys 16-18 are the three plain buttons below the screen and carry only
an action. Relative icon paths resolve against the config file's directory.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LCD_KEYS = range(1, 16)
BUTTON_KEYS = range(16, 19)
ALL_KEYS = range(1, 19)
ACTION_TYPES = {"shell", "open", "page", "none"}

DEFAULT_CONFIG_PATH = Path(
    os.environ.get("MIRABOX_MAC_CONFIG", "~/.config/mirabox-mac/config.json")
).expanduser()


class ConfigError(Exception):
    pass


@dataclass
class Action:
    type: str = "none"
    command: str | None = None  # shell
    target: str | None = None  # open: app name, path or URL
    page: str | None = None  # page


@dataclass
class Key:
    number: int
    label: str = ""
    icon: Path | None = None
    bg: str = "#202020"
    fg: str = "#ffffff"
    action: Action = field(default_factory=Action)


@dataclass
class Page:
    name: str
    keys: dict[int, Key]


@dataclass
class ClockConfig:
    idle_seconds: int = 30  # 0 disables the idle clock
    show_date: bool = True
    bg: str = "#000000"
    fg: str = "#ffffff"
    date_fg: str = "#9a9a9a"
    blink: bool = True


@dataclass
class Config:
    path: Path
    brightness: int
    led: tuple[int, int, int] | None
    default_page: str
    pages: dict[str, Page]
    clock: ClockConfig = field(default_factory=ClockConfig)

    def page(self, name: str) -> Page:
        try:
            return self.pages[name]
        except KeyError:
            raise ConfigError(f"page {name!r} is not defined") from None


def _parse_action(raw: Any, where: str) -> Action:
    if raw is None:
        return Action()
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: action must be an object")
    kind = raw.get("type", "none")
    if kind not in ACTION_TYPES:
        raise ConfigError(f"{where}: unknown action type {kind!r}, expected one of {sorted(ACTION_TYPES)}")
    action = Action(type=kind, command=raw.get("command"), target=raw.get("target"), page=raw.get("page"))
    if kind == "shell" and not action.command:
        raise ConfigError(f"{where}: shell action needs 'command'")
    if kind == "open" and not action.target:
        raise ConfigError(f"{where}: open action needs 'target'")
    if kind == "page" and not action.page:
        raise ConfigError(f"{where}: page action needs 'page'")
    return action


def _parse_key(number: int, raw: Any, base: Path, where: str) -> Key:
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: key entry must be an object")
    icon = raw.get("icon")
    icon_path = None
    if icon:
        icon_path = (base / icon).expanduser()
        if not icon_path.is_absolute():
            icon_path = base / icon_path
        if not icon_path.exists():
            raise ConfigError(f"{where}: icon not found: {icon_path}")
    return Key(
        number=number,
        label=str(raw.get("label", "")),
        icon=icon_path,
        bg=str(raw.get("bg", "#202020")),
        fg=str(raw.get("fg", "#ffffff")),
        action=_parse_action(raw.get("action"), where),
    )


def _parse_page(name: str, raw: Any, base: Path) -> Page:
    if not isinstance(raw, dict) or not isinstance(raw.get("keys"), dict):
        raise ConfigError(f"page {name!r}: must be an object with a 'keys' map")
    keys: dict[int, Key] = {}
    for k, v in raw["keys"].items():
        try:
            number = int(k)
        except ValueError:
            raise ConfigError(f"page {name!r}: key id {k!r} is not an integer") from None
        if number not in ALL_KEYS:
            raise ConfigError(f"page {name!r}: key {number} out of range 1-18")
        keys[number] = _parse_key(number, v, base, f"page {name!r} key {number}")
    return Page(name=name, keys=keys)


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> Config:
    path = Path(path).expanduser()
    if not path.exists():
        raise ConfigError(f"config not found: {path} (copy config.example.json there)")
    with path.open() as f:
        try:
            raw = json.load(f)
        except json.JSONDecodeError as e:
            raise ConfigError(f"{path}: invalid JSON: {e}") from None
    base = path.parent

    brightness = int(raw.get("brightness", 80))
    if not 0 <= brightness <= 100:
        raise ConfigError("brightness must be 0-100")

    led = raw.get("led")
    led_t = None
    if led is not None:
        if not (isinstance(led, list) and len(led) == 3):
            raise ConfigError("led must be [r, g, b]")
        led_t = tuple(int(c) for c in led)  # type: ignore[assignment]

    pages_raw = raw.get("pages")
    if not isinstance(pages_raw, dict) or not pages_raw:
        raise ConfigError("'pages' must be a non-empty object")
    pages = {name: _parse_page(name, p, base) for name, p in pages_raw.items()}

    default_page = raw.get("default_page") or next(iter(pages))
    if default_page not in pages:
        raise ConfigError(f"default_page {default_page!r} is not a defined page")

    for page in pages.values():
        for key in page.keys.values():
            if key.action.type == "page" and key.action.page not in pages:
                raise ConfigError(f"page {page.name!r} key {key.number}: target page {key.action.page!r} not defined")

    clock_raw = raw.get("clock", {})
    if clock_raw is None:
        clock_raw = {"idle_seconds": 0}
    if not isinstance(clock_raw, dict):
        raise ConfigError("'clock' must be an object")
    clock = ClockConfig(
        idle_seconds=int(clock_raw.get("idle_seconds", 30)),
        show_date=bool(clock_raw.get("show_date", True)),
        bg=str(clock_raw.get("bg", "#000000")),
        fg=str(clock_raw.get("fg", "#ffffff")),
        date_fg=str(clock_raw.get("date_fg", "#9a9a9a")),
        blink=bool(clock_raw.get("blink", True)),
    )
    if clock.idle_seconds < 0:
        raise ConfigError("clock.idle_seconds must be >= 0")

    return Config(path=path, brightness=brightness, led=led_t, default_page=default_page, pages=pages, clock=clock)
