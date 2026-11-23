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
SAFE_SCALE = 0.86                # design scaled to 86% -> ~75px side margin
BG = (6, 14, 25)                 # template's dark navy, used for the margin


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


def _openverse(query: str) -> tuple[Image.Image | None, str]:
    """Keyless: CC0 / public-domain / CC BY photos from openverse.org.
    CC BY needs credit, which we return and add to the caption."""
    try:
        results = None
        for _ in range(3):                      # the API sometimes answers 504
            try:
                r = requests.get("https://api.openverse.org/v1/images/",
                                 params={"q": query[:100], "license": "cc0,pdm,by",
                                         "page_size": 10},
                                 headers={"User-Agent": "CoinFaNewsBot/1.0"}, timeout=25)
            except requests.RequestException:
                time.sleep(3)
                continue
            if r.ok:
                results = r.json().get("results", [])
                break
            time.sleep(3)
        if results is None:
            return None, ""
        if not results:
            words = query.split()
            return _openverse(" ".join(words[:-1])) if len(words) > 1 else (None, "")
        for res in results[:5]:
            try:
                img = _download(res["url"])
                if min(img.size) < 500:
                    continue
                lic = (res.get("license") or "").lower()
                credit = "" if lic in ("cc0", "pdm") else (
                    f"Photo: {res.get('creator') or 'unknown'} / "
                    f"CC {lic.upper()} {res.get('license_version') or ''} via Openverse").strip()
                return img, credit
            except Exception:
                continue
    except Exception as e:
        log.warning("openverse failed: %s", e)
    return None, ""


def stock_photo(query: str) -> tuple[Image.Image | None, str]:
    """Returns (image, credit line). Pixabay/Pexels if keys exist, else Openverse."""
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
    """Dark gradient with a large gold keyword, used if no stock photo is found."""
    g = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(g)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=(int(18 + 22 * (1 - t)), int(26 + 26 * (1 - t)), int(44 + 34 * (1 - t))))
    if tag:
        size = 260
        while size > 60:
            f = ImageFont.truetype(FONT_BOLD, size)
            if d.textlength(tag, font=f) < w * 0.85:
                break
            size -= 10
        tw = d.textlength(tag, font=f)
        d.text(((w - tw) / 2, h * 0.38), tag, font=f, fill=(18, 26, 44),
               stroke_width=4, stroke_fill=GOLD)
        for i in range(0, w, 60):          # subtle chart-like diagonal lines
            d.line([(i, h), (i + 300, h - 260)], fill=(38, 52, 78), width=2)
    return g


def _cover(photo: Image.Image, w: int, h: int) -> Image.Image:
    r = max(w / photo.width, h / photo.height)
    p = photo.resize((int(photo.width * r) + 1, int(photo.height * r) + 1), Image.LANCZOS)
    left = (p.width - w) // 2
    top = max(0, (p.height - h) // 3)               # bias toward upper part
    return p.crop((left, top, left + w, top + h))


def compose(headline: str, photo: Image.Image | None, out_path, tag: str = "") -> str:
    base = Image.open(ASSETS / "template.jpg").convert("RGB").resize((W, H), Image.LANCZOS)
    ph_h = H - LINE_Y
    ph = _cover(photo, W, ph_h) if photo else _fallback_photo(W, ph_h, tag)
    # fade the photo's top edge into the dark band for a clean join
    mask = Image.new("L", (W, ph_h), 255)
    md = ImageDraw.Draw(mask)
    for i in range(40):
        md.line([(0, i), (W, i)], fill=int(120 + 135 * i / 40))
    base.paste(ph, (0, LINE_Y), mask)
    _draw_headline(base, headline)
    # Instagram's profile grid crops 4:5 posts to 3:4 (~34px off each side), so
    # shrink the whole design into a centred safe area on a dark canvas.
    sw, sh = int(W * SAFE_SCALE), int(H * SAFE_SCALE)
    canvas = Image.new("RGB", (W, H), BG)
    canvas.paste(base.resize((sw, sh), Image.LANCZOS), ((W - sw) // 2, (H - sh) // 2))
    canvas.save(out_path, "JPEG", quality=92, optimize=True)
    return str(out_path)
