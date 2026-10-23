"""Self-update from GitHub Releases: check, download, verify, replace, relaunch."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("TeleMonitor")

APP_EXE_NAME = "telemonitor.exe"
CHECK_INTERVAL = 6 * 3600
FIRST_CHECK_DELAY = 30
MAX_DOWNLOAD_BYTES = 80 * 1024 * 1024


class UpdateError(RuntimeError):
    """Raised when an update cannot be verified or applied."""


def parse_version(text: str) -> tuple[int, ...]:
    """'v1.2.3' -> (1, 2, 3). Missing or non-numeric parts count as 0."""
    nums = re.findall(r"\d+", str(text or ""))
    return tuple(int(n) for n in nums) or (0,)


def _api(repo: str) -> str:
    return f"https://api.github.com/repos/{repo}/releases/latest"


def _get_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "TeleMonitor"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"HTTP {exc.code} từ {url}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise UpdateError(str(exc)) from exc
    except ValueError as exc:
        raise UpdateError("JSON không hợp lệ từ GitHub") from exc


def check(repo: str, current: str, timeout: float = 15) -> dict | None:
    """Return {version, url, sha256_url} when a newer release exists, else None."""
    repo = str(repo or "").strip().strip("/")
    if not repo:
        return None
    data = _get_json(_api(repo), timeout)
    latest = str(data.get("tag_name") or "")
    if not latest or parse_version(latest) <= parse_version(current):
        return None
    assets = {a.get("name"): a.get("browser_download_url") for a in data.get("assets") or []}
    exe_url = assets.get(APP_EXE_NAME)
    sha_url = assets.get(APP_EXE_NAME + ".sha256")
    if not exe_url or not sha_url:
        log.error(
            "release %s thiếu asset %s hoặc %s.sha256 — bỏ qua",
            latest, APP_EXE_NAME, APP_EXE_NAME,
        )
        return None
    return {"version": latest, "url": exe_url, "sha256_url": sha_url}


def _fetch_sha(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "TeleMonitor"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(65536).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as exc:
        raise UpdateError(f"không tải được file SHA-256: {exc}") from exc
    # Accept "<hex>", "<hex>  telemonitor.exe" (sha256sum) and Windows
    # certutil output, which wraps the hash in header/footer lines.
    for token in raw.split():
        if re.fullmatch(r"[0-9a-fA-F]{64}", token):
            return token.lower()
    raise UpdateError("file SHA-256 không chứa hash hợp lệ")


def download(url: str, sha_url: str, dest: Path, timeout: float = 60) -> str:
    """Download, verify SHA-256, return the hex digest. Deletes dest on mismatch."""
    expected = _fetch_sha(sha_url, timeout)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    digest = hashlib.sha256()
    total = 0
    req = urllib.request.Request(url, headers={"User-Agent": "TeleMonitor"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, tmp.open("wb") as fh:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise UpdateError(f"file quá lớn (> {MAX_DOWNLOAD_BYTES} bytes)")
                digest.update(chunk)
                fh.write(chunk)
    except (urllib.error.URLError, OSError) as exc:
        tmp.unlink(missing_ok=True)
        raise UpdateError(f"tải thất bại: {exc}") from exc
    actual = digest.hexdigest()
    if actual != expected:
        tmp.unlink(missing_ok=True)
        raise UpdateError(f"SHA-256 lệch: mong {expected[:12]}… nhận {actual[:12]}…")
    tmp.replace(dest)
    log.info("downloaded %s (%d bytes, sha256 ok)", dest.name, total)
    return actual


def apply(new_exe: Path) -> None:
    """Replace the running exe and relaunch. Does not return."""
    if not getattr(sys, "frozen", False):
        raise UpdateError("apply() chỉ chạy được với bản đóng gói .exe")
    current = Path(sys.executable)
    old = current.with_suffix(current.suffix + ".old")
    old.unlink(missing_ok=True)
    os.replace(current, old)
    try:
        os.replace(new_exe, current)
    except OSError:
        os.replace(old, current)  # roll back so the machine is not left without an exe
        raise
    log.info("replaced exe, relaunching")
    subprocess.Popen([str(current)], close_fds=True)
    os._exit(0)


def cleanup_old() -> None:
    """Remove telemonitor.exe.old left by a previous self-replace."""
    if not getattr(sys, "frozen", False):
        return
    old = Path(sys.executable).with_suffix(Path(sys.executable).suffix + ".old")
    try:
        old.unlink(missing_ok=True)
    except OSError:
        log.warning("không xoá được %s", old)


def update_once(cfg: dict, current: str, update_dir: Path) -> str | None:
    """Check + download + apply. Returns the new version, or None if up to date."""
    info = check(cfg.get("update_repo", ""), current)
    if not info:
        return None
    dest = update_dir / (APP_EXE_NAME + ".new")
    download(info["url"], info["sha256_url"], dest)
    apply(dest)
    return info["version"]


def start_watcher(cfg: dict, current: str, update_dir: Path, on_error) -> None:
    """Background thread: first check after a delay, then every interval."""
    import threading

    def loop() -> None:
        time.sleep(FIRST_CHECK_DELAY)
        while True:
            try:
                update_once(cfg, current, update_dir)
            except UpdateError as exc:
                log.error("update failed: %s", exc)
                on_error(str(exc))
            except Exception as exc:  # noqa: BLE001 - the watcher must never die
                log.exception("update watcher error")
                on_error(str(exc))
            time.sleep(cfg.get("update_check_interval", CHECK_INTERVAL))

    threading.Thread(target=loop, daemon=True, name="update-watcher").start()
