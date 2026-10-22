"""Sensitive-title detection and full-screen capture."""
from __future__ import annotations

import io
import re

# Browser window titles contain the page title, not the URL, so matching is
# title-based. Every keyword is matched on word boundaries so short entries
# never fire inside unrelated words (sex in "Essex", jav in "JavaScript").
# Extend per machine via config.json -> sensitive_keywords.
SENSITIVE_KEYWORDS: tuple[str, ...] = (
    # --- Adult: global brands (top-traffic, Semrush Sep 2026) ---
    "pornhub",
    "xvideos",
    "xvideo",
    "xnxx",
    "xhamster",
    "xhamsterlive",
    "redtube",
    "youporn",
    "youjizz",
    "spankbang",
    "eporner",
    "hqporner",
    "xgroovy",
    "pornpics",
    "beeg",
    "motherless",
    "4tube",
    "tube8",
    "porn",
    "porno",
    "onlyfans",
    "fansly",
    "manyvids",
    "brazzers",
    "bangbros",
    "naughty america",
    # --- Adult: Asian / hentai / manga ---
    "javhd",
    "javbus",
    "javlibrary",
    "javmix",
    "supjav",
    "njav",
    "missav",
    "hentai",
    "hanime",
    "nhentai",
    "e-hentai",
    "ehentai",
    "fakku",
    "dlsite",
    "f95zone",
    # --- Adult: cam sites ---
    "chaturbate",
    "stripchat",
    "bongacams",
    "cam4",
    "livejasmin",
    "jerkmate",
    # --- Adult: generic / Vietnamese ---
    "sex",
    "xxx",
    "18+",
    "nsfw",
    "phim sex",
    "sex việt",
    "sex viet",
    "clip sex",
    "phim heo",
    "khiêu dâm",
    "ấu dâm",
    "loạn luân",
    "mại dâm",
    "gái gọi",
    # --- Gambling: Vietnamese bookmakers (MIC blocklist / top VN searches) ---
    "789bet",
    "188bet",
    "w88",
    "fun88",
    "m88",
    "ae888",
    "shbet",
    "f8bet",
    "jun88",
    "new88",
    "sunwin",
    "hitclub",
    "rikvip",
    "go88",
    "b52",
    "cwin",
    "kubet",
    "fb88",
    "vn88",
    "sv388",
    "bong88",
    "12bet",
    "1xbet",
    "8xbet",
    # --- Gambling: pirate football streams that carry betting ads ---
    "xoilac",
    "xôi lạc",
    "thapcam",
    "cakhia",
    # --- Gambling: generic / Vietnamese ---
    "casino",
    "cá độ",
    "cá cược",
    "cờ bạc",
    "đánh bạc",
    "nhà cái",
    "kèo nhà cái",
    "lô đề",
    "đá gà",
    "tài xỉu",
    # --- Drugs ---
    "ma túy",
    "cần sa",
    "thuốc lắc",
    "bóng cười",
    "cocaine",
    "heroin",
    "methamphetamine",
    "ketamine",
    "mdma",
)

_patterns: dict[str, re.Pattern] = {}


def _compile(keyword: str) -> re.Pattern | None:
    needle = keyword.strip().lower()
    if not needle:
        return None
    pat = _patterns.get(needle)
    if pat is None:
        # ASCII word boundaries: "sex" must not fire inside "Essex",
        # "jav" must not fire inside "JavaScript".
        pat = re.compile(rf"(?<![0-9a-z]){re.escape(needle)}(?![0-9a-z])")
        _patterns[needle] = pat
    return pat


def is_sensitive(title: str, extra: list[str] | None = None) -> bool:
    if not title:
        return False
    haystack = title.lower()
    for word in tuple(SENSITIVE_KEYWORDS) + tuple(extra or ()):
        pat = _compile(str(word))
        if pat is not None and pat.search(haystack):
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
