"""Render 64x64 key images from a Key definition."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import datetime as _dt

from .config import ClockConfig, Key

KEY_SIZE = (64, 64)
FONT_CANDIDATES = [
    "/System/Library/Fonts/SFNSRounded.ttf",
    "/System/Library/Fonts/SFNS.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, start: int = 14, floor: int = 8):
    size = start
    while size > floor:
        font = _font(size)
        if draw.textlength(text, font=font) <= max_width:
            return font
        size -= 1
    return _font(floor)


def render_key(key: Key) -> Image.Image:
    img = Image.new("RGB", KEY_SIZE, key.bg)
    draw = ImageDraw.Draw(img)
    label = key.label.strip()

    if key.icon is not None:
        icon = Image.open(key.icon).convert("RGBA")
        box = 34 if label else 48
        icon.thumbnail((box, box), Image.LANCZOS)
        y = 5 if label else (KEY_SIZE[1] - icon.height) // 2
        x = (KEY_SIZE[0] - icon.width) // 2
        img.paste(icon, (x, y), icon)
        if label:
            font = _fit_font(draw, label, 60, start=12)
            w = draw.textlength(label, font=font)
            draw.text(((KEY_SIZE[0] - w) / 2, 44), label, fill=key.fg, font=font)
        return img

    if label:
        lines = label.split("\n")
        if len(lines) == 1 and len(label) > 7 and " " in label:
            lines = label.split(" ", 1)
        font = _fit_font(draw, max(lines, key=len), 60, start=16 if len(lines) == 1 else 13)
        line_h = font.size + 2
        total = line_h * len(lines)
        y = (KEY_SIZE[1] - total) / 2
        for line in lines:
            w = draw.textlength(line, font=font)
            draw.text(((KEY_SIZE[0] - w) / 2, y), line, fill=key.fg, font=font)
            y += line_h
    return img


def blank_key(bg: str = "#000000") -> Image.Image:
    return Image.new("RGB", KEY_SIZE, bg)


GRID_COLS, GRID_ROWS = 5, 3
CANVAS = (GRID_COLS * KEY_SIZE[0], GRID_ROWS * KEY_SIZE[1])  # 320 x 192


def split_tiles(canvas: Image.Image) -> list[Image.Image]:
    """Cut a 320x192 canvas into 15 key tiles, ordered key 1..15."""
    tiles = []
    for n in range(GRID_COLS * GRID_ROWS):
        c, r = n % GRID_COLS, n // GRID_COLS
        x, y = c * KEY_SIZE[0], r * KEY_SIZE[1]
        tiles.append(canvas.crop((x, y, x + KEY_SIZE[0], y + KEY_SIZE[1])))
    return tiles


def render_clock(now: _dt.datetime, colon_on: bool, cfg: ClockConfig) -> Image.Image:
    """Full-screen clock: HH:MM across the top two key rows, date on the bottom row."""
    canvas = Image.new("RGB", CANVAS, cfg.bg)
    draw = ImageDraw.Draw(canvas)

    time_text = now.strftime("%H:%M")
    font = _fit_font(draw, "88:88", CANVAS[0] - 16, start=120, floor=40)
    bbox = draw.textbbox((0, 0), "88:88", font=font)
    text_h = bbox[3] - bbox[1]
    area_h = KEY_SIZE[1] * 2 if cfg.show_date else CANVAS[1]
    y = (area_h - text_h) / 2 - bbox[1]
    # Draw digits and colon separately so the colon can blink without shifting digits.
    x = (CANVAS[0] - draw.textlength(time_text, font=font)) / 2
    for ch in time_text:
        if ch != ":" or colon_on:
            draw.text((x, y), ch, font=font, fill=cfg.fg)
        x += draw.textlength(ch, font=font)

    if cfg.show_date:
        date_text = now.strftime("%Y-%m-%d  %a")
        dfont = _fit_font(draw, date_text, CANVAS[0] - 24, start=30, floor=14)
        w = draw.textlength(date_text, font=dfont)
        dbbox = draw.textbbox((0, 0), date_text, font=dfont)
        dh = dbbox[3] - dbbox[1]
        dy = KEY_SIZE[1] * 2 + (KEY_SIZE[1] - dh) / 2 - dbbox[1]
        draw.text(((CANVAS[0] - w) / 2, dy), date_text, font=dfont, fill=cfg.date_fg)
    return canvas
