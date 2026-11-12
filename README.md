# mirabox-mac

Drive a Mirabox Stream Dock **M18** on macOS from a JSON key map, without the
official StreamDock app. Each of the 15 LCD keys gets a rendered image
(label, background colour, optional icon) and an action; the three buttons
below the screen get actions only. Pages let one key switch the whole layout.

Built on the official [StreamDock-Device-SDK](https://github.com/MiraboxSpace/StreamDock-Device-SDK)
(Python, MIT), vendored as a git submodule.

## Requirements

- macOS 11+ on Apple silicon or Intel
- [uv](https://docs.astral.sh/uv/) (manages Python 3.12 and the virtualenv)
- `brew install hidapi`
- The official StreamDock app must **not** be running; it holds the device.
  Quit it and turn off its "launch at login" option.

## Install

```bash
git clone --recurse-submodules git@github.com:SonianW/mirabox-mac.git
cd mirabox-mac
uv sync
mkdir -p ~/.config/mirabox-mac
cp config.example.json ~/.config/mirabox-mac/config.json
uv run mirabox-mac devices        # should list StreamDockM18
uv run mirabox-mac check          # validate the config
uv run mirabox-mac preview        # render each page to /tmp/mirabox-mac-preview/*.png
uv run mirabox-mac run            # start the daemon in the foreground
```

Start at login:

```bash
scripts/install-launchd.sh        # installs ~/Library/LaunchAgents/com.sonianw.mirabox-mac.plist
scripts/install-launchd.sh remove
tail -f ~/Library/Logs/mirabox-mac.log
```

## Config

Default path `~/.config/mirabox-mac/config.json`, override with `-c` or
`MIRABOX_MAC_CONFIG`. The daemon reloads it whenever the file changes.

```json
{
  "brightness": 80,
  "led": [0, 0, 0],
  "default_page": "main",
  "clock": {"idle_seconds": 30, "blink": true, "gap": [16, 16]},
  "pages": {
    "main": {
      "keys": {
        "1":  {"label": "Terminal", "bg": "#1e5aa8", "action": {"type": "open", "target": "Terminal"}},
        "2":  {"label": "Lock", "action": {"type": "shell", "command": "pmset displaysleepnow"}},
        "3":  {"label": "Docs", "icon": "icons/docs.png", "action": {"type": "open", "target": "https://example.com"}},
        "15": {"label": "More", "action": {"type": "page", "page": "tools"}},
        "16": {"action": {"type": "page", "page": "main"}}
      }
    },
    "tools": { "keys": { "15": {"label": "Back", "action": {"type": "page", "page": "main"}} } }
  }
}
```

| Field | Meaning |
| --- | --- |
| `brightness` | Screen brightness 0-100 |
| `clock` | Idle clock: after `idle_seconds` without a key press the 15 LCD keys show one full-screen clock (HH:MM, colon blinking each second; `show_date: true` adds the date on the bottom row). The next press only wakes the page. `idle_seconds: 0` disables it. Fields: `idle_seconds`, `show_date`, `blink`, `bg`, `fg`, `date_fg`, `gap` (`[x, y]` physical gap between keys in key pixels, 64 px per key; tune until digits line up across keys). The device background image is never touched. |
| `led` | `[r, g, b]` for the 24 RGB LEDs; omit to leave them alone |
| `pages.<name>.keys.<n>` | `n` is 1-15 for LCD keys (left to right, top to bottom), 16-18 for the bottom buttons |
| `label` | Text drawn on the key; `\n` forces a line break, a space in a long label also wraps |
| `icon` | PNG path, relative to the config file; drawn above the label |
| `bg` / `fg` | Background and text colours |
| `action.type` | `shell` (runs `command` through `/bin/sh`), `open` (`open -a <app>`, or `open <url or path>`), `page` (switch to `page`), `none` |

Actions run detached, so a slow command never blocks the key reader.

## Meeting alarm

`alarm` in the config turns the deck into a flashing full-screen reminder
`lead_seconds` before each calendar event: red/white/yellow frames alternate
at `fps`, the LEDs flash, brightness goes to 100. Any key press ends it and
does nothing else; it also stops after `max_seconds`.

Events come from `events_file` (default `~/.config/mirabox-mac/events.json`,
format in `src/mirabox_mac/events.py`). With `wave_mcp_url` set, the daemon
fills that file itself every `sync_minutes` from the Wave calendar MCP:

```bash
uv run mirabox-mac wave login    # OAuth in the browser; token kept in ~/.config/mirabox-mac/oauth/, ~5.6 days, no refresh
uv run mirabox-mac wave status
uv run mirabox-mac wave sync     # one-off pull
uv run mirabox-mac alarm-test --seconds 90   # fake event to see the alarm
```

Fixed daily reminders that are not in the calendar go in `alarm.reminders`:
`[{"title": "吃饭", "time": "11:50", "days": "weekdays"}]`, `days` is
`daily`, `weekdays` or a list like `mon,wed,fri`.

The OAuth client follows the MCP spec: discovery from the 401 challenge,
dynamic registration with a loopback redirect on port 51733, PKCE.

## Layout

```
src/mirabox_mac/
  config.py   load + validate JSON
  render.py   64x64 key images (Pillow)
  actions.py  shell / open / page
  daemon.py   open device, draw page, dispatch presses, hotplug, config reload
  events.py   events file loader
  wave_oauth.py  OAuth 2.1 client + token store
  wave_sync.py   MCP client, calendar → events file
  cli.py      run | devices | check | preview | wave | alarm-test
vendor/StreamDock-Device-SDK   official SDK submodule (Python-SDK installed editable)
launchd/, scripts/             login agent
```

## Notes

- The SDK's `set_key_image` writes a temporary JPEG into the current directory;
  the daemon `chdir`s into a private temp dir at start.
- Device IDs: Mirabox M18 `6603:1009`, M18 EN `6603:1012`. Firmware tested:
  `V3.M18V3_E_HXJDF.03.021`.
- Only button events are mapped. The M18 has no knobs or touch bar.
- After Mac sleep or a USB re-enumeration the SDK handle can go stale while
  the device path stays the same, so hotplug polling never fires. The daemon
  counts failed key writes and reopens the device after three bad frames.
- Input codes: on the tested firmware the device reports LCD key presses by
  screen position, while the SDK decodes them through its row-swapped image
  map. `daemon.py` undoes that swap so position n is reported as key n.
