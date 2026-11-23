"""Settings loaded from the .env file next to main.py."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ASSETS = ROOT / "assets"
OUT = DATA / "out"


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env(ROOT / ".env")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
CLAUDE_MODEL = env("CLAUDE_MODEL", "claude-sonnet-5-5")

TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = env("TELEGRAM_CHAT_ID")  # your own numeric chat id

PEXELS_API_KEY = env("PEXELS_API_KEY")
PIXABAY_API_KEY = env("PIXABAY_API_KEY")
IMGBB_API_KEY = env("IMGBB_API_KEY")

IG_USER_ID = env("IG_USER_ID")
IG_ACCESS_TOKEN = env("IG_ACCESS_TOKEN")
IG_API_VERSION = env("IG_API_VERSION", "v23.0")

DAILY_POSTS = int(env("DAILY_POSTS", "7"))
MAX_NEWS_AGE_HOURS = int(env("MAX_NEWS_AGE_HOURS", "24"))
CHECK_EVERY_MINUTES = int(env("CHECK_EVERY_MINUTES", "30"))
BRAND_HASHTAG = env("BRAND_HASHTAG", "#کوین_فا_نیوز")

# --- Category quotas per day ---
QUOTA_CRYPTO = int(env("QUOTA_CRYPTO", "3"))
QUOTA_BOURSE = int(env("QUOTA_BOURSE", "2"))
QUOTA_MARKET = int(env("QUOTA_MARKET", "1"))  # housing, gold, car, silver
QUOTA_MEME = int(env("QUOTA_MEME", "1"))      # memecoin news (optional, 0-1)

# --- Instagram algorithm: staggered publishing ---
# Optimal posting hours in user's timezone (Europe/Brussels)
# Posts are spread across these slots, max 1 per check cycle
IG_POST_GAP_MINUTES = int(env("IG_POST_GAP_MINUTES", "120"))  # min gap between posts
IG_OPTIMAL_HOURS = [9, 12, 15, 17, 19, 21]  # best engagement hours

# --- Crypto feeds (international, English) ---
FEEDS_CRYPTO = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("The Block", "https://www.theblock.co/rss.xml"),
    ("Decrypt", "https://decrypt.co/feed"),
    ("Bitcoin Magazine", "https://bitcoinmagazine.com/.rss/full/"),
    ("CryptoSlate", "https://cryptoslate.com/feed/"),
    ("The Defiant", "https://thedefiant.io/api/feed"),
    ("Blockworks", "https://blockworks.co/feed"),
]

# --- Iranian stock market feeds (Persian) ---
FEEDS_BOURSE = [
    ("بورس‌نیوز", "https://www.boursenews.ir/fa/rss"),
    ("بورس‌پرس", "https://boursepress.ir/fa/rss"),
    ("اکوایران", "https://ecoiran.com/feeds/"),
    ("اقتصادنیوز", "https://www.eghtesadnews.com/feeds/"),
    ("دنیای اقتصاد", "https://donya-e-eqtesad.com/feeds/latest"),
]

# --- Iranian market feeds: housing, gold, car, silver (Persian) ---
FEEDS_MARKET = [
    ("tgju طلا", "https://www.tgju.org/feed"),
    ("ایرنا اقتصادی", "https://www.irna.ir/rss/tp/1018"),
    ("ایسنا", "https://www.isna.ir/rss"),
]

# --- Memecoin keywords for filtering from crypto feeds ---
MEME_COINS = {
    "doge", "dogecoin", "shib", "shiba", "pepe", "floki", "bonk", "wif",
    "dogwifhat", "brett", "mog", "popcat", "neiro", "turbo", "memecoin",
    "meme coin", "meme token", "dog coin", "frog coin",
}

# Legacy flat list (keep for backwards compat)
FEEDS = FEEDS_CRYPTO

for d in (DATA, OUT):
    d.mkdir(parents=True, exist_ok=True)
