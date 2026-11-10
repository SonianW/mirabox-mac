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
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]


CJK_FONT_CANDIDATES = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]


def _font(size: int, cjk: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (CJK_FONT_CANDIDATES if cjk else FONT_CANDIDATES):
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _has_cjk(text: str) -> bool:
    return any("\u3000" <= ch <= "\u9fff" or "\uff00" <= ch <= "\uffef" for ch in text)


def _fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, start: int = 14, floor: int = 8):
    cjk = _has_cjk(text)
    size = start
    while size > floor:
        font = _font(size, cjk)
        if draw.textlength(text, font=font) <= max_width:
            return font
        size -= 1
    return _font(floor, cjk)


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
    """Full-screen clock: one glyph per key column, H H : M M, colon in the middle column.

    Each glyph is centred on its own column and scaled independently in x and y
    so the widest digit fills the key width and every glyph fills the available
    height. Positions are fixed, so nothing shifts when digits or the colon change.
    """
    size = canvas_size(cfg.gap)
    gx, gy = cfg.gap
    canvas = Image.new("RGB", size, cfg.bg)
    time_text = now.strftime("%H:%M")

    font = _font(200)
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    bbox = probe.textbbox((0, 0), "0123456789", font=font)
    glyph_h = bbox[3] - bbox[1]
    digit_adv = max(probe.textlength(d, font=font) for d in "0123456789")

    margin_x, margin_y = 2, 4
    time_rows = 2 if cfg.show_date else GRID_ROWS
    area_h = time_rows * KEY_SIZE[1] + (time_rows - 1) * gy
    target_h = area_h - 2 * margin_y
    sx = (KEY_SIZE[0] - 2 * margin_x) / digit_adv

    for col, ch in enumerate(time_text):
        if ch == ":" and not colon_on:
            continue
        adv = probe.textlength(ch, font=font)
        layer = Image.new("RGBA", (int(adv) + 2, glyph_h), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text((0, -bbox[1]), ch, font=font, fill=cfg.fg)
        g = layer.resize((max(1, int(adv * sx)), target_h), Image.LANCZOS)
        cx = col * (KEY_SIZE[0] + gx) + KEY_SIZE[0] / 2
        canvas.paste(g, (int(cx - g.width / 2), margin_y), g)

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


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int, max_lines: int) -> list[str]:
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=font) <= max_w:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
            if len(lines) == max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) == max_lines and draw.textlength("".join(lines) , font=font) < draw.textlength(text, font=font):
        lines[-1] = lines[-1][:-1] + "…"
    return lines


def render_alarm(title: str, seconds_left: int, phase: int, gap: tuple[int, int]) -> Image.Image:
    """One frame of the meeting alarm. `phase` alternates colours and jitters the text."""
    size = canvas_size(gap)
    gx, gy = gap
    palette = [("#d00000", "#ffffff"), ("#ffffff", "#d00000"), ("#ffd400", "#000000"), ("#000000", "#ffd400")]
    bg, fg = palette[phase % len(palette)]
    canvas = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(canvas)
    jitter = 6 if phase % 2 else -6

    # Top two rows: the meeting title, up to two lines.
    area_h = KEY_SIZE[1] * 2 + gy
    font = _fit_font(draw, title, size[0] - 24, start=44, floor=26)
    lines = _wrap(draw, title, font, size[0] - 24, 2)
    line_h = font.size + 6
    y = (area_h - line_h * len(lines)) / 2
    for line in lines:
        w = draw.textlength(line, font=font)
        draw.text(((size[0] - w) / 2 + jitter, y), line, font=font, fill=fg)
        y += line_h

    # Bottom row: countdown.
    text = f"{seconds_left} 秒后开会" if seconds_left > 0 else "开会了！"
    bfont = _fit_font(draw, text, size[0] - 24, start=40, floor=20)
    bbox = draw.textbbox((0, 0), text, font=bfont)
    row_top = 2 * (KEY_SIZE[1] + gy)
    w = bbox[2] - bbox[0]
    draw.text(((size[0] - w) / 2 - jitter, row_top + (KEY_SIZE[1] - (bbox[3] - bbox[1])) / 2 - bbox[1]), text, font=bfont, fill=fg)
    return canvas
