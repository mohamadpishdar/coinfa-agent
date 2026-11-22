"""Collect fresh items from crypto news RSS feeds."""
import calendar
import logging
import re
import time
from dataclasses import dataclass

import feedparser
import requests

from . import storage
from .config import FEEDS, MAX_NEWS_AGE_HOURS

log = logging.getLogger(__name__)
logging.getLogger("trafilatura").setLevel(logging.CRITICAL)
UA = {"User-Agent": "Mozilla/5.0 (CoinFa news bot)"}


@dataclass
class Item:
    source: str
    title: str
    link: str
    summary: str
    published: float
    body: str = ""


def _clean(html: str) -> str:
    txt = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", txt).strip()


def collect() -> list[Item]:
    cutoff = time.time() - MAX_NEWS_AGE_HOURS * 3600
    items: list[Item] = []
    links: set[str] = set()
    for name, url in FEEDS:
        try:
            raw = requests.get(url, headers=UA, timeout=20).content
            feed = feedparser.parse(raw)
        except Exception as e:  # one dead feed must not stop the run
            log.warning("feed %s failed: %s", name, e)
            continue
        for e in feed.entries[:25]:
            link = e.get("link", "")
            t = e.get("published_parsed") or e.get("updated_parsed")
            ts = calendar.timegm(t) if t else time.time()
            if not link or link in links or ts < cutoff or storage.is_seen(link):
                continue
            links.add(link)
            items.append(Item(name, _clean(e.get("title", "")), link,
                              _clean(e.get("summary", ""))[:600], ts))
    items.sort(key=lambda i: i.published, reverse=True)
    log.info("collected %d fresh items", len(items))
    return items


def fetch_body(item: Item) -> str:
    """Best-effort full text; falls back to the RSS summary."""
    try:
        import trafilatura
        html = requests.get(item.link, headers=UA, timeout=20).text
        text = trafilatura.extract(html) or ""
        if len(text) > 300:
            return text[:6000]
    except Exception as e:
        log.info("full text failed for %s: %s", item.link, e)
    return item.summary
