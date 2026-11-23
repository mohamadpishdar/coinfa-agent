"""Claude: pick the most important stories, then write Persian posts."""
import json
import logging
import re

import requests

from .config import ANTHROPIC_API_KEY, BRAND_HASHTAG, CLAUDE_MODEL

log = logging.getLogger(__name__)


def _claude(system: str, user: str, max_tokens: int = 1500) -> str:
    body = {"model": CLAUDE_MODEL, "max_tokens": max_tokens, "system": system,
            "messages": [{"role": "user", "content": user}]}
    base = {"anthropic-version": "2023-06-01", "content-type": "application/json"}
    # classic keys use x-api-key; some newer key types expect a Bearer header
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


def pick(items, n: int) -> list[int]:
    """Return indexes of the n most important, non-duplicate stories."""
    if len(items) <= n:
        return list(range(len(items)))
    lst = "\n".join(f"{i}. [{it.source}] {it.title} — {it.summary[:200]}"
                    for i, it in enumerate(items[:80]))
    out = _claude(
        "You are the news editor of a Persian crypto news Instagram page. "
        "Pick stories with real news value for Persian-speaking crypto users: "
        "market-moving events, regulation, major projects, hacks/security, "
        "big-company adoption. Skip sponsored posts, price-prediction fluff, "
        "press releases, and several articles about the same story (keep one).",
        f"Choose the {n} best stories. Reply with ONLY a JSON array of their "
        f"numbers, most important first.\n\n{lst}", 200)
    try:
        idx = [int(i) for i in _json(out) if 0 <= int(i) < len(items)]
        return list(dict.fromkeys(idx))[:n]
    except Exception:
        log.warning("pick parse failed: %s", out[:200])
        return list(range(n))


SYSTEM_WRITER = f"""تو سردبیر و نویسنده‌ی پیج خبری «کوین فا نیوز» هستی. خبرهای انگلیسی رمزارز را
به فارسیِ روان، خودمانی و کاملاً انسانی بازنویسی می‌کنی؛ طوری که هیچ‌کس نفهمد ترجمه یا متن ماشینی است.

قواعد قطعی:
- ترجمه‌ی کلمه‌به‌کلمه ممنوع. مثل یک آدم که خبر را خوانده و برای دوستش تعریف می‌کند بنویس.
- لحن: محاوره‌ای مؤدب و گرم (مثل «دارن»، «میشه»، «یعنی چی؟»)، ولی دقیق و بی‌اغراق.
- نیم‌فاصله را همیشه درست بگذار (می‌شود، داده‌ها، بزرگ‌ترین، رمزارزها).
- عدد، نام، تاریخ و مبلغ را دقیقاً مطابق متن اصلی بیاور؛ چیزی از خودت اضافه نکن و حدس نزن.
- هیچ توصیه‌ی خرید/فروش، سیگنال، «الان وقت خریده» یا وعده‌ی سود ننویس. پیج فقط خبری است.
- کلمات زرد و ترسناک مثل «بمب»، «انفجار»، «سکته» ممنوع.
- نام پروژه یا کوین را یک‌بار به انگلیسی داخل پرانتز بیاور، مثل: اتریوم (ETH).

خروجی فقط یک JSON با این کلیدها:
"headline": تیتر فارسی خیلی کوتاه و تیتروار برای روی تصویر؛ حداکثر ۷ کلمه و ۴۰ کاراکتر، بدون نقطه.
"caption": کپشن اینستاگرام ۵ تا ۹ خط کوتاه: خط اول یک قلاب جذاب، بعد اصل خبر در ۲–۴ خط، بعد یک خط «چرا مهمه؟»،
  بعد یک سؤال برای کامنت، بعد خط «منبع: <نام منبع>». حداکثر ۳ ایموجی در کل متن. هشتگ داخل کپشن نگذار.
"keywords": ۴ تا ۶ کلیدواژه‌ی فارسی که مردم جست‌وجو می‌کنند (بدون #)، به‌صورت آرایه.
"hashtags": ۸ تا ۱۲ هشتگ فارسی و انگلیسی به‌صورت آرایه؛ هر هشتگ بدون فاصله و با _ (مثل #ارز_دیجیتال)، و حتماً {BRAND_HASHTAG}.
"tag": یک کلمه یا نماد انگلیسی کوتاه برای پس‌زمینه‌ی تصویر وقتی عکس پیدا نشد (مثل "BTC" یا "ETF")، حداکثر ۸ حرف.
"image_query": ۲ تا ۴ کلمه‌ی انگلیسی برای پیدا کردن عکس استوک مرتبط (مثل "bitcoin trading chart"). بدون نام شخص یا برند خاص.
"""


def write(item, body: str) -> dict:
    out = _claude(SYSTEM_WRITER,
                  f"منبع: {item.source}\nتیتر اصلی: {item.title}\nلینک: {item.link}\n\n"
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
