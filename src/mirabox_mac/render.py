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


def canvas_size(gap: tuple[int, int]) -> tuple[int, int]:
    """Virtual canvas covering the 5x3 key grid plus the physical gaps between keys."""
    gx, gy = gap
    return (GRID_COLS * KEY_SIZE[0] + (GRID_COLS - 1) * gx, GRID_ROWS * KEY_SIZE[1] + (GRID_ROWS - 1) * gy)


def split_tiles(canvas: Image.Image, gap: tuple[int, int]) -> list[Image.Image]:
    """Cut the canvas into 15 key tiles at the keys' physical positions, ordered key 1..15."""
    gx, gy = gap
    tiles = []
    for n in range(GRID_COLS * GRID_ROWS):
        c, r = n % GRID_COLS, n // GRID_COLS
        x, y = c * (KEY_SIZE[0] + gx), r * (KEY_SIZE[1] + gy)
        tiles.append(canvas.crop((x, y, x + KEY_SIZE[0], y + KEY_SIZE[1])))
    return tiles


def render_clock(now: _dt.datetime, colon_on: bool, cfg: ClockConfig) -> Image.Image:
    """Full-screen clock: HH:MM stretched to fill the key grid (date on the bottom row if enabled)."""
    size = canvas_size(cfg.gap)
    gx, gy = cfg.gap
    canvas = Image.new("RGB", size, cfg.bg)
    time_text = now.strftime("%H:%M")

    # Render the time at a fixed large size, crop to the geometry of "88:88" so the
    # digits never shift when the colon blinks, then resize to the target area.
    # Aspect ratio is not preserved: the digits stretch to fill the whole grid.
    font = _font(200)
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    bbox = probe.textbbox((0, 0), "88:88", font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    layer = Image.new("RGBA", (text_w, text_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    # Centre the actual string inside the "88:88" box: narrow digits such as "1"
    # would otherwise leave the time hugging the left edge.
    actual_w = draw.textlength(time_text, font=font)
    x = -bbox[0] + (text_w - actual_w) / 2
    for ch in time_text:
        if ch != ":" or colon_on:
            draw.text((x, -bbox[1]), ch, font=font, fill=cfg.fg)
        x += draw.textlength(ch, font=font)

    margin = 6
    time_rows = 2 if cfg.show_date else GRID_ROWS
    area_h = time_rows * KEY_SIZE[1] + (time_rows - 1) * gy
    target = (size[0] - 2 * margin, area_h - 2 * margin)
    layer = layer.resize(target, Image.LANCZOS)
    canvas.paste(layer, (margin, margin), layer)

    if cfg.show_date:
        draw = ImageDraw.Draw(canvas)
        date_text = now.strftime("%Y-%m-%d  %a")
        dfont = _fit_font(draw, date_text, size[0] - 24, start=34, floor=14)
        w = draw.textlength(date_text, font=dfont)
        dbbox = draw.textbbox((0, 0), date_text, font=dfont)
        dh = dbbox[3] - dbbox[1]
        row_top = 2 * (KEY_SIZE[1] + gy)
        dy = row_top + (KEY_SIZE[1] - dh) / 2 - dbbox[1]
        draw.text(((size[0] - w) / 2, dy), date_text, font=dfont, fill=cfg.date_fg)
    return canvas
