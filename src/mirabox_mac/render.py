"""Render 64x64 key images from a Key definition."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import Key

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
