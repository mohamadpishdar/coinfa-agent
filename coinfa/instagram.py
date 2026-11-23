"""Publish a photo post through the official Instagram API (Instagram Login).

The Graph API needs a public image URL, so the JPEG is first uploaded to
imgbb (free) with an expiry; Instagram copies it on publish.
"""
import base64
import logging
import time

import requests

from . import storage
from .config import IG_ACCESS_TOKEN, IG_API_VERSION, IG_USER_ID, IMGBB_API_KEY

log = logging.getLogger(__name__)
# Instagram-Login tokens (IGAA...) use graph.instagram.com; Facebook-Login
# tokens (EAA...) use graph.facebook.com with the linked IG business account.
_FB = IG_ACCESS_TOKEN.startswith("EAA")
BASE = f"https://graph.{'facebook' if _FB else 'instagram'}.com/{IG_API_VERSION}"


def _token() -> str:
    """Use the stored refreshed token if we have one; refresh every ~50 days."""
    if _FB:                       # Facebook tokens: use as given (no IG refresh)
        return IG_ACCESS_TOKEN
    t = storage.get("ig_token") or IG_ACCESS_TOKEN
    last = storage.get("ig_token_refreshed", 0)
    if time.time() - last > 50 * 86400:
        try:
            r = requests.get("https://graph.instagram.com/refresh_access_token",
                             params={"grant_type": "ig_refresh_token",
                                     "access_token": t}, timeout=30)
            if r.ok and r.json().get("access_token"):
                t = r.json()["access_token"]
                storage.update(lambda s: s.update(ig_token=t, ig_token_refreshed=time.time()))
                log.info("instagram token refreshed")
        except Exception as e:
            log.warning("token refresh failed: %s", e)
    return t


def host_image(path: str) -> str:
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    r = requests.post("https://api.imgbb.com/1/upload",
                      params={"key": IMGBB_API_KEY, "expiration": 86400},
                      data={"image": b64}, timeout=60)
    r.raise_for_status()
    return r.json()["data"]["url"]


def publish(image_path: str, caption: str) -> str:
    return publish_url(host_image(image_path), caption)


def publish_url(url: str, caption: str) -> str:
    token = _token()
    r = requests.post(f"{BASE}/{IG_USER_ID}/media",
                      data={"image_url": url, "caption": caption,
                            "access_token": token}, timeout=60)
    if not r.ok:
        raise RuntimeError(f"create container: {r.text[:300]}")
    cid = r.json()["id"]
    # wait until Instagram has fetched the image
    for _ in range(20):
        s = requests.get(f"{BASE}/{cid}", params={"fields": "status_code",
                                                  "access_token": token}, timeout=30).json()
        if s.get("status_code") == "FINISHED":
            break
        if s.get("status_code") == "ERROR":
            raise RuntimeError(f"container error: {s}")
        time.sleep(3)
    r = requests.post(f"{BASE}/{IG_USER_ID}/media_publish",
                      data={"creation_id": cid, "access_token": token}, timeout=60)
    if not r.ok:
        raise RuntimeError(f"publish: {r.text[:300]}")
    media_id = r.json()["id"]
    try:
        link = requests.get(f"{BASE}/{media_id}", params={"fields": "permalink",
                            "access_token": token}, timeout=30).json().get("permalink", "")
    except Exception:
        link = ""
    return link or media_id
