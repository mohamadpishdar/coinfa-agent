"""Cloud mode: no always-on process and no local state.

    python cloud.py send posts.json   # build images, send drafts with ✅/❌ to Telegram
    python cloud.py check             # publish every draft you approved since last check
    python cloud.py status            # show pending/published/schedule info in the group

posts.json is a list of objects written by the scheduled Claude session:
  {"headline", "caption", "keywords", "hashtags", "tag", "image_query", "link", "source"}

The approved image lives on imgbb (7-day expiry) and its path rides inside the button's
callback data; the caption is the text of the message the buttons are attached to.
So Telegram itself is the only state.
"""
import json
import logging
import sys
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


def send(posts_file: str) -> None:
    posts = json.load(open(posts_file, encoding="utf-8"))
    for p in posts:
        try:
            photo, credit = imaging.stock_photo(p.get("image_query", "cryptocurrency"),
                                                       category=p.get("category", "crypto"))
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

    # Send control panel after all drafts
    now = datetime.now(TZ_BRUSSELS)
    schedule = [h for h in range(10, 21)]
    next_checks = [f"{h}:03" for h in schedule if
                   now.replace(hour=h, minute=3, second=0) > now]
    panel = (f"🎛 پنل کنترل CoinFa News\n\n"
             f"📬 {len(posts)} خبر ارسال شد\n"
             f"⏰ چک بعدی: {next_checks[0] if next_checks else 'فردا ۱۰:۰۳'}\n"
             f"📅 زمان‌بندی: هر ساعت (:03) از ۱۰ تا ۲۰\n\n"
             f"✅ روی خبرها بزنید → ساعت بعد منتشر میشه\n"
             f"❌ رد کنید → حذف میشه")
    kb = {"inline_keyboard": [[
        {"text": "📊 وضعیت صف", "callback_data": "qstatus:"},
    ]]}
    _call("sendMessage", data={"chat_id": config.TELEGRAM_CHAT_ID, "text": panel,
                               "reply_markup": json.dumps(kb)})


def check() -> None:
    updates = _call("getUpdates", data={"timeout": 0,
                                        "allowed_updates": json.dumps(["callback_query"])})
    last = None
    published = 0
    skipped_dup = 0
    published_keys = set()

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
        msg_text = msg.get("text", "")

        # Answer the callback so Telegram stops showing the spinner
        try:
            _call("answerCallbackQuery", data={"callback_query_id": cq["id"],
                                               "text": "در حال بررسی..."})
        except Exception:
            pass

        # Handle status/qstatus button clicks
        if action in ("status", "qstatus"):
            # Count remaining pending approvals in this batch
            pending = sum(1 for uu in updates
                         if uu.get("callback_query", {}).get("data", "").startswith("ok:")
                         and "✅ منتشر شد" not in uu.get("callback_query", {}).get("message", {}).get("text", ""))
            now = datetime.now(TZ_BRUSSELS)
            next_h = [f"{h}:03" for h in range(10, 21)
                      if now.replace(hour=h, minute=3, second=0) > now]
            reply = (f"📊 وضعیت صف\n\n"
                     f"🕐 {now.strftime('%H:%M')} بروکسل\n"
                     f"✅ {pending} پست در انتظار انتشار\n"
                     f"⏰ انتشار بعدی: {next_h[0] if next_h else 'فردا ۱۰:۰۳'}\n"
                     f"📬 {published} پست تا الان منتشر شد")
            try:
                _call("sendMessage", data={"chat_id": chat, "text": reply})
            except Exception:
                pass
            continue

        if action == "ok":
            # GUARD 1: skip if this message was already published
            if "✅ منتشر شد" in msg_text:
                log.info("skipping already-published message %s", msg.get("message_id"))
                skipped_dup += 1
                continue

            # GUARD 2: skip if same imgbb key already published in this run
            if key in published_keys:
                log.info("skipping duplicate key %s in same run", key)
                skipped_dup += 1
                continue

            # Show "publishing..." on the message
            try:
                _call("editMessageText", data={
                    "chat_id": chat, "message_id": msg["message_id"],
                    "text": (msg_text + "\n\n— ⏳ در حال انتشار روی اینستاگرام...")[:4096]})
            except Exception:
                pass

            try:
                link = instagram.publish_url(IBB + key, msg_text)
                pub_time = datetime.now(TZ_BRUSSELS).strftime("%H:%M")
                status = f"✅ منتشر شد ({pub_time}): {link}"
                published += 1
                published_keys.add(key)
                # Send a separate notification message
                headline = msg_text.split("\n")[0][:60]
                try:
                    _call("sendMessage", data={
                        "chat_id": chat,
                        "text": f"📢 پست منتشر شد!\n📰 {headline}\n🔗 {link}\n🕐 {pub_time}"})
                except Exception:
                    pass
            except Exception as e:
                log.exception("publish failed")
                status = f"⚠️ انتشار ناموفق: {str(e)[:200]}"
        else:
            status = "❌ رد شد"

        data = {"chat_id": chat, "message_id": msg["message_id"],
                "text": (msg_text + f"\n\n— {status}")[:4096]}
        if status.startswith("⚠️") and msg.get("reply_markup"):
            data["reply_markup"] = json.dumps(msg["reply_markup"])
        try:
            _call("editMessageText", data=data)
        except Exception as e:
            log.info("edit failed: %s", e)
        print(status)

    if last is not None:
        _call("getUpdates", data={"offset": last + 1, "timeout": 0})
    print(f"checked {len(updates)} updates, published {published}, skipped {skipped_dup} duplicates")


def status() -> None:
    """Send a status report to the Telegram group."""
    now = datetime.now(TZ_BRUSSELS)

    # Get recent Instagram posts
    token = config.IG_ACCESS_TOKEN
    base = "graph.facebook.com" if token.startswith("EAA") else "graph.instagram.com"
    try:
        url = f"https://{base}/{config.IG_API_VERSION}/{config.IG_USER_ID}/media"
        r = requests.get(url, params={"access_token": token,
                                       "fields": "timestamp,caption,permalink",
                                       "limit": 5}, timeout=15)
        recent = r.json().get("data", []) if r.ok else []
    except Exception:
        recent = []

    # Next scheduled check times
    schedule = [10, 12, 14, 16, 18, 20]
    next_checks = []
    for h in schedule:
        t = now.replace(hour=h, minute=3, second=0, microsecond=0)
        if t > now:
            next_checks.append(t.strftime("%H:%M"))
    if not next_checks:
        next_checks = ["فردا ۱۰:۰۳"]

    # Check pending updates (peek without consuming)
    updates = _call("getUpdates", data={"timeout": 0,
                                        "allowed_updates": json.dumps(["callback_query"])})
    pending = []
    for u in updates:
        cq = u.get("callback_query", {})
        if cq.get("data", "").startswith("ok:"):
            msg_text = cq.get("message", {}).get("text", "")
            if "✅ منتشر شد" not in msg_text:
                headline = msg_text.split("\n")[0][:50]
                pending.append(headline)

    # Build status message
    lines = ["📊 وضعیت CoinFa News\n"]
    lines.append(f"🕐 {now.strftime('%Y-%m-%d %H:%M')} بروکسل")
    lines.append(f"⏰ چک بعدی: {', '.join(next_checks[:3])}")
    lines.append(f"📅 روزانه ساعت: {', '.join(str(h) + ':03' for h in schedule)}")

    if recent:
        lines.append(f"\n📱 آخرین پست‌های اینستاگرام:")
        for m in recent:
            ts = m.get("timestamp", "")[:16].replace("T", " ")
            caption = (m.get("caption") or "")[:40].replace("\n", " ")
            lines.append(f"  • {ts} — {caption}...")

    if pending:
        lines.append(f"\n✅ {len(pending)} پست در صف انتشار:")
        for h in pending:
            lines.append(f"  • {h}")
        lines.append(f"🕐 انتشار در: {next_checks[0] if next_checks else 'نامشخص'}")
    else:
        lines.append("\n📭 صف انتشار خالیست")
        lines.append("💡 روی پست‌های جدید دکمه ✅ بزنید")

    _call("sendMessage", data={"chat_id": config.TELEGRAM_CHAT_ID,
                               "text": "\n".join(lines)})
    print("Status sent")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "send":
        send(sys.argv[2])
    elif len(sys.argv) >= 2 and sys.argv[1] == "check":
        check()
    elif len(sys.argv) >= 2 and sys.argv[1] == "status":
        status()
    else:
        sys.exit(__doc__)
