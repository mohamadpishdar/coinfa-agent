"""Claude: pick the most important stories, then write Persian posts."""
import json
import logging
import re

import requests

from .config import (ANTHROPIC_API_KEY, BRAND_HASHTAG, CLAUDE_MODEL,
                     QUOTA_CRYPTO, QUOTA_BOURSE, QUOTA_MARKET, QUOTA_MEME)

log = logging.getLogger(__name__)


def _claude(system: str, user: str, max_tokens: int = 1500) -> str:
    body = {"model": CLAUDE_MODEL, "max_tokens": max_tokens, "system": system,
            "messages": [{"role": "user", "content": user}]}
    base = {"anthropic-version": "2023-06-01", "content-type": "application/json"}
    for auth in ({"x-api-key": ANTHROPIC_API_KEY},
                 {"Authorization": f"Bearer {ANTHROPIC_API_KEY}"}):
        r = requests.post("https://api.anthropic.com/v1/messages",
                          headers={**base, **auth}, json=body, timeout=120)
        if r.status_code not in (401, 403):
            break
    if not r.ok:
        raise RuntimeError(f"Claude API {r.status_code}: {r.text[:300]}")
    return "".join(b.get("text", "") for b in r.json()["content"])


def _json(text: str):
    m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    return json.loads(m.group(1) if m else text)


def _pick_category(items, category: str, n: int) -> list[int]:
    """Pick top n items from a specific category. Returns global indexes."""
    if n <= 0:
        return []
    cat_items = [(i, it) for i, it in enumerate(items) if it.category == category]
    if not cat_items:
        return []
    if len(cat_items) <= n:
        return [i for i, _ in cat_items]

    lst = "\n".join(f"{j}. [{it.source}] {it.title} — {it.summary[:200]}"
                    for j, (i, it) in enumerate(cat_items))

    if category == "crypto":
        role = ("You are the news editor of a Persian crypto news Instagram page. "
                "Pick stories with real news value for Persian-speaking crypto users: "
                "market-moving events, regulation, major projects, hacks/security, "
                "big-company adoption. Skip sponsored posts, price-prediction fluff, "
                "press releases, and several articles about the same story (keep one).")
    elif category == "bourse":
        role = ("You are the news editor of a Persian financial news page. "
                "Pick the most important stories about Tehran Stock Exchange (بورس تهران), "
                "TEDPIX index moves, major IPOs, big trades, regulatory changes, "
                "and notable sector moves. Skip duplicate stories and opinion pieces.")
    elif category == "meme":
        role = ("You are the news editor of a Persian crypto news page. "
                "Pick ONLY the single most newsworthy memecoin story — something with "
                "real impact: a massive price move, celebrity involvement, exchange listing, "
                "or regulatory action. The memecoin must be well-known (DOGE, SHIB, PEPE, "
                "FLOKI, BONK, WIF etc). Skip minor price changes and shitcoin promotions.")
    else:  # market
        role = ("You are the news editor of a Persian financial news page. "
                "Pick stories about Iran's housing market (مسکن), gold & coin prices (طلا و سکه), "
                "car market (خودرو), or silver (نقره). Focus on price changes, "
                "government policy, and market-moving news. Skip opinion and analysis.")

    out = _claude(
        role,
        f"Choose the {n} best stories. Reply with ONLY a JSON array of their "
        f"numbers, most important first.\n\n{lst}", 200)
    try:
        local_idx = [int(i) for i in _json(out) if 0 <= int(i) < len(cat_items)]
        local_idx = list(dict.fromkeys(local_idx))[:n]
        return [cat_items[j][0] for j in local_idx]
    except Exception:
        log.warning("pick parse failed for %s: %s", category, out[:200])
        return [i for i, _ in cat_items[:n]]


def pick(items, n: int) -> list[int]:
    """Return indexes of the n most important stories, respecting category quotas."""
    crypto_idx = _pick_category(items, "crypto", QUOTA_CRYPTO)
    bourse_idx = _pick_category(items, "bourse", QUOTA_BOURSE)
    market_idx = _pick_category(items, "market", QUOTA_MARKET)
    meme_idx = _pick_category(items, "meme", QUOTA_MEME)

    result = crypto_idx + bourse_idx + market_idx + meme_idx

    # If some categories had fewer items, fill from crypto
    if len(result) < n:
        used = set(result)
        extras = [i for i, it in enumerate(items)
                  if i not in used and it.category == "crypto"]
        result.extend(extras[:n - len(result)])

    return result[:n]


SYSTEM_WRITER = f"""تو سردبیر و نویسنده‌ی پیج خبری «کوین فا نیوز» هستی. خبرها را
به فارسیِ روان، خودمانی و کاملاً انسانی بازنویسی می‌کنی؛ طوری که هیچ‌کس نفهمد ترجمه یا متن ماشینی است.

اگر خبر به زبان فارسی است، آن را بازنویسی و خلاصه کن (ترجمه نکن). اگر انگلیسی است، به فارسی روان بنویس.

قواعد قطعی:
- ترجمه‌ی کلمه‌به‌کلمه ممنوع. مثل یک آدم که خبر را خوانده و برای دوستش تعریف می‌کند بنویس.
- لحن: محاوره‌ای مؤدب و گرم (مثل «دارن»، «میشه»، «یعنی چی؟»)، ولی دقیق و بی‌اغراق.
- نیم‌فاصله را همیشه درست بگذار (می‌شود، داده‌ها، بزرگ‌ترین، رمزارزها).
- عدد، نام، تاریخ و مبلغ را دقیقاً مطابق متن اصلی بیاور؛ چیزی از خودت اضافه نکن و حدس نزن.
- هیچ توصیه‌ی خرید/فروش، سیگنال، «الان وقت خریده» یا وعده‌ی سود ننویس. پیج فقط خبری است.
- کلمات زرد و ترسناک مثل «بمب»، «انفجار»، «سکته» ممنوع.
- برای خبرهای رمزارز: نام پروژه یا کوین را یک‌بار به انگلیسی داخل پرانتز بیاور، مثل: اتریوم (ETH).
- برای خبرهای میم‌کوین: لحن کمی شادتر و خودمانی‌تر، ولی همچنان دقیق.
- برای خبرهای بورس ایران: نماد شرکت را ذکر کن اگر مرتبط باشد.
- برای خبرهای طلا/مسکن/خودرو: قیمت‌ها را به تومان بیاور اگر در متن هست.

خروجی فقط یک JSON با این کلیدها:
"headline": تیتر فارسی خیلی کوتاه و تیتروار برای روی تصویر؛ حداکثر ۷ کلمه و ۴۰ کاراکتر، بدون نقطه.
"caption": کپشن اینستاگرام ۵ تا ۹ خط کوتاه: خط اول یک قلاب جذاب، بعد اصل خبر در ۲–۴ خط، بعد یک خط «چرا مهمه؟»،
  بعد یک سؤال برای کامنت، بعد خط «منبع: <نام منبع>». حداکثر ۳ ایموجی در کل متن. هشتگ داخل کپشن نگذار.
"keywords": ۴ تا ۶ کلیدواژه‌ی فارسی که مردم جست‌وجو می‌کنند (بدون #)، به‌صورت آرایه.
"hashtags": ۸ تا ۱۲ هشتگ فارسی و انگلیسی به‌صورت آرایه؛ هر هشتگ بدون فاصله و با _ (مثل #ارز_دیجیتال)، و حتماً {BRAND_HASHTAG}.
"tag": یک کلمه یا نماد انگلیسی کوتاه برای پس‌زمینه‌ی تصویر وقتی عکس پیدا نشد (مثل "BTC" یا "TEPIX" یا "GOLD" یا "DOGE")، حداکثر ۸ حرف.
"image_query": ۲ تا ۴ کلمه‌ی انگلیسی برای پیدا کردن عکس استوک مرتبط (مثل "bitcoin trading chart" یا "gold coins bars" یا "shiba inu dog crypto"). بدون نام شخص یا برند خاص.
"""


def write(item, body: str) -> dict:
    out = _claude(SYSTEM_WRITER,
                  f"منبع: {item.source}\nدسته‌بندی: {item.category}\n"
                  f"تیتر اصلی: {item.title}\nلینک: {item.link}\n\n"
                  f"متن خبر:\n{body}", 1800)
    d = _json(out)
    tags = [t if t.startswith("#") else "#" + t for t in d.get("hashtags", [])]
    tags = [re.sub(r"\s+", "_", t.strip()) for t in tags]
    if BRAND_HASHTAG not in tags:
        tags.insert(0, BRAND_HASHTAG)
    d["hashtags"] = list(dict.fromkeys(tags))[:15]
    d["headline"] = d.get("headline", "").strip().rstrip(".")
    return d


def full_caption(post: dict, credit: str = "") -> str:
    kw = " · ".join(post.get("keywords", []))
    parts = [post["caption"].strip()]
    if kw:
        parts.append(f"🔎 {kw}")
    if credit:
        parts.append(f"📷 {credit}")
    parts.append(" ".join(post["hashtags"]))
    return "\n\n".join(parts)[:2150]
