"""Compose the post image on the CoinFa template.

Layout (from assets/template.jpg, 864x1080, rendered at 1080x1350):
  - top band: logo at left, headline to the right of the logo
  - golden line at y≈195 (template px)
  - below the line: a photo related to the story, cover-cropped
"""
import io
import time
import logging

import arabic_reshaper
import requests
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

from .config import ASSETS, PEXELS_API_KEY, PIXABAY_API_KEY

log = logging.getLogger(__name__)

W, H = 1080, 1350
S = W / 864                      # template -> output scale
LINE_Y = int(197 * S)            # first row under the golden line
TITLE_BOX = (int(228 * S), int(14 * S), W - int(26 * S), int(186 * S))
FONT_BOLD = str(ASSETS / "Vazirmatn-Black.ttf")
GOLD = (233, 196, 120)


from PIL import features

_RAQM = features.check("raqm")


def _font(size: int) -> ImageFont.FreeTypeFont:
    # With libraqm, Pillow shapes Persian itself; otherwise we reshape + bidi.
    eng = ImageFont.Layout.RAQM if _RAQM else ImageFont.Layout.BASIC
    return ImageFont.truetype(FONT_BOLD, size, layout_engine=eng)


def _rtl(text: str) -> str:
    return text if _RAQM else get_display(arabic_reshaper.reshape(text))


def _kw():
    return {"direction": "rtl", "language": "fa"} if _RAQM else {}


def _wrap(draw, words, font, max_w):
    lines, cur = [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if draw.textlength(_rtl(test), font=font, **_kw()) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _draw_headline(img: Image.Image, text: str) -> None:
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = TITLE_BOX
    bw, bh = x1 - x0, y1 - y0
    words = text.split()
    for size in range(78, 30, -2):
        font = _font(size)
        lines = _wrap(d, words, font, bw)
        lh = int(size * 1.45)
        if len(lines) <= 3 and lh * len(lines) <= bh:
            break
    total = lh * len(lines)
    y = y0 + (bh - total) // 2
    for ln in lines:
        shown = _rtl(ln)
        tw = d.textlength(shown, font=font, **_kw())
        x = x1 - tw                                   # right-aligned (RTL)
        d.text((x + 2, y + 3), shown, font=font, fill=(0, 0, 0), **_kw())   # soft shadow
        d.text((x, y), shown, font=font, fill=(255, 255, 255), **_kw())
        y += lh


def _download(url: str) -> Image.Image:
    return Image.open(io.BytesIO(requests.get(url, timeout=30).content)).convert("RGB")


def _pixabay(query: str) -> Image.Image | None:
    if not PIXABAY_API_KEY:
        return None
    try:
        r = requests.get("https://pixabay.com/api/",
                         params={"key": PIXABAY_API_KEY, "q": query[:100],
                                 "image_type": "photo", "orientation": "vertical",
                                 "safesearch": "true", "per_page": 5}, timeout=20)
        hits = r.json().get("hits", [])
        if not hits:
            words = query.split()
            return _pixabay(" ".join(words[:-1])) if len(words) > 1 else None
        return _download(hits[0]["largeImageURL"])
    except Exception as e:
        log.warning("pixabay failed: %s", e)
        return None


_USED: set[str] = set()   # photo URLs already used in this run, to avoid repeats


def _openverse(query: str) -> tuple[Image.Image | None, str]:
    """Keyless: CC0 / public-domain / CC BY photographs from openverse.org.
    Picks the largest usable photo among the top results; CC BY needs credit,
    which we return and add to the caption."""
    results = None
    for _ in range(3):                      # the API is slow and sometimes answers 5xx
        try:
            r = requests.get("https://api.openverse.org/v1/images/",
                             params={"q": query[:100], "license": "cc0,pdm,by",
                                     "category": "photograph", "page_size": 20},
                             headers={"User-Agent": "CoinFaNewsBot/1.0"}, timeout=40)
            if r.ok:
                results = r.json().get("results", [])
                break
        except (requests.RequestException, ValueError):
            pass
        time.sleep(4)
    if not results:
        return None, ""
    # biggest first; skip small or very wide/tall images
    def good(x):
        wdt, hgt = x.get("width") or 0, x.get("height") or 0
        return wdt >= 900 and hgt >= 500 and 0.5 < wdt / max(hgt, 1) < 2.0
    words = [w[:-1] if w.endswith("s") else w for w in query.lower().split() if len(w) > 2]

    def relevant(x):   # every query word must appear in the title or tags
        text = (x.get("title") or "").lower() + " " + " ".join(
            (t.get("name") or "").lower() for t in (x.get("tags") or []))
        return all(w in text for w in words)

    # keep Openverse's own relevance order; skip repeats
    ranked = [x for x in results if good(x) and relevant(x) and x.get("url") not in _USED]
    for res in ranked[:8]:
        try:
            img = _download(res["url"])
        except Exception:
            continue
        if img.width < 900 or img.height < 500:
            continue
        _USED.add(res["url"])
        lic = (res.get("license") or "").lower()
        credit = "" if lic in ("cc0", "pdm") else (
            f"Photo: {res.get('creator') or 'unknown'} / "
            f"CC {lic.upper()} {res.get('license_version') or ''} via Openverse").strip()
        return img, credit
    return None, ""


def stock_photo(query: str) -> tuple[Image.Image | None, str]:
    """Returns (image, credit line). `query` may hold alternatives separated by "|",
    tried in order. Pixabay/Pexels if keys exist, else Openverse."""
    if "|" in query:
        for q in [q.strip() for q in query.split("|") if q.strip()]:
            img, credit = stock_photo(q)
            if img is not None:
                return img, credit
        return None, ""
    img = _pixabay(query)
    if img is not None:
        return img, ""
    if PEXELS_API_KEY:
        img = _pexels(query)
        if img is not None:
            return img, ""
    return _openverse(query)


def _pexels(query: str) -> Image.Image | None:
    try:
        r = requests.get("https://api.pexels.com/v1/search",
                         headers={"Authorization": PEXELS_API_KEY},
                         params={"query": query, "per_page": 8,
                                 "orientation": "portrait"}, timeout=20)
        photos = r.json().get("photos", [])
        if not photos:
            words = query.split()
            if len(words) > 1:
                return _pexels(" ".join(words[:-1]))
            return None
        return _download(photos[0]["src"]["large2x"])
    except Exception as e:
        log.warning("pexels failed: %s", e)
        return None


def _fallback_photo(w, h, tag: str = "") -> Image.Image:
    """Designed news graphic used when no stock photo is found:
    glowing gradient, network lines, candlestick chart and a gold coin with the tag."""
    import math
    import random
    from PIL import ImageFilter
    rnd = random.Random(tag or "coinfa")
    t = (tag or "").upper()
    accent = {"HACK": (235, 70, 70), "BUG": (235, 70, 70), "SEC": (90, 160, 255),
              "ETF": (80, 170, 255), "LAW": (90, 160, 255)}.get(t, (240, 185, 60))
    # background: vertical gradient + soft glow behind the coin
    g = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(g)
    for y in range(h):
        k = y / h
        d.line([(0, y), (w, y)], fill=(int(10 + 14 * (1 - k)), int(16 + 20 * (1 - k)), int(32 + 30 * (1 - k))))
    glow = Image.new("RGB", (w, h), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx, cy, r = w // 2, int(h * 0.40), int(min(w, h) * 0.23)
    gd.ellipse([cx - r * 2, cy - r * 2, cx + r * 2, cy + r * 2], fill=tuple(int(c * 0.55) for c in accent))
    glow = glow.filter(ImageFilter.GaussianBlur(140))
    g = Image.blend(g, Image.composite(glow, g, glow.convert("L")), 0.85)
    d = ImageDraw.Draw(g, "RGBA")
    # network: faint nodes and links
    pts = [(rnd.randint(0, w), rnd.randint(0, int(h * 0.75))) for _ in range(26)]
    for i, a in enumerate(pts):
        for b in pts[i + 1:]:
            if math.dist(a, b) < 230:
                d.line([a, b], fill=(*accent, 38), width=2)
    for x, y in pts:
        d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(*accent, 110))
    # candlestick chart along the bottom
    base_y, price, n = int(h * 0.80), 0.0, 26
    cw = w / n
    trend = -1 if t in ("HACK", "BUG") else (rnd.choice([-1, 1]))
    series = []
    for i in range(n):
        o = price
        price += rnd.uniform(-1, 1) * 18 + trend * 4
        series.append((o, price))
    lo = min(min(a, b) for a, b in series); hi = max(max(a, b) for a, b in series)
    span = max(hi - lo, 1)
    def Y(v): return base_y - (v - lo) / span * h * 0.22
    for i, (o, c) in enumerate(series):
        x0 = int(i * cw + cw * 0.25); x1 = int(i * cw + cw * 0.75)
        col = (60, 200, 120, 150) if c >= o else (230, 80, 80, 150)
        d.line([((x0 + x1) // 2, Y(max(o, c)) - rnd.randint(4, 18)),
                ((x0 + x1) // 2, Y(min(o, c)) + rnd.randint(4, 18))], fill=col, width=3)
        d.rectangle([x0, min(Y(o), Y(c)), x1, max(Y(o), Y(c)) + 2], fill=col)
    # gold coin with the tag
    for i in range(r, 0, -1):
        k = i / r
        col = (int(150 + 100 * (1 - k)), int(105 + 85 * (1 - k)), int(30 + 40 * (1 - k)))
        d.ellipse([cx - i, cy - i, cx + i, cy + i], fill=col)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 225, 140), width=6)
    d.ellipse([cx - r + 22, cy - r + 22, cx + r - 22, cy + r - 22], outline=(120, 80, 20), width=4)
    if t:
        size = int(r * 0.9)
        while size > 30:
            f = ImageFont.truetype(FONT_BOLD, size)
            if d.textlength(t, font=f) < r * 1.45:
                break
            size -= 6
        bb = d.textbbox((0, 0), t, font=f)
        tx, ty = cx - (bb[2] - bb[0]) / 2 - bb[0], cy - (bb[3] - bb[1]) / 2 - bb[1]
        d.text((tx + 3, ty + 4), t, font=f, fill=(90, 60, 10))
        d.text((tx, ty), t, font=f, fill=(255, 245, 210))
    # bottom fade
    for y in range(int(h * 0.85), h):
        a = int(200 * (y - h * 0.85) / (h * 0.15))
        d.line([(0, y), (w, y)], fill=(8, 12, 24, a))
    return g


def _landscape(photo: Image.Image, w: int, h: int) -> Image.Image:
    """Wide photo: sharp full-width copy over a blurred, darkened fill of itself."""
    from PIL import ImageEnhance, ImageFilter
    bg = _cover(photo, w, h).filter(ImageFilter.GaussianBlur(28))
    bg = ImageEnhance.Brightness(bg).enhance(0.45)
    fg = photo.resize((w, int(photo.height * w / photo.width)), Image.LANCZOS)
    y = (h - fg.height) // 2 - int(h * 0.04)
    bg.paste(fg, (0, max(y, 0)))
    d = ImageDraw.Draw(bg)
    d.line([(0, y - 2), (w, y - 2)], fill=GOLD, width=3)
    d.line([(0, y + fg.height + 1), (w, y + fg.height + 1)], fill=GOLD, width=3)
    return bg


def _cover(photo: Image.Image, w: int, h: int) -> Image.Image:
    r = max(w / photo.width, h / photo.height)
    p = photo.resize((int(photo.width * r) + 1, int(photo.height * r) + 1), Image.LANCZOS)
    left = (p.width - w) // 2
    top = max(0, (p.height - h) // 3)               # bias toward upper part
    return p.crop((left, top, left + w, top + h))


def compose(headline: str, photo: Image.Image | None, out_path, tag: str = "") -> str:
    base = Image.open(ASSETS / "template.jpg").convert("RGB").resize((W, H), Image.LANCZOS)
    ph_h = H - LINE_Y
    if photo is None:
        ph = _fallback_photo(W, ph_h, tag)
    elif photo.width / photo.height > 1.1:
        ph = _landscape(photo, W, ph_h)
    else:
        ph = _cover(photo, W, ph_h)
    # fade the photo's top edge into the dark band for a clean join
    mask = Image.new("L", (W, ph_h), 255)
    md = ImageDraw.Draw(mask)
    for i in range(40):
        md.line([(0, i), (W, i)], fill=int(120 + 135 * i / 40))
    base.paste(ph, (0, LINE_Y), mask)
    _draw_headline(base, headline)
    base.save(out_path, "JPEG", quality=92, optimize=True)
    return str(out_path)
