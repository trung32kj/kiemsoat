"""Sensitive-title detection and full-screen capture."""
from __future__ import annotations

import io

# Fixed list: browser window titles only contain the page title, not the URL.
# Extend per machine via config.json -> sensitive_keywords.
SENSITIVE_KEYWORDS: tuple[str, ...] = (
    "pornhub",
    "xvideos",
    "xnxx",
    "xhamster",
    "redtube",
    "youporn",
    "onlyfans",
    "hentai",
    "porn",
    "xxx",
    "18+",
    "sex video",
    "clip sex",
    "phim sex",
    "phim heo",
    "khiêu dâm",
)


def is_sensitive(title: str, extra: list[str] | None = None) -> bool:
    if not title:
        return False
    haystack = title.lower()
    for word in tuple(SENSITIVE_KEYWORDS) + tuple(extra or ()):
        needle = str(word).strip().lower()
        if needle and needle in haystack:
            return True
    return False


def grab_jpeg(quality: int = 60) -> bytes:
    from PIL import ImageGrab

    img = ImageGrab.grab(all_screens=True)
    if img.mode != "RGB":
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()
