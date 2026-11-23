"""Collect fresh items from crypto & Iranian market RSS feeds."""
import calendar
import logging
import re
import time
from dataclasses import dataclass, field

import feedparser
import requests

from . import storage
from .config import (FEEDS_CRYPTO, FEEDS_BOURSE, FEEDS_MARKET,
                     MAX_NEWS_AGE_HOURS)

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
    category: str = "crypto"   # "crypto", "bourse", "market"
    body: str = ""


def _clean(html: str) -> str:
    txt = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", txt).strip()


def _collect_feeds(feed_list: list[tuple[str, str]], category: str,
                   cutoff: float) -> list[Item]:
    """Fetch items from a list of (name, url) feeds with the given category."""
    items: list[Item] = []
    links: set[str] = set()
    for name, url in feed_list:
        try:
            raw = requests.get(url, headers=UA, timeout=20).content
            feed = feedparser.parse(raw)
        except Exception as e:
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
                              _clean(e.get("summary", ""))[:600], ts,
                              category=category))
    return items


def collect() -> list[Item]:
    cutoff = time.time() - MAX_NEWS_AGE_HOURS * 3600
    crypto = _collect_feeds(FEEDS_CRYPTO, "crypto", cutoff)
    bourse = _collect_feeds(FEEDS_BOURSE, "bourse", cutoff)
    market = _collect_feeds(FEEDS_MARKET, "market", cutoff)

    # Filter market items: keep only those about gold/housing/car/silver
    market_kw = re.compile(
        r"طلا|سکه|نقره|مسکن|خانه|آپارتمان|خودرو|پراید|تیبا|دنا|ساینا|پژو|"
        r"ایران.?خودرو|سایپا|اجاره|رهن|ملک|قیمت.?زمین|بازار.?فلز",
        re.IGNORECASE,
    )
    market = [it for it in market if market_kw.search(it.title + " " + it.summary)]

    all_items = crypto + bourse + market
    all_items.sort(key=lambda i: i.published, reverse=True)

    log.info("collected %d crypto, %d bourse, %d market items",
             len(crypto), len(bourse), len(market))
    return all_items


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
