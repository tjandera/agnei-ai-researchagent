"""
Media generation for the finance digest.

Two live paths backed by Agnes (hero image, recap video) plus one fully
offline path (a locally drawn poster) used when no Agnes client is available.
The image and video models are never asked to render text, numbers, or
charts. Every real number in the product comes from yfinance and the chart.
"""

import io
import math

from PIL import Image, ImageDraw, ImageFont, ImageFilter


# ------------------------------------------------------------------ #
# Live Agnes media
# ------------------------------------------------------------------ #

def _theme_words(symbol: str, name: str) -> str:
    """Pick a sector mood from the symbol so prompts feel asset specific."""
    s = (symbol or "").upper()
    n = (name or "").lower()
    if s.endswith("-USD") or any(w in n for w in ("bitcoin", "ethereum", "crypto", "coin")):
        return "digital asset, blockchain lattice, electric blue and violet energy, crypto"
    if any(w in n for w in ("bank", "financ", "capital", "holdings", "group")):
        return "institutional finance, marble and brass, deep blues, ledgers of light"
    if any(w in n for w in ("oil", "energy", "gas", "petro")):
        return "energy and commodities, refined metal, amber and slate tones"
    if any(w in n for w in ("tech", "semi", "chip", "software", "micro", "nvidia", "apple")):
        return "advanced technology, silicon geometry, cool cyan circuitry, precision"
    return "global equities, abstract market currents, refined gold and ink tones"


def generate_hero_image(client, symbol, name, theme_hint="", size="1024x768"):
    """Generate one abstract editorial hero visual. Returns a URL or None."""
    try:
        theme = _theme_words(symbol, name)
        hint = (theme_hint or "").strip()
        prompt = (
            "A sophisticated abstract financial editorial illustration, cinematic and "
            "high contrast, themed on " + theme + ". "
            "Flowing abstract market currents and data motifs, layered depth, dramatic "
            "rim lighting, volumetric haze, fine particle detail, premium magazine cover "
            "aesthetic, painterly yet modern. "
            "Mood: " + (hint or "measured market tension") + ". "
            "Landscape composition with generous negative space. "
            "No text, no words, no letters, no numbers, no logos, no readable charts, "
            "no axis labels, no tickers, no user interface."
        )
        return client.generate_image(prompt, size=size)
    except Exception:
        return None


def generate_recap_video(client, image_url, symbol, name):
    """Generate a short silent cinematic b-roll seeded by the hero image."""
    try:
        theme = _theme_words(symbol, name)
        prompt = (
            "Slow cinematic finance b-roll, atmospheric and editorial, themed on "
            + theme + ". "
            "Very slow push-in on abstract market currents, drifting light particles, "
            "soft volumetric haze, gentle parallax, shifting rim light, calm and "
            "premium documentary mood. Silent. "
            "No text, no words, no letters, no numbers, no logos, no readable charts, "
            "no user interface."
        )
        return client.generate_video(
            prompt,
            image_url=image_url,
            num_frames=121,
            frame_rate=24,
            width=1152,
            height=768,
            poll_interval=8,
            max_wait=240,
        )
    except Exception:
        return None


# ------------------------------------------------------------------ #
# Offline poster (no network, fully local, deterministic look)
# ------------------------------------------------------------------ #

_FONT_CANDIDATES = [
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _font(size):
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _vertical_gradient(size, top, bottom):
    w, h = size
    base = Image.new("RGB", (1, h))
    px = base.load()
    for y in range(h):
        px[0, y] = _lerp(top, bottom, y / max(1, h - 1))
    return base.resize((w, h))


def offline_hero_poster(symbol, name, up):
    """Draw a branded landscape poster as PNG bytes. No network required."""
    W, H = 1024, 768
    if up:
        top, bottom, accent = (10, 22, 18), (8, 40, 30), (52, 211, 153)
    else:
        top, bottom, accent = (26, 12, 14), (44, 12, 18), (248, 113, 113)

    img = _vertical_gradient((W, H), top, bottom)
    draw = ImageDraw.Draw(img, "RGBA")

    # Abstract line motif: a drifting field of thin diagonal strokes.
    for i in range(34):
        t = i / 33.0
        y0 = int(H * (0.18 + 0.64 * t))
        amp = 26 + 30 * math.sin(t * math.pi)
        pts = []
        for x in range(0, W + 1, 32):
            yy = y0 + amp * math.sin((x / W) * math.pi * 2 + t * 3.0)
            pts.append((x, yy))
        alpha = int(26 + 54 * (1 - abs(0.5 - t) * 2))
        draw.line(pts, fill=accent + (alpha,), width=2)

    # A soft accent arc sweeping up or down to imply direction.
    arc_box = [W * 0.05, H * (0.1 if up else 0.45), W * 0.95, H * (0.95 if up else 1.35)]
    start, end = (200, 340) if up else (20, 160)
    draw.arc(arc_box, start=start, end=end, fill=accent + (120,), width=6)

    # Glow node accents.
    for cx, cy, r in [(W * 0.16, H * 0.30, 5), (W * 0.78, H * 0.22, 7), (W * 0.62, H * 0.7, 4)]:
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=accent + (220,))

    # Subtle vignette for depth.
    vign = Image.new("L", (W, H), 0)
    vd = ImageDraw.Draw(vign)
    vd.ellipse([-W * 0.25, -H * 0.25, W * 1.25, H * 1.25], fill=70)
    vign = vign.filter(ImageFilter.GaussianBlur(120))
    shade = Image.new("RGB", (W, H), (0, 0, 0))
    img = Image.composite(img, shade, vign.point(lambda v: 255 - (255 - v)))

    draw = ImageDraw.Draw(img, "RGBA")

    # Top hairline and kicker.
    draw.line([(64, 96), (160, 96)], fill=accent + (230,), width=3)
    kicker = _font(22)
    draw.text((64, 112), "AGNES FINANCE DIGEST", font=kicker, fill=(226, 232, 240, 230))

    # Symbol as the dominant typographic label.
    sym = (symbol or "").upper()
    sym_font = _font(132)
    draw.text((60, 300), sym, font=sym_font, fill=(248, 250, 252, 255))

    # Asset name beneath, clipped to one tidy line.
    label = (name or sym).strip()
    if len(label) > 34:
        label = label[:31].rstrip() + "..."
    name_font = _font(40)
    draw.text((64, 452), label, font=name_font, fill=(203, 213, 225, 235))

    # Direction tag, words only, never a price.
    tag = "TREND UP" if up else "TREND DOWN"
    tag_font = _font(24)
    tw = draw.textlength(tag, font=tag_font)
    pad = 18
    bx0, by0 = 64, 540
    draw.rounded_rectangle(
        [bx0, by0, bx0 + tw + pad * 2, by0 + 48],
        radius=24, fill=accent + (40,), outline=accent + (220,), width=2,
    )
    draw.text((bx0 + pad, by0 + 11), tag, font=tag_font, fill=(248, 250, 252, 255))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
