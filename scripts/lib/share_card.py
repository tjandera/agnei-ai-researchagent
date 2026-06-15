"""
Share card generator.

Composites a social-media-ready PNG by overlaying real numbers and short text
onto the AI hero image (or the offline poster when no image is available).
Output is a 1200x675 PNG — the Twitter/X / LinkedIn card aspect ratio.

The text on the card always comes from grounded data, never the image model.
"""

from __future__ import annotations

import io
from typing import Optional

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from lib.media_gen import _font, offline_hero_poster  # reuse font + fallback

CARD_W, CARD_H = 1200, 675

# Action signal palette — matches the web UI chips.
SIGNAL_COLORS = {
    "ACCUMULATE": ((22, 163, 74),   (240, 253, 244)),  # green
    "HOLD":       ((71, 85, 105),   (241, 245, 249)),  # slate
    "WATCH":      ((202, 138, 4),   (254, 252, 232)),  # amber
    "TRIM":       ((220, 38, 38),   (254, 242, 242)),  # red
}


def build_share_card(
    symbol: str,
    name: str,
    price: Optional[float],
    change_pct: Optional[float],
    action_signal: str,
    summary: str,
    image_url: Optional[str] = None,
) -> bytes:
    """Return a 1200x675 PNG with the AI image (or poster) + overlaid text.

    Never raises — falls back to the offline poster background if the AI URL
    can't be fetched, and to a flat gradient if Pillow itself errors.
    """
    bg = _load_background(image_url, symbol, name, (change_pct or 0) >= 0)
    card = _compose_card(bg, symbol, name, price, change_pct, action_signal, summary)
    buf = io.BytesIO()
    card.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ------------------------------------------------------------------ #
# Background
# ------------------------------------------------------------------ #

def _load_background(image_url: Optional[str], symbol: str, name: str, up: bool) -> Image.Image:
    """Pull the AI hero image, or fall back to the locally drawn poster."""
    if image_url:
        try:
            resp = requests.get(image_url, timeout=15)
            resp.raise_for_status()
            img = Image.open(io.BytesIO(resp.content)).convert("RGB")
            return _fit_cover(img, CARD_W, CARD_H)
        except Exception:
            pass

    # Fallback: offline poster.
    poster_png = offline_hero_poster(symbol, name, up)
    img = Image.open(io.BytesIO(poster_png)).convert("RGB")
    return _fit_cover(img, CARD_W, CARD_H)


def _fit_cover(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Resize+crop the image to exactly target_w x target_h (CSS `object-fit: cover`)."""
    src_w, src_h = img.size
    src_aspect = src_w / src_h
    target_aspect = target_w / target_h

    if src_aspect > target_aspect:
        # Source is wider — scale by height, crop sides.
        new_h = target_h
        new_w = int(round(src_aspect * new_h))
    else:
        # Source is taller — scale by width, crop top/bottom.
        new_w = target_w
        new_h = int(round(new_w / src_aspect))

    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


# ------------------------------------------------------------------ #
# Composition
# ------------------------------------------------------------------ #

def _compose_card(
    bg: Image.Image,
    symbol: str,
    name: str,
    price: Optional[float],
    change_pct: Optional[float],
    action_signal: str,
    summary: str,
) -> Image.Image:
    # Darken the bottom half so text reads cleanly over any image.
    overlay = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for i in range(CARD_H):
        # Gradient: 0 alpha at top, ~210 at bottom.
        t = i / (CARD_H - 1)
        alpha = int(20 + 210 * (t ** 1.6))
        od.line([(0, i), (CARD_W, i)], fill=(8, 10, 14, alpha))
    bg = Image.alpha_composite(bg.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(bg, "RGBA")

    # Top-left kicker.
    draw.line([(56, 56), (140, 56)], fill=(244, 183, 64, 240), width=3)
    draw.text((56, 70), "AGNES FINANCE DIGEST",
              font=_font(20), fill=(236, 230, 216, 235))

    # Top-right action signal chip.
    _draw_signal_chip(draw, action_signal)

    # Bottom-left: symbol, then company name.
    sym = (symbol or "").upper()
    draw.text((56, CARD_H - 290), sym,
              font=_font(160), fill=(248, 250, 252, 255))

    company = (name or sym).strip()
    if len(company) > 38:
        company = company[:35].rstrip() + "..."
    draw.text((60, CARD_H - 122), company,
              font=_font(32), fill=(203, 213, 225, 235))

    # Bottom-right: price + change %.
    if price is not None:
        price_text = _fmt_money(price)
        price_font = _font(80)
        pw = draw.textlength(price_text, font=price_font)
        draw.text((CARD_W - 56 - pw, CARD_H - 230), price_text,
                  font=price_font, fill=(248, 250, 252, 255))

    if change_pct is not None:
        up = change_pct >= 0
        chg_color = (74, 222, 128, 255) if up else (248, 113, 113, 255)
        arrow = "▲" if up else "▼"
        chg_text = f"{arrow} {abs(change_pct):.2f}%"
        chg_font = _font(40)
        cw = draw.textlength(chg_text, font=chg_font)
        draw.text((CARD_W - 56 - cw, CARD_H - 134), chg_text,
                  font=chg_font, fill=chg_color)

    # Middle: one-line summary, wrapped to two lines max.
    if summary:
        _draw_wrapped_summary(draw, summary, CARD_W - 112)

    # Bottom-right corner watermark.
    draw.text((CARD_W - 100, CARD_H - 38), "agnes",
              font=_font(18), fill=(244, 183, 64, 200))

    return bg.convert("RGB")


def _draw_signal_chip(draw: ImageDraw.ImageDraw, signal: str) -> None:
    sig = (signal or "HOLD").upper()
    if sig not in SIGNAL_COLORS:
        sig = "HOLD"
    fill_color, _ = SIGNAL_COLORS[sig]
    text = sig
    font = _font(24)
    tw = draw.textlength(text, font=font)
    pad_x, pad_y = 22, 12
    chip_w = int(tw + pad_x * 2)
    chip_h = 50
    x1 = CARD_W - 56 - chip_w
    y1 = 48
    draw.rounded_rectangle(
        [x1, y1, x1 + chip_w, y1 + chip_h],
        radius=14, fill=fill_color + (235,),
        outline=(255, 255, 255, 60), width=1,
    )
    draw.text((x1 + pad_x, y1 + pad_y - 2), text,
              font=font, fill=(255, 255, 255, 250))


def _draw_wrapped_summary(draw: ImageDraw.ImageDraw, summary: str, max_w: int) -> None:
    """Render up to 2 lines of summary text in the middle-left band."""
    font = _font(28)
    words = summary.split()
    lines = []
    cur = ""
    for w in words:
        attempt = f"{cur} {w}".strip()
        if draw.textlength(attempt, font=font) <= max_w:
            cur = attempt
        else:
            if cur:
                lines.append(cur)
            cur = w
            if len(lines) >= 2:
                break
    if cur and len(lines) < 2:
        lines.append(cur)
    if not lines:
        return
    # If we truncated, add an ellipsis to the last line.
    if len(lines) == 2 and len(" ".join(lines)) < len(summary):
        last = lines[1]
        while draw.textlength(last + "...", font=font) > max_w and len(last) > 4:
            last = last[:-1].rstrip()
        lines[1] = last + "..."

    y = CARD_H // 2 - (len(lines) * 38) // 2 + 30
    for line in lines:
        draw.text((56, y), line, font=font, fill=(236, 240, 248, 240))
        y += 42


def _fmt_money(n: float) -> str:
    a = abs(n)
    if a >= 1000:
        return f"${n:,.0f}"
    if a >= 1:
        return f"${n:,.2f}"
    return f"${n:.4f}"
