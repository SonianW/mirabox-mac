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


def _cells(text: str, max_cells: int) -> list[str]:
    """Pack text into per-key cells: each CJK character and each Latin word gets its own cell."""
    cells: list[str] = []
    cur = ""
    for ch in text:
        if _has_cjk(ch):
            if cur:
                cells.append(cur)
                cur = ""
            cells.append(ch)
        elif ch.isspace():
            if cur:
                cells.append(cur)
                cur = ""
        else:
            cur += ch
    if cur:
        cells.append(cur)
    if len(cells) > max_cells:
        cells = cells[: max_cells - 1] + ["…"]
    return cells


def _row_font(cells: list[str], scale: float):
    """One font size for a whole row: the largest that fits every cell's text in a key."""
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    size = int(58 * scale)
    floor = 12
    while size > floor:
        if all(probe.textlength(c, font=_font(size, _has_cjk(c))) <= 60 * scale for c in cells if c):
            break
        size -= 1
    return size


def _cell_tile(text: str, bg: str, fg: str, size: int) -> Image.Image:
    tile = Image.new("RGB", KEY_SIZE, bg)
    if not text:
        return tile
    draw = ImageDraw.Draw(tile)
    font = _font(size, _has_cjk(text))
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((KEY_SIZE[0] - w) / 2 - bbox[0], (KEY_SIZE[1] - h) / 2 - bbox[1]), text, font=font, fill=fg)
    return tile


def _row_tiles(cells: list[str], bg: str, fg: str, scale: float) -> list[Image.Image]:
    pad = (GRID_COLS - len(cells)) // 2
    slots = [""] * pad + cells + [""] * (GRID_COLS - len(cells) - pad)
    size = _row_font(cells, scale)
    return [_cell_tile(c, bg, fg, size) for c in slots]


def render_alarm_tiles(title: str, seconds_left: int, phase: int) -> list[Image.Image]:
    """15 key tiles for one alarm frame: title across rows 1-2 (one cell per key), countdown on row 3.

    Text never crosses the physical gap between keys. `phase` alternates the
    colour scheme and pulses the glyph size.
    """
    palette = [("#d00000", "#ffffff"), ("#ffffff", "#d00000"), ("#ffd400", "#000000"), ("#000000", "#ffd400")]
    bg, fg = palette[phase % len(palette)]
    scale = 1.0 if phase % 2 == 0 else 0.8

    title_cells = _cells(title, GRID_COLS * 2)
    if len(title_cells) <= GRID_COLS:
        rows = [title_cells, []]
    else:
        split = (len(title_cells) + 1) // 2
        rows = [title_cells[:split], title_cells[split:]]
    tiles: list[Image.Image] = []
    for row in rows:
        tiles += _row_tiles(row, bg, fg, scale)
    bottom = _cells(f"{seconds_left}秒后开会" if seconds_left > 0 else "开会了！", GRID_COLS)
    tiles += _row_tiles(bottom, bg, fg, scale)
    return tiles


def render_agenda_tiles(items: list[tuple[str, str, bool]], bg: str = "#101820", fg: str = "#ffffff") -> list[Image.Image]:
    """Upcoming alarms, one per row: (HH:MM, title, is_today). Time in column 1, title in columns 2-5."""
    tiles: list[Image.Image] = []
    for r in range(GRID_ROWS):
        if r >= len(items):
            tiles += [Image.new("RGB", KEY_SIZE, bg)] * GRID_COLS
            continue
        when, title, today = items[r]
        tcol = "#4cc9f0" if today else "#f4a261"
        tile = Image.new("RGB", KEY_SIZE, bg)
        d = ImageDraw.Draw(tile)
        f = _font(22)
        bb = d.textbbox((0, 0), when, font=f)
        d.text(((KEY_SIZE[0] - (bb[2] - bb[0])) / 2 - bb[0], 14 - bb[1]), when, font=f, fill=tcol)
        f2 = _font(12)
        tag = "今天" if today else "明天"
        bb2 = d.textbbox((0, 0), tag, font=_font(12, True))
        d.text(((KEY_SIZE[0] - (bb2[2] - bb2[0])) / 2 - bb2[0], 42 - bb2[1]), tag, font=_font(12, True), fill="#8a8a8a")
        tiles.append(tile)
        cells = _cells(title, GRID_COLS - 1)
        size = _row_font(cells, 0.75)
        cells += [""] * (GRID_COLS - 1 - len(cells))
        tiles += [_cell_tile(c, bg, fg, size) for c in cells]
    return tiles
