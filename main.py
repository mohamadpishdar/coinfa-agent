"""CoinFa News agent.

Run it whenever your computer is on:
    python main.py            # makes up to DAILY_POSTS drafts per day, waits for your ✅/❌
    python main.py --dry      # test: makes 1 draft into data/out/ without Telegram/Instagram
"""
import logging
import sys
import threading
import time
import uuid

from coinfa import config, feeds, imaging, storage, writer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(),
                              logging.FileHandler(config.DATA / "agent.log", encoding="utf-8")])
log = logging.getLogger("coinfa")
_gen_lock = threading.Lock()


def make_drafts(n: int, dry: bool = False) -> int:
    items = feeds.collect()
    if not items:
        return 0
    made = 0
    for i in writer.pick(items, n):
        it = items[i]
        storage.mark_seen(it.link)
        try:
            post = writer.write(it, feeds.fetch_body(it))
            photo, credit = imaging.stock_photo(post.get("image_query", "cryptocurrency"))
            pid = uuid.uuid4().hex[:10]
            img = imaging.compose(post["headline"], photo, config.OUT / f"{pid}.jpg",
                                  post.get("tag", ""))
            caption = writer.full_caption(post, credit)
            if dry:
                (config.OUT / f"{pid}.txt").write_text(
                    f"{post['headline']}\n\n{caption}\n\n{it.link}", encoding="utf-8")
                log.info("dry draft: %s", img)
            else:
                storage.update(lambda s: s["pending"].__setitem__(
                    pid, {"image": img, "caption": caption, "link": it.link,
                          "headline": post["headline"]}))
                from coinfa import telegram
                telegram.send_draft(pid, img, post["headline"], caption, it.link)
                storage.add_made_today()
            made += 1
        except Exception as e:
            log.exception("draft failed for %s: %s", it.link, e)
    return made


def on_decision(pid: str, approved: bool) -> str:
    p = storage.get("pending", {}).get(pid)
    if not p:
        return "این مورد قبلاً بررسی شده"
    if not approved:
        storage.update(lambda s: s["pending"].pop(pid, None))
        return "❌ رد شد"
    try:
        from coinfa import instagram
        link = instagram.publish(p["image"], p["caption"])
        storage.update(lambda s: s["pending"].pop(pid, None))
        return f"✅ منتشر شد: {link}"
    except Exception as e:
        log.exception("publish failed")
        return f"⚠️ انتشار ناموفق بود (دوباره ✅ بزنید یا لاگ را ببینید): {str(e)[:200]}"


def _generate_if_needed():
    if not _gen_lock.acquire(blocking=False):
        return
    try:
        need = config.DAILY_POSTS - storage.made_today()
        if need > 0:
            log.info("making %d drafts", need)
            make_drafts(need)
    except Exception:
        log.exception("generation round failed")
    finally:
        _gen_lock.release()


def _check_config():
    missing = [k for k in ("ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
                           "IMGBB_API_KEY", "IG_USER_ID", "IG_ACCESS_TOKEN")
               if not getattr(config, k)]
    if not (config.PIXABAY_API_KEY or config.PEXELS_API_KEY):
        log.info("No Pixabay/Pexels key: using Openverse (free, no key) for photos")
    if missing:
        sys.exit("Missing in .env: " + ", ".join(missing))


def main():
    if "--dry" in sys.argv:
        if not config.ANTHROPIC_API_KEY:
            sys.exit("Set ANTHROPIC_API_KEY in .env")
        print("made", make_drafts(1, dry=True), "draft(s) in", config.OUT)
        return
    _check_config()
    from coinfa import telegram
    log.info("CoinFa agent started")
    last_check = 0.0
    while True:
        if time.time() - last_check > config.CHECK_EVERY_MINUTES * 60:
            last_check = time.time()
            threading.Thread(target=_generate_if_needed, daemon=True).start()
        try:
            telegram.poll(on_decision)
        except Exception as e:
            log.warning("telegram poll: %s", e)
            time.sleep(10)


if __name__ == "__main__":
    main()
