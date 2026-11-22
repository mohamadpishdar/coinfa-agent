"""Telegram: send drafts with ✅/❌ buttons and handle the clicks (long polling)."""
import json
import logging

import requests

from . import storage
from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

log = logging.getLogger(__name__)
API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def _call(method: str, **kw):
    r = requests.post(f"{API}/{method}", timeout=kw.pop("_timeout", 60), **kw)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"telegram {method}: {data}")
    return data["result"]


def say(text: str) -> None:
    _call("sendMessage", data={"chat_id": TELEGRAM_CHAT_ID, "text": text,
                               "disable_web_page_preview": True})


def send_draft(pid: str, image_path: str, headline: str, caption: str, link: str) -> None:
    with open(image_path, "rb") as f:
        _call("sendPhoto", data={"chat_id": TELEGRAM_CHAT_ID,
                                 "caption": f"📰 {headline}\n🔗 {link}"[:1024]},
              files={"photo": f})
    kb = {"inline_keyboard": [[
        {"text": "✅ تأیید و انتشار", "callback_data": f"ok:{pid}"},
        {"text": "❌ رد", "callback_data": f"no:{pid}"},
    ]]}
    _call("sendMessage", data={"chat_id": TELEGRAM_CHAT_ID, "text": caption[:4000],
                               "reply_markup": json.dumps(kb)})


def poll(on_decision, timeout: int = 50) -> None:
    """One long-poll round. on_decision(pid, approved) -> status text."""
    offset = storage.get("tg_offset", 0)
    updates = _call("getUpdates", data={"offset": offset, "timeout": timeout,
                                        "allowed_updates": json.dumps(["callback_query"])},
                    _timeout=timeout + 15)
    for u in updates:
        storage.update(lambda s: s.update(tg_offset=u["update_id"] + 1))
        cq = u.get("callback_query")
        if not cq:
            continue
        chat = str(cq.get("message", {}).get("chat", {}).get("id", ""))
        if chat != str(TELEGRAM_CHAT_ID):          # ignore anyone else
            continue
        action, _, pid = cq.get("data", "").partition(":")
        _call("answerCallbackQuery", data={"callback_query_id": cq["id"],
                                           "text": "در حال انتشار…" if action == "ok" else "رد شد"})
        status = on_decision(pid, action == "ok")
        msg = cq["message"]
        data = {"chat_id": chat, "message_id": msg["message_id"],
                "text": (msg.get("text", "") + f"\n\n— {status}")[:4096]}
        if status.startswith("⚠️") and msg.get("reply_markup"):
            data["reply_markup"] = json.dumps(msg["reply_markup"])   # keep buttons to retry
        try:   # append the result (buttons removed unless publishing failed)
            _call("editMessageText", data=data)
        except Exception as e:
            log.info("edit failed: %s", e)
