"""Tiny JSON state: seen links, today's count, pending approvals."""
import json
import threading
from datetime import date

from .config import DATA

_STATE = DATA / "state.json"
_lock = threading.Lock()


def _read() -> dict:
    if _STATE.exists():
        try:
            return json.loads(_STATE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"seen": [], "days": {}, "pending": {}, "tg_offset": 0}


def _write(s: dict) -> None:
    s["seen"] = s["seen"][-3000:]
    tmp = _STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_STATE)


def get(key, default=None):
    with _lock:
        return _read().get(key, default)


def update(fn):
    """fn(state) mutates state in place; returns whatever fn returns."""
    with _lock:
        s = _read()
        r = fn(s)
        _write(s)
        return r


def today() -> str:
    return date.today().isoformat()


def made_today() -> int:
    return get("days", {}).get(today(), 0)


def add_made_today(n: int = 1) -> None:
    def f(s):
        s["days"][today()] = s["days"].get(today(), 0) + n
        # keep only last 30 days
        for k in sorted(s["days"])[:-30]:
            del s["days"][k]
    update(f)


def is_seen(link: str) -> bool:
    return link in get("seen", [])


def mark_seen(link: str) -> None:
    update(lambda s: s["seen"].append(link))
