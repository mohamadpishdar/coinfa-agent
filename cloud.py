"""Cloud mode: no always-on process and no local state.

    python cloud.py send posts.json   # build images, send drafts with ✅/❌ to Telegram
    python cloud.py check             # publish ONE approved draft if timing is right

posts.json is a list of objects written by the scheduled Claude session:
  {"headline", "caption", "keywords", "hashtags", "tag", "image_query", "link", "source"}

The approved image lives on imgbb (7-day expiry) and its path rides inside the button's
callback data; the caption is the text of the message the buttons are attached to.
So Telegram itself is the only state.

SMART PUBLISHING: Instead of publishing all approved posts at once, publishes
at most ONE per check cycle, with a minimum gap between posts (IG_POST_GAP_MINUTES).
This follows Instagram's algorithm preference for spaced-out, consistent posting.
"""
import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone, timedelta

import requests

from coinfa import config, imaging, instagram, writer
from coinfa.telegram import _call

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("coinfa.cloud")
IBB = "https://i.ibb.co/"
TZ_BRUSSELS = timezone(timedelta(hours=1))


def _host(path: str) -> str:
    with open(path, "rb") as f:
        r = requests.post("https://api.imgbb.com/1/upload",
                          params={"key": config.IMGBB_API_KEY, "expiration": 7 * 86400,
                                  "name": "p"},
                          files={"image": ("p.jpg", f, "image/jpeg")}, timeout=60)
    r.raise_for_status()
    return r.json()["data"]["url"]


def _last_post_time() -> float | None:
    """Check the most recent Instagram post time via IG API.
    Returns epoch timestamp or None if unknown."""
    try:
        token = config.IG_ACCESS_TOKEN
        base = "graph.facebook.com" if token.startswith("EAA") else "graph.instagram.com"
        url = f"https://{base}/{config.IG_API_VERSION}/{config.IG_USER_ID}/media"
        r = requests.get(url, params={"access_token": token, "fields": "timestamp",
                                       "limit": 1}, timeout=15)
        if r.ok:
            data = r.json().get("data", [])
            if data:
                ts_str = data[0]["timestamp"]  # ISO 8601
                from datetime import datetime as dt
                return dt.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
    except Exception as e:
        log.info("could not fetch last post time: %s", e)
    return None


def _ok_to_publish() -> bool:
    """Check if enough time has passed since last post and hour is good."""
    now = datetime.now(TZ_BRUSSELS)
    hour = now.hour

    # Only publish during reasonable hours (9am - 10pm Brussels)
    if hour < 9 or hour > 22:
        log.info("outside posting hours (%d), skipping", hour)
        return False

    # Check gap since last post
    last = _last_post_time()
    if last is not None:
        gap = time.time() - last
        min_gap = config.IG_POST_GAP_MINUTES * 60
        if gap < min_gap:
            log.info("only %d min since last post (need %d), skipping",
                     int(gap / 60), config.IG_POST_GAP_MINUTES)
            return False

    return True


def send(posts_file: str) -> None:
    posts = json.load(open(posts_file, encoding="utf-8"))
    for p in posts:
        try:
            photo, credit = imaging.stock_photo(p.get("image_query", "cryptocurrency"))
            out = config.OUT / f"{uuid.uuid4().hex[:8]}.jpg"
            imaging.compose(p["headline"], photo, out, p.get("tag", ""))
            caption = writer.full_caption(p, credit)
            url = _host(str(out))
            key = url[len(IBB):] if url.startswith(IBB) else ""
            if not key or len(key) > 60:
                raise RuntimeError(f"unexpected image url {url}")
            with open(out, "rb") as f:
                _call("sendPhoto", data={"chat_id": config.TELEGRAM_CHAT_ID,
                                         "caption": f"📰 {p['headline']}\n🔗 {p.get('link', '')}"[:1024]},
                      files={"photo": f})
            kb = {"inline_keyboard": [[
                {"text": "✅ تأیید و انتشار", "callback_data": f"ok:{key}"},
                {"text": "❌ رد", "callback_data": "no:"},
            ]]}
            _call("sendMessage", data={"chat_id": config.TELEGRAM_CHAT_ID, "text": caption,
                                       "reply_markup": json.dumps(kb)})
            print("SENT", p.get("link", ""))
        except Exception as e:
            log.exception("draft failed: %s", e)
            print("FAILED", p.get("link", ""), e)


def check() -> None:
    updates = _call("getUpdates", data={"timeout": 0,
                                        "allowed_updates": json.dumps(["callback_query"])})
    last = None
    published_one = False

    # Collect all pending approvals and rejections
    actions = []
    for u in updates:
        last = u["update_id"]
        cq = u.get("callback_query")
        if not cq:
            continue
        msg = cq.get("message", {})
        chat = str(msg.get("chat", {}).get("id", ""))
        if chat != str(config.TELEGRAM_CHAT_ID):
            continue
        action, _, key = cq.get("data", "").partition(":")
        actions.append({"action": action, "key": key, "msg": msg, "chat": chat})

    for item in actions:
        action = item["action"]
        key = item["key"]
        msg = item["msg"]
        chat = item["chat"]

        if action == "ok":
            if published_one or not _ok_to_publish():
                # Queue: don't consume the update yet, leave buttons for next check
                # But we must acknowledge updates to avoid re-processing rejections
                # So we skip publishing but still process the update
                log.info("delaying publish (already published one or timing not right)")
                # Re-add the approval button so it can be published next cycle
                kb = {"inline_keyboard": [[
                    {"text": "✅ تأیید و انتشار", "callback_data": f"ok:{key}"},
                    {"text": "❌ رد", "callback_data": "no:"},
                ]]}
                data = {"chat_id": chat, "message_id": msg["message_id"],
                        "text": msg.get("text", "") + "\n\n⏳ در صف انتشار...",
                        "reply_markup": json.dumps(kb)}
                try:
                    _call("editMessageText", data=data)
                except Exception:
                    pass
                continue

            try:
                link = instagram.publish_url(IBB + key, msg.get("text", ""))
                status = f"✅ منتشر شد: {link}"
                published_one = True
            except Exception as e:
                log.exception("publish failed")
                status = f"⚠️ انتشار ناموفق: {str(e)[:200]}"
        else:
            status = "❌ رد شد"

        data = {"chat_id": chat, "message_id": msg["message_id"],
                "text": (msg.get("text", "").replace("\n\n⏳ در صف انتشار...", "")
                         + f"\n\n— {status}")[:4096]}
        if status.startswith("⚠️") and msg.get("reply_markup"):
            data["reply_markup"] = json.dumps(msg["reply_markup"])
        try:
            _call("editMessageText", data=data)
        except Exception as e:
            log.info("edit failed: %s", e)
        print(status)

    if last is not None:
        _call("getUpdates", data={"offset": last + 1, "timeout": 0})
    print("checked", len(updates), "updates,",
          "published 1" if published_one else "no publish this cycle")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "send":
        send(sys.argv[2])
    elif len(sys.argv) >= 2 and sys.argv[1] == "check":
        check()
    else:
        sys.exit(__doc__)
