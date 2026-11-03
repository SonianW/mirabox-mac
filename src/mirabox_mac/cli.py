from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import DEFAULT_CONFIG_PATH, LCD_KEYS, ConfigError, load_config


def cmd_run(args) -> int:
    from .daemon import run

    run(Path(args.config).expanduser(), watch_config=not args.no_watch)
    return 0


def cmd_devices(args) -> int:
    from StreamDock.DeviceManager import DeviceManager

    devs = DeviceManager().enumerate()
    if not devs:
        print("no Stream Dock devices found")
        return 1
    for d in devs:
        print(f"{type(d).__name__}  path={d.path}")
    return 0


def cmd_check(args) -> int:
    cfg = load_config(Path(args.config).expanduser())
    print(f"config ok: {cfg.path}")
    print(f"brightness={cfg.brightness} led={cfg.led} default_page={cfg.default_page}")
    for page in cfg.pages.values():
        bound = ", ".join(f"{n}:{k.label or k.action.type}" for n, k in sorted(page.keys.items()))
        print(f"page {page.name!r}: {bound}")
    return 0


def cmd_preview(args) -> int:
    from PIL import Image

    from .render import KEY_SIZE, blank_key, render_key

    cfg = load_config(Path(args.config).expanduser())
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    gap, cols, rows = 6, 5, 3
    for page in cfg.pages.values():
        sheet = Image.new("RGB", (cols * KEY_SIZE[0] + (cols + 1) * gap, rows * KEY_SIZE[1] + (rows + 1) * gap), "#101010")
        for n in LCD_KEYS:
            key = page.keys.get(n)
            img = render_key(key) if key else blank_key()
            c, r = (n - 1) % cols, (n - 1) // cols
            sheet.paste(img, (gap + c * (KEY_SIZE[0] + gap), gap + r * (KEY_SIZE[1] + gap)))
        path = out / f"page-{page.name}.png"
        sheet.save(path)
        print(path)
    if cfg.clock.idle_seconds > 0:
        import datetime as dt

        from .render import render_clock

        from .render import split_tiles

        canvas = render_clock(dt.datetime.now(), True, cfg.clock)
        path = out / "clock-canvas.png"
        canvas.save(path)
        print(path)
        # What the keys actually show: tiles laid out with the configured gaps.
        gx, gy = cfg.clock.gap
        sheet = Image.new("RGB", canvas.size, "#303030")
        for n, tile in enumerate(split_tiles(canvas, cfg.clock.gap)):
            c, r = n % cols, n // cols
            sheet.paste(tile, (c * (KEY_SIZE[0] + gx), r * (KEY_SIZE[1] + gy)))
        path = out / "clock-keys.png"
        sheet.save(path)
        print(path)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mirabox-mac", description="Drive a Mirabox Stream Dock M18 on macOS from a JSON key map.")
    p.add_argument("-c", "--config", default=str(DEFAULT_CONFIG_PATH), help=f"config path (default {DEFAULT_CONFIG_PATH})")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("run", help="run the daemon")
    s.add_argument("--no-watch", action="store_true", help="do not reload when the config file changes")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("devices", help="list connected Stream Dock devices")
    s.set_defaults(fn=cmd_devices)

    s = sub.add_parser("check", help="validate the config and print the key map")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("preview", help="render each page to a PNG contact sheet")
    s.add_argument("--out", default="/tmp/mirabox-mac-preview")
    s.set_defaults(fn=cmd_preview)

    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    try:
        return args.fn(args)
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
