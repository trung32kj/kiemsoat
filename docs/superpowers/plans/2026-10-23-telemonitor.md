# TeleMonitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ứng dụng Python chạy nền trên Windows, tự khởi động cùng máy, gửi thông báo Telegram khi máy bật và khi người dùng chuyển ứng dụng/tab, kèm ảnh chụp màn hình khi gặp trang nhạy cảm.

**Architecture:** Một process, một vòng poll đọc cửa sổ đang active bằng ctypes, một worker thread gửi tin qua Telegram Bot API bằng `urllib`. Sáu module độc lập (`config`, `wininfo`, `tracker`, `capture`, `telegram`, `main`), chỉ `main` biết tất cả. Đóng gói bằng PyInstaller `--onefile --noconsole`, tự khởi động qua Registry `HKCU\...\Run`.

**Tech Stack:** Python 3.11, stdlib (`ctypes`, `urllib.request`, `queue`, `winreg`, `logging`), Pillow (chỉ để chụp màn hình), PyInstaller.

**Spec:** `docs/superpowers/specs/2026-10-23-telemonitor-design.md`

## Global Constraints

- Không có GUI, không tray icon, không cửa sổ console khi chạy.
- Chỉ một dependency ngoài stdlib: `Pillow`.
- Không dùng test framework. Mọi test là assert thuần, chạy bằng `python tests/test_core.py`.
- Chỉ chạy trên Windows (ctypes gọi `user32`/`kernel32`/`winreg`).
- Mọi tin nhắn gửi Telegram có tiền tố `[<device_name>]` (trừ tin khởi động).
- Parse mode `HTML`; mọi text từ hệ thống phải escape qua `telegram.escape()`.
- Ảnh nhạy cảm: tối đa 1 ảnh / `sensitive_cooldown` giây / máy.
- Không đọc URL trình duyệt, không gửi keystroke, không điều khiển máy từ xa ngoài các lệnh `/shot`, `/live`, `/stop`, `/status`.
- Không mở port mạng. Mọi liên lạc đi qua HTTPS tới `api.telegram.org`.
- Mọi update Telegram có `chat.id` khác `chat_id` trong config bị bỏ qua im lặng (không trả lời).

## File Structure

| File | Trách nhiệm |
|---|---|
| `src/config.py` | Nạp/tạo `config.json`, điền default, chuẩn hoá kiểu |
| `src/wininfo.py` | Trả `(exe_name, window_title)` của cửa sổ foreground |
| `src/tracker.py` | Quyết định một cặp `(app, title)` có phải là "mới" không |
| `src/capture.py` | Danh sách từ khóa nhạy cảm + chụp màn hình ra JPEG bytes |
| `src/telegram.py` | `send_message`, `send_photo`, `escape`, dựng multipart, `get_updates` |
| `src/commands.py` | Poll lệnh, xác thực chat_id, xử lý `/shot`, `/live`, `/stop`, `/status` |
| `src/main.py` | Logging, mutex 1 instance, queue gửi, vòng poll, CLI |
| `tests/test_core.py` | Assert thuần cho config/tracker/telegram/capture |
| `requirements.txt` | `Pillow` |
| `config.example.json` | Mẫu cấu hình |
| `build.bat` | PyInstaller `--onefile --noconsole` |
| `install.bat` / `uninstall.bat` | Copy vào `%LOCALAPPDATA%` + bật/tắt autostart |
| `README.md` | Hướng dẫn cài đặt, build, nhiều máy |

---

### Task 1: Scaffold + config module

**Files:**
- Create: `src/config.py`
- Create: `tests/test_core.py`
- Create: `requirements.txt`

**Interfaces:**
- Produces: `config.DEFAULTS: dict`, `config.config_path() -> Path`, `config.load(path: Path | None = None) -> dict`

- [ ] **Step 1: Tạo `requirements.txt`**

```
Pillow>=10.0
```

- [ ] **Step 2: Viết test thất bại cho config**

Tạo `tests/test_core.py`:

```python
"""Assert-based checks. Run: python tests/test_core.py"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config  # noqa: E402


def test_config_defaults_fill_missing_keys():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        cfg = config.load(path)
        assert path.exists(), "config.json phải được tạo khi thiếu"
        for key in config.DEFAULTS:
            assert key in cfg, f"thiếu key {key}"
        assert cfg["device_name"], "device_name phải fallback về hostname"
        assert cfg["poll_interval"] == 2.0


def test_config_partial_file_keeps_defaults():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        path.write_text(json.dumps({"bot_token": "abc", "poll_interval": "0.1"}),
                        encoding="utf-8")
        cfg = config.load(path)
        assert cfg["bot_token"] == "abc"
        assert cfg["poll_interval"] == 0.5, "poll_interval phải bị kẹp tối thiểu 0.5"
        assert cfg["track_activity"] is True


def test_config_broken_file_falls_back():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        path.write_text("{not json", encoding="utf-8")
        cfg = config.load(path)
        assert cfg["device_name"]
        assert cfg["bot_token"] == ""


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("all passed")
```

- [ ] **Step 3: Chạy test để thấy nó fail**

Run: `python tests/test_core.py`
Expected: `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 4: Viết `src/config.py`**

```python
"""Load/create config.json next to the executable."""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

DEFAULTS = {
    "bot_token": "",
    "chat_id": "",
    "device_name": "",
    "poll_interval": 2.0,
    "send_startup_message": True,
    "track_activity": True,
    "sensitive_keywords": [],
    "sensitive_cooldown": 300,
    "enable_commands": True,
    "command_poll_timeout": 25,
    "ignore_apps": [
        "LockApp.exe",
        "SearchHost.exe",
        "ShellExperienceHost.exe",
        "StartMenuExperienceHost.exe",
        "TextInputHost.exe",
    ],
}


def config_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "config.json"
    return Path(__file__).resolve().parent.parent / "config.json"


def load(path: Path | None = None) -> dict:
    path = Path(path) if path else config_path()
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy
    if not path.exists():
        try:
            path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        return _normalize(cfg)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _normalize(cfg)
    if isinstance(data, dict):
        cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
    return _normalize(cfg)


def _normalize(cfg: dict) -> dict:
    cfg["bot_token"] = str(cfg.get("bot_token") or "").strip()
    cfg["chat_id"] = str(cfg.get("chat_id") or "").strip()
    name = str(cfg.get("device_name") or "").strip()
    cfg["device_name"] = name or socket.gethostname()
    try:
        cfg["poll_interval"] = max(0.5, float(cfg.get("poll_interval") or 2.0))
    except (TypeError, ValueError):
        cfg["poll_interval"] = 2.0
    try:
        cfg["sensitive_cooldown"] = max(30, int(cfg.get("sensitive_cooldown") or 300))
    except (TypeError, ValueError):
        cfg["sensitive_cooldown"] = 300
    cfg["send_startup_message"] = bool(cfg.get("send_startup_message", True))
    cfg["track_activity"] = bool(cfg.get("track_activity", True))
    cfg["enable_commands"] = bool(cfg.get("enable_commands", True))
    try:
        cfg["command_poll_timeout"] = max(5, min(50, int(cfg.get("command_poll_timeout") or 25)))
    except (TypeError, ValueError):
        cfg["command_poll_timeout"] = 25
    if not isinstance(cfg.get("sensitive_keywords"), list):
        cfg["sensitive_keywords"] = []
    if not isinstance(cfg.get("ignore_apps"), list):
        cfg["ignore_apps"] = list(DEFAULTS["ignore_apps"])
    return cfg
```

- [ ] **Step 5: Chạy test**

Run: `python tests/test_core.py`
Expected: 3 dòng `ok test_...` rồi `all passed`

- [ ] **Step 6: Commit**

```bash
git add src/config.py tests/test_core.py requirements.txt
git commit -m "feat: config loader with defaults and normalization"
```

---

### Task 2: Change tracker (chống lặp)

**Files:**
- Create: `src/tracker.py`
- Modify: `tests/test_core.py`

**Interfaces:**
- Consumes: không
- Produces: `tracker.ChangeTracker()` với `changed(app: str, title: str) -> bool`

- [ ] **Step 1: Thêm test thất bại**

Thêm vào `tests/test_core.py` (trước khối `if __name__`):

```python
def test_tracker_reports_only_changes():
    from tracker import ChangeTracker
    t = ChangeTracker()
    assert t.changed("chrome.exe", "Tin tức") is True, "lần đầu phải gửi"
    assert t.changed("chrome.exe", "Tin tức") is False, "trùng thì không gửi"
    assert t.changed("chrome.exe", "Tin tức - Google Chrome") is True, "đổi title phải gửi"
    assert t.changed("notepad.exe", "x.txt") is True, "đổi app phải gửi"
    assert t.changed("notepad.exe", "") is False, "title rỗng bỏ qua"
    assert t.changed("", "x") is False, "app rỗng bỏ qua"


def test_tracker_is_case_insensitive():
    from tracker import ChangeTracker
    t = ChangeTracker()
    assert t.changed("Chrome.exe", "ABC") is True
    assert t.changed("chrome.exe", "abc") is False
```

- [ ] **Step 2: Chạy test**

Run: `python tests/test_core.py`
Expected: `ModuleNotFoundError: No module named 'tracker'`

- [ ] **Step 3: Viết `src/tracker.py`**

```python
"""Deduplicate active-window changes."""
from __future__ import annotations


class ChangeTracker:
    """Reports True only when (app, title) differs from the last accepted pair."""

    def __init__(self) -> None:
        self._last: tuple[str, str] | None = None

    def changed(self, app: str, title: str) -> bool:
        app = (app or "").strip()
        title = (title or "").strip()
        if not app:
            return False
        key = (app.lower(), title.lower())
        if key == self._last:
            return False
        self._last = key
        return True
```

- [ ] **Step 4: Chạy test**

Run: `python tests/test_core.py`
Expected: 5 dòng `ok`, kết thúc `all passed`

- [ ] **Step 5: Commit**

```bash
git add src/tracker.py tests/test_core.py
git commit -m "feat: change tracker dedupes active window events"
```

---

### Task 3: Telegram client

**Files:**
- Create: `src/telegram.py`
- Modify: `tests/test_core.py`

**Interfaces:**
- Produces:
  - `telegram.TelegramError(RuntimeError)`
  - `telegram.escape(text: str) -> str`
  - `telegram._multipart(fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]) -> tuple[bytes, str]`
  - `telegram.send_message(token: str, chat_id: str, text: str, timeout: float = 15) -> None`
  - `telegram.send_photo(token: str, chat_id: str, jpeg: bytes, caption: str = "", timeout: float = 30) -> None`
  - `telegram.get_updates(token: str, offset: int, timeout: int = 25) -> list[dict]`

- [ ] **Step 1: Thêm test thất bại**

```python
def test_telegram_escape_html():
    from telegram import escape
    assert escape("a<b>&c") == "a&lt;b&gt;&amp;c"


def test_telegram_multipart_body():
    from telegram import _multipart
    body, ctype = _multipart({"chat_id": "123", "text": "hi"}, {})
    assert ctype.startswith("multipart/form-data; boundary=")
    boundary = ctype.split("boundary=", 1)[1]
    assert f"--{boundary}".encode() in body
    assert body.endswith(f"--{boundary}--\r\n".encode())
    assert b'name="chat_id"\r\n\r\n123\r\n' in body


def test_telegram_multipart_photo():
    from telegram import _multipart
    body, ctype = _multipart({"caption": "x"}, {"photo": ("a.jpg", b"\xff\xd8junk", "image/jpeg")})
    assert b'filename="a.jpg"' in body
    assert b"Content-Type: image/jpeg" in body
    assert b"\xff\xd8junk" in body
```

- [ ] **Step 2: Chạy test**

Run: `python tests/test_core.py`
Expected: `ModuleNotFoundError: No module named 'telegram'`

- [ ] **Step 3: Viết `src/telegram.py`**

```python
"""Minimal Telegram Bot API client (stdlib only)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid


class TelegramError(RuntimeError):
    """Raised when the Bot API rejects a request or the network fails."""


def escape(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _api(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def _multipart(
    fields: dict[str, str],
    files: dict[str, tuple[str, bytes, str]],
) -> tuple[bytes, str]:
    boundary = "----TeleMonitor" + uuid.uuid4().hex
    out = bytearray()
    for name, value in fields.items():
        out += f"--{boundary}\r\n".encode()
        out += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        out += str(value).encode("utf-8") + b"\r\n"
    for name, (filename, data, mime) in files.items():
        out += f"--{boundary}\r\n".encode()
        out += (
            f'Content-Disposition: form-data; name="{name}"; '
            f'filename="{filename}"\r\n'
        ).encode()
        out += f"Content-Type: {mime}\r\n\r\n".encode()
        out += data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def _post(url: str, data: bytes, content_type: str, timeout: float) -> dict:
    req = urllib.request.Request(url, data=data, headers={"Content-Type": content_type})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise TelegramError(f"HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise TelegramError(str(exc)) from exc
    except ValueError as exc:
        raise TelegramError("invalid JSON from Telegram") from exc
    if not payload.get("ok"):
        raise TelegramError(str(payload.get("description", "unknown error")))
    return payload


def send_message(token: str, chat_id: str, text: str, timeout: float = 15) -> None:
    body, ctype = _multipart(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        },
        {},
    )
    _post(_api(token, "sendMessage"), body, ctype, timeout)


def send_photo(
    token: str,
    chat_id: str,
    jpeg: bytes,
    caption: str = "",
    timeout: float = 30,
) -> None:
    body, ctype = _multipart(
        {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
        {"photo": ("shot.jpg", jpeg, "image/jpeg")},
    )
    _post(_api(token, "sendPhoto"), body, ctype, timeout)


def get_updates(token: str, offset: int, timeout: int = 25) -> list[dict]:
    url = (
        f"{_api(token, 'getUpdates')}?offset={int(offset)}"
        f"&timeout={int(timeout)}&allowed_updates=%5B%22message%22%5D"
    )
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout + 15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        if exc.code == 409:
            raise TelegramError(
                "409 Conflict: bot đang có webhook. Chạy "
                "https://api.telegram.org/bot<TOKEN>/deleteWebhook trước."
            ) from exc
        raise TelegramError(f"HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise TelegramError(str(exc)) from exc
    except ValueError as exc:
        raise TelegramError("invalid JSON from Telegram") from exc
    if not payload.get("ok"):
        raise TelegramError(str(payload.get("description", "unknown error")))
    return payload.get("result") or []
```

- [ ] **Step 4: Chạy test**

Run: `python tests/test_core.py`
Expected: 8 dòng `ok`, kết thúc `all passed`

- [ ] **Step 5: Commit**

```bash
git add src/telegram.py tests/test_core.py
git commit -m "feat: telegram client with hand-rolled multipart"
```

---

### Task 4: Sensitive-page detection + screenshot

**Files:**
- Create: `src/capture.py`
- Modify: `tests/test_core.py`

**Interfaces:**
- Produces:
  - `capture.SENSITIVE_KEYWORDS: tuple[str, ...]`
  - `capture.is_sensitive(title: str, extra: list[str] | None = None) -> bool`
  - `capture.grab_jpeg(quality: int = 60) -> bytes`

- [ ] **Step 1: Thêm test thất bại**

```python
def test_capture_is_sensitive():
    from capture import is_sensitive
    assert is_sensitive("Pornhub - Google Chrome") is True
    assert is_sensitive("Tin tức hôm nay") is False
    assert is_sensitive("") is False
    assert is_sensitive("XVideos", ["xvideos"]) is True
    assert is_sensitive("my custom site", ["CUSTOM"]) is True, "phải không phân biệt hoa thường"
    assert is_sensitive("nothing here", [""]) is False, "từ khóa rỗng bỏ qua"
```

- [ ] **Step 2: Chạy test**

Run: `python tests/test_core.py`
Expected: `ModuleNotFoundError: No module named 'capture'`

- [ ] **Step 3: Viết `src/capture.py`**

```python
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
```

- [ ] **Step 4: Chạy test**

Run: `python tests/test_core.py`
Expected: 9 dòng `ok`, kết thúc `all passed`

- [ ] **Step 5: Kiểm tra chụp màn hình thật (thủ công)**

Run: `python -c "import sys; sys.path.insert(0,'src'); import capture; d=capture.grab_jpeg(); print(len(d)); open('shot.jpg','wb').write(d)"`
Expected: in ra số byte > 10000, mở `shot.jpg` thấy đúng màn hình hiện tại. Xoá `shot.jpg` sau khi xem.

- [ ] **Step 6: Commit**

```bash
git add src/capture.py tests/test_core.py
git commit -m "feat: sensitive keyword detection and screen capture"
```

---

### Task 5: Active window reader

**Files:**
- Create: `src/wininfo.py`

**Interfaces:**
- Produces: `wininfo.active() -> tuple[str, str]` — `(exe_name, title)`, `("", "")` khi lỗi

- [ ] **Step 1: Viết `src/wininfo.py`**

Không có unit test được (cần cửa sổ thật); kiểm tra thủ công ở Step 2.

```python
"""Read the foreground window via Win32 ctypes."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_user32.GetWindowTextLengthW.restype = ctypes.c_int
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetWindowTextW.restype = ctypes.c_int
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
_kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL


def _exe_name(hwnd: int) -> str:
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1]
        return ""
    finally:
        _kernel32.CloseHandle(handle)


def _title(hwnd: int) -> str:
    length = _user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def active() -> tuple[str, str]:
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return ("", "")
    try:
        return (_exe_name(hwnd), _title(hwnd))
    except OSError:
        return ("", "")
```

- [ ] **Step 2: Kiểm tra thủ công**

Run: `python -c "import sys; sys.path.insert(0,'src'); import wininfo; print(wininfo.active())"`
Expected: in ra tuple có exe_name thật của cửa sổ terminal (vd `('WindowsTerminal.exe', '...')`). Chuyển sang Chrome rồi chạy lại thấy `chrome.exe`.

- [ ] **Step 3: Commit**

```bash
git add src/wininfo.py
git commit -m "feat: read foreground window app and title via ctypes"
```

---

### Task 6: Main loop, queue, CLI, logging

**Files:**
- Create: `src/main.py`
- Create: `config.example.json`

**Interfaces:**
- Consumes: `config.load()`, `config.config_path()`, `wininfo.active()`, `tracker.ChangeTracker`, `capture.is_sensitive`, `capture.grab_jpeg`, `telegram.send_message`, `telegram.send_photo`, `telegram.escape`, `telegram.TelegramError`
- Produces: `main.main(argv: list[str] | None = None) -> int`

- [ ] **Step 1: Viết `config.example.json`**

```json
{
  "bot_token": "123456:ABC-DEF_your_bot_token",
  "chat_id": "123456789",
  "device_name": "PC-Van-Phong",
  "poll_interval": 2.0,
  "send_startup_message": true,
  "track_activity": true,
  "sensitive_keywords": [],
  "sensitive_cooldown": 300,
  "enable_commands": true,
  "command_poll_timeout": 25,
  "ignore_apps": [
    "LockApp.exe",
    "SearchHost.exe",
    "ShellExperienceHost.exe",
    "StartMenuExperienceHost.exe",
    "TextInputHost.exe"
  ]
}
```

- [ ] **Step 2: Viết `src/main.py`**

```python
"""TeleMonitor entry point: hidden Windows agent reporting activity to Telegram."""
from __future__ import annotations

import ctypes
import logging
import logging.handlers
import os
import queue
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import capture
import commands
import config
import telegram
import tracker
import wininfo

APP_NAME = "TeleMonitor"
MUTEX_NAME = "Local\\TeleMonitorMutex"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
LOG_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_NAME
ERROR_ALREADY_EXISTS = 183

log = logging.getLogger(APP_NAME)
_mutex_handle = None


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if sys.stderr is not None:
        root.addHandler(logging.StreamHandler())


def say(msg: str, error: bool = False) -> None:
    """Print for dev builds, MessageBox for the frozen exe (no console)."""
    log.info("%s", msg)
    if sys.stderr is not None:
        print(msg, file=sys.stderr if error else sys.stdout)
    if getattr(sys, "frozen", False):
        ctypes.windll.user32.MessageBoxW(None, msg, APP_NAME, 0x10 if error else 0x40)


def acquire_single_instance() -> bool:
    global _mutex_handle
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    _mutex_handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


def autostart_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    launcher = pythonw if pythonw.exists() else Path(sys.executable)
    return f'"{launcher}" "{Path(__file__).resolve()}"'


def install_autostart() -> None:
    import winreg

    cmd = autostart_command()
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
    say(f"Đã bật tự khởi động:\n{cmd}")


def uninstall_autostart() -> None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, APP_NAME)
        say("Đã tắt tự khởi động.")
    except FileNotFoundError:
        say("Chưa có mục tự khởi động nào.")


class Sender:
    """Background thread that drains a bounded queue and posts to Telegram."""

    def __init__(self, cfg: dict) -> None:
        self.token = cfg["bot_token"]
        self.chat_id = cfg["chat_id"]
        self.q: queue.Queue = queue.Queue(maxsize=100)
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def put(self, kind: str, payload) -> None:
        try:
            self.q.put_nowait((kind, payload))
        except queue.Full:
            log.warning("send queue full, dropping oldest")
            try:
                self.q.get_nowait()
                self.q.put_nowait((kind, payload))
            except (queue.Empty, queue.Full):
                pass

    def _run(self) -> None:
        if not self.token or not self.chat_id:
            return
        while True:
            kind, payload = self.q.get()
            for attempt in range(3):
                try:
                    if kind == "text":
                        telegram.send_message(self.token, self.chat_id, payload)
                    else:
                        telegram.send_photo(
                            self.token, self.chat_id, payload[0], payload[1]
                        )
                    break
                except telegram.TelegramError as exc:
                    log.warning("send failed (try %d): %s", attempt + 1, exc)
                    time.sleep(5 * (attempt + 1))


def poll_forever(cfg: dict, sender: Sender) -> None:
    changes = tracker.ChangeTracker()
    ignore = {str(a).lower() for a in cfg["ignore_apps"]}
    device = telegram.escape(cfg["device_name"])
    last_shot = 0.0

    while True:
        try:
            app, title = wininfo.active()
            skip = not app or app.lower() in ignore

            if not skip and cfg["track_activity"] and changes.changed(app, title):
                sender.put(
                    "text",
                    f"[{device}] <b>{telegram.escape(app)}</b>\n"
                    f"— {telegram.escape(title) or '(không có tiêu đề)'}",
                )

            if not skip and capture.is_sensitive(title, cfg["sensitive_keywords"]):
                now = time.monotonic()
                if now - last_shot >= cfg["sensitive_cooldown"]:
                    last_shot = now
                    try:
                        jpeg = capture.grab_jpeg()
                        caption = f"⚠️ [{device}] {telegram.escape(title)[:200]}"
                        sender.put("photo", (jpeg, caption))
                    except Exception as exc:  # noqa: BLE001 - capture must never kill the loop
                        log.warning("screenshot failed: %s", exc)
        except Exception:  # noqa: BLE001 - keep the agent alive
            log.exception("poll error")
        time.sleep(cfg["poll_interval"])


def run() -> None:
    cfg = config.load()
    if not cfg["bot_token"] or not cfg["chat_id"]:
        log.error("Thiếu bot_token/chat_id trong %s", config.config_path())
        return
    log.info("start device=%s interval=%s", cfg["device_name"], cfg["poll_interval"])
    sender = Sender(cfg)
    sender.start()
    if cfg.get("enable_commands", True):
        live = commands.LiveSession()
        commands.CommandListener(cfg, sender, live).start()
        log.info("command listener enabled (/shot, /live, /stop, /status)")
    if cfg["send_startup_message"]:
        stamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        sender.put(
            "text",
            f"🟢 <b>Máy tính đã bật</b>\n"
            f"🖥️ <b>{telegram.escape(cfg['device_name'])}</b>\n"
            f"🕒 {stamp}",
        )
    poll_forever(cfg, sender)


def test_send() -> int:
    cfg = config.load()
    if not cfg["bot_token"] or not cfg["chat_id"]:
        say(f"Thiếu bot_token/chat_id trong {config.config_path()}", error=True)
        return 1
    try:
        telegram.send_message(
            cfg["bot_token"],
            cfg["chat_id"],
            f"✅ Test từ <b>{telegram.escape(cfg['device_name'])}</b>",
        )
    except telegram.TelegramError as exc:
        say(f"Gửi thất bại: {exc}", error=True)
        return 1
    say("Đã gửi tin test. Kiểm tra Telegram.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    setup_logging()
    if "--install" in args:
        install_autostart()
        return 0
    if "--uninstall" in args:
        uninstall_autostart()
        return 0
    if "--test" in args:
        return test_send()
    if not acquire_single_instance():
        log.info("another instance is already running, exiting")
        return 0
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Kiểm tra import và CLI không crash**

Run: `python src/main.py --help; python -c "import sys; sys.path.insert(0,'src'); import main; print(main.autostart_command())"`
Expected: `--help` không được xử lý đặc biệt nên sẽ chạy app (cần token) — nếu không có token thì log lỗi và thoát 0. Dòng thứ hai in ra đường dẫn `pythonw.exe ... src\main.py`.

- [ ] **Step 4: Commit**

```bash
git add src/main.py config.example.json
git commit -m "feat: main loop, sender queue, autostart and CLI"
```

---

### Task 6b: Lệnh điều khiển hai chiều (`/shot`, `/live`, `/stop`, `/status`)

**Files:**
- Create: `src/commands.py`
- Modify: `tests/test_core.py`

**Interfaces:**
- Consumes: `telegram.get_updates`, `telegram.send_message`, `telegram.escape`
- Produces:
  - `commands.parse(text: str, device_name: str) -> tuple[str, int, str] | None` — trả `(action, arg, target_device)`; `action` ∈ `{"shot", "live", "stop", "status"}`, `target_device` rỗng nghĩa là mọi máy; `None` = không phải lệnh / không khớp máy này.
  - `commands.LiveSession` — `start(seconds)`, `stop()`, `remaining() -> int`
  - `commands.CommandListener(cfg, sender, live)` với `start()`

- [ ] **Step 1: Thêm test thất bại cho parser**

Thêm vào `tests/test_core.py`:

```python
def test_command_parse_shot():
    from commands import parse
    assert parse("/shot", "PC1") == ("shot", 0, "")
    assert parse("/shot", "PC1") is not None


def test_command_parse_target_device():
    from commands import parse
    assert parse("/shot PC1", "PC1") == ("shot", 0, "PC1")
    assert parse("/shot PC2", "PC1") is None, "lệnh cho máy khác thì bỏ qua"
    assert parse("/shot pc1", "PC1") == ("shot", 0, "pc1"), "so khớp không phân biệt hoa thường"


def test_command_parse_live():
    from commands import parse
    assert parse("/live", "PC1") == ("live", 30, ""), "mặc định 30 giây"
    assert parse("/live 60", "PC1") == ("live", 60, "")
    assert parse("/live 9999", "PC1") == ("live", 300, ""), "kẹp tối đa 300"
    assert parse("/live abc", "PC1") == ("live", 30, ""), "số sai thì về mặc định"
    assert parse("/live 45 PC1", "PC1") == ("live", 45, "PC1")


def test_command_parse_ignores_others():
    from commands import parse
    assert parse("hello", "PC1") is None
    assert parse("", "PC1") is None
    assert parse("/unknown", "PC1") is None
    assert parse("/stop@MyBot", "PC1") == ("stop", 0, ""), "bỏ @botname"
    assert parse("/STATUS", "PC1") == ("status", 0, "")
```

- [ ] **Step 2: Chạy test**

Run: `python tests/test_core.py`
Expected: `ModuleNotFoundError: No module named 'commands'`

- [ ] **Step 3: Viết `src/commands.py`**

```python
"""Telegram command listener: remote screen viewing."""
from __future__ import annotations

import logging
import threading
import time

import capture
import telegram

log = logging.getLogger("TeleMonitor")

DEFAULT_LIVE_SECONDS = 30
MAX_LIVE_SECONDS = 300
LIVE_FRAME_INTERVAL = 2.0


def parse(text: str, device_name: str) -> tuple[str, int, str] | None:
    """Return (action, arg, target_device) or None when not for this machine."""
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return None
    parts = raw.split()
    cmd = parts[0][1:].split("@", 1)[0].lower()
    rest = parts[1:]
    if cmd not in ("shot", "live", "stop", "status"):
        return None

    seconds = 0
    if cmd == "live":
        seconds = DEFAULT_LIVE_SECONDS
        if rest and rest[0].lstrip("-").isdigit():
            seconds = max(2, min(MAX_LIVE_SECONDS, int(rest[0])))
            rest = rest[1:]

    target = rest[0] if rest else ""
    if target and target.lower() != device_name.lower():
        return None
    return (cmd, seconds, target)


class LiveSession:
    """One /live run at a time; new /live replaces the old."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ends_at = 0.0
        self._thread: threading.Thread | None = None

    def start(self, seconds: int, on_frame) -> None:
        with self._lock:
            self._ends_at = time.monotonic() + seconds
            if self._thread and self._thread.is_alive():
                return  # existing loop picks up the new deadline
            self._thread = threading.Thread(
                target=self._loop, args=(on_frame,), daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._ends_at = 0.0

    def remaining(self) -> int:
        with self._lock:
            return max(0, int(self._ends_at - time.monotonic()))

    def _loop(self, on_frame) -> None:
        while True:
            if self.remaining() <= 0:
                with self._lock:
                    if self.remaining() <= 0:
                        self._thread = None
                        return
            try:
                on_frame()
            except Exception as exc:  # noqa: BLE001 - never kill the session thread
                log.warning("live frame failed: %s", exc)
            time.sleep(LIVE_FRAME_INTERVAL)


class CommandListener:
    """Long-polls getUpdates and executes commands from the configured chat only."""

    def __init__(self, cfg: dict, sender, live: LiveSession) -> None:
        self.token = cfg["bot_token"]
        self.chat_id = str(cfg["chat_id"])
        self.device = cfg["device_name"]
        self.sender = sender
        self.live = live
        self.offset = 0
        self.started_at = time.monotonic()

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        backoff = 5
        while True:
            try:
                updates = telegram.get_updates(self.token, self.offset)
                backoff = 5
                for upd in updates:
                    self.offset = max(self.offset, int(upd.get("update_id", 0)) + 1)
                    self._handle(upd)
            except telegram.TelegramError as exc:
                log.warning("getUpdates failed: %s", exc)
                time.sleep(backoff)
                backoff = min(60, backoff * 2)

    def _handle(self, upd: dict) -> None:
        msg = upd.get("message") or {}
        chat = msg.get("chat") or {}
        if str(chat.get("id", "")) != self.chat_id:
            return  # silent: never reveal the agent to strangers
        parsed = parse(msg.get("text", ""), self.device)
        if parsed is None:
            return
        action, seconds, _target = parsed
        if action == "shot":
            self._shoot()
        elif action == "live":
            self.live.start(seconds, self._shoot)
            self.sender.put(
                "text",
                f"🎥 [{telegram.escape(self.device)}] Bắt đầu /live {seconds}s",
            )
        elif action == "stop":
            self.live.stop()
            self.sender.put("text", f"⏹ [{telegram.escape(self.device)}] Đã dừng /live")
        elif action == "status":
            up = int(time.monotonic() - self.started_at)
            self.sender.put(
                "text",
                f"ℹ️ [{telegram.escape(self.device)}] up {up // 3600}h"
                f"{(up % 3600) // 60}m, /live còn {self.live.remaining()}s",
            )

    def _shoot(self) -> None:
        jpeg = capture.grab_jpeg()
        caption = f"📷 [{telegram.escape(self.device)}]"
        self.sender.put("photo", (jpeg, caption))
```

- [ ] **Step 4: Chạy test**

Run: `python tests/test_core.py`
Expected: 13 dòng `ok`, kết thúc `all passed`

- [ ] **Step 5: Commit**

```bash
git add src/commands.py tests/test_core.py
git commit -m "feat: telegram command listener for /shot and /live"
```

---

### Task 7: Đóng gói + script cài đặt

**Files:**
- Create: `build.bat`
- Create: `install.bat`
- Create: `uninstall.bat`
- Create: `README.md`

**Interfaces:**
- Produces: `dist\telemonitor.exe`, thư mục `%LOCALAPPDATA%\TeleMonitor\`

- [ ] **Step 1: Viết `build.bat`**

```bat
@echo off
setlocal
cd /d "%~dp0"

python -m pip install --upgrade pyinstaller Pillow || goto :err

python -m PyInstaller ^
  --onefile ^
  --noconsole ^
  --name telemonitor ^
  --paths src ^
  --hidden-import PIL._tkinter_finder ^
  --clean ^
  src\main.py || goto :err

echo.
echo Xong. File: dist\telemonitor.exe
goto :eof

:err
echo.
echo BUILD THAT BAI.
exit /b 1
```

- [ ] **Step 2: Viết `install.bat`**

```bat
@echo off
setlocal
set "SRC=%~dp0"
set "DST=%LOCALAPPDATA%\TeleMonitor"

if not exist "%SRC%dist\telemonitor.exe" (
  echo Chua co dist\telemonitor.exe. Chay build.bat truoc.
  pause
  exit /b 1
)

if not exist "%DST%" mkdir "%DST%"
copy /y "%SRC%dist\telemonitor.exe" "%DST%\telemonitor.exe" >nul

if not exist "%DST%\config.json" (
  if exist "%SRC%config.json" (
    copy /y "%SRC%config.json" "%DST%\config.json" >nul
  ) else (
    copy /y "%SRC%config.example.json" "%DST%\config.json" >nul
    echo Da tao %DST%\config.json - hay dien bot_token, chat_id, device_name.
  )
)

start "" "%DST%\telemonitor.exe" --install
timeout /t 2 >nul
start "" "%DST%\telemonitor.exe"
echo.
echo Da cai vao %DST% va bat tu khoi dong.
pause
```

- [ ] **Step 3: Viết `uninstall.bat`**

```bat
@echo off
setlocal
set "DST=%LOCALAPPDATA%\TeleMonitor"

taskkill /f /im telemonitor.exe >nul 2>&1
if exist "%DST%\telemonitor.exe" start "" "%DST%\telemonitor.exe" --uninstall
timeout /t 2 >nul
if exist "%DST%" rmdir /s /q "%DST%"
echo Da go cai dat.
pause
```

- [ ] **Step 4: Viết `README.md`**

```markdown
# TeleMonitor

Agent chạy nền trên Windows, báo hoạt động về Telegram.

## Tính năng

- Tự khởi động cùng Windows, gửi tin "Máy tính đã bật" kèm tên máy và giờ.
- Theo dõi ứng dụng/cửa sổ đang active mỗi 2 giây, gửi Telegram khi đổi.
  Chrome/Edge đưa tên tab vào window title nên thấy được cả trang đang xem.
- Phát hiện trang nhạy cảm theo từ khóa, chụp toàn màn hình, gửi ảnh
  (tối đa 1 ảnh / 5 phút / máy).
- Xem màn hình máy từ xa bằng lệnh Telegram: `/shot`, `/live N`, `/stop`, `/status`.

## Lệnh điều khiển

Nhắn trực tiếp cho bot (chỉ chat_id trong config mới có tác dụng):

| Lệnh | Việc |
|---|---|
| `/shot` | Chụp màn hình ngay |
| `/live 30` | Chụp 1 ảnh/2 giây trong 30 giây (tối đa 300) |
| `/stop` | Dừng `/live` |
| `/status` | Tên máy, uptime, `/live` còn bao lâu |

Nhiều máy: thêm tên máy vào cuối — `/shot PC-Van-Phong`. Không thêm tên thì mọi máy
cùng chụp. `/status` luôn trả lời từ mọi máy để bạn biết máy nào đang chạy.

Nếu `getUpdates` báo lỗi **409 Conflict**, bot đang có webhook. Mở trình duyệt:
`https://api.telegram.org/bot<TOKEN>/deleteWebhook` rồi khởi động lại app.

## Cài đặt

### 1. Tạo bot Telegram

1. Nhắn `@BotFather` → `/newbot` → lấy **token**.
2. Nhắn `@userinfobot` → lấy **chat_id** của bạn.
3. Mở chat với bot vừa tạo và bấm **Start** (bắt buộc, nếu không bot không gửi được).

### 2. Build

```bat
python -m pip install -r requirements.txt
build.bat
```

### 3. Cài

Sửa `config.example.json` → đổi tên thành `config.json` → điền `bot_token`, `chat_id`,
`device_name`. Rồi chạy `install.bat` (không cần quyền Admin).

Kiểm tra cấu hình: `%LOCALAPPDATA%\TeleMonitor\telemonitor.exe --test`

## Nhiều máy

Dùng **cùng một bot** cho mọi máy. Trên mỗi máy:

1. Copy `telemonitor.exe` + `config.json` vào `%LOCALAPPDATA%\TeleMonitor\`.
2. Đặt `device_name` khác nhau (`PC-Van-Phong`, `Laptop-Me`, ...).
3. Chạy `telemonitor.exe --install` rồi `telemonitor.exe`.

Mọi tin nhắn có tiền tố `[TênMáy]` nên xem một chat là biết máy nào.

## Cấu hình

| Key | Ý nghĩa |
|---|---|
| `bot_token` | Token bot Telegram |
| `chat_id` | Chat nhận tin |
| `device_name` | Tên máy hiện trong tin nhắn (rỗng = hostname) |
| `poll_interval` | Giây giữa 2 lần kiểm tra (tối thiểu 0.5) |
| `send_startup_message` | Gửi tin khi khởi động |
| `track_activity` | Theo dõi chuyển ứng dụng |
| `sensitive_keywords` | Thêm từ khóa nhạy cảm ngoài danh sách có sẵn |
| `sensitive_cooldown` | Giây tối thiểu giữa 2 ảnh (tối thiểu 30) |
| `enable_commands` | Bật nhận lệnh `/shot`, `/live`, `/stop`, `/status` |
| `command_poll_timeout` | Giây long-poll getUpdates (5–50) |
| `ignore_apps` | Tên exe bỏ qua |

## Log

`%LOCALAPPDATA%\TeleMonitor\app.log` (1MB × 3 file).

## Gỡ cài đặt

Chạy `uninstall.bat`.

## Giới hạn đã biết

- Không đọc URL trình duyệt; nhận diện trang nhạy cảm dựa trên tiêu đề trang,
  nên site lạ không có tên trong tiêu đề sẽ không bị phát hiện.
- Chỉ chạy trên Windows.
- Tool này giám sát máy. Chỉ dùng trên máy bạn sở hữu hoặc đã được người dùng
  máy đó đồng ý rõ ràng — giám sát người khác không có sự đồng ý là vi phạm pháp luật.
```

- [ ] **Step 5: Build thử**

Run: `build.bat`
Expected: tạo `dist\telemonitor.exe`, không lỗi.

- [ ] **Step 6: Commit**

```bash
git add build.bat install.bat uninstall.bat README.md
git commit -m "build: pyinstaller packaging and install scripts"
```

---

### Task 8: Kiểm tra end-to-end trên máy thật

**Files:** không sửa code.

- [ ] **Step 1: Chạy test tự động**

Run: `python tests/test_core.py`
Expected: `all passed`

- [ ] **Step 2: Test gửi tin**

Run: `dist\telemonitor.exe --test`
Expected: hộp thoại "Đã gửi tin test", điện thoại nhận tin.

- [ ] **Step 3: Cài và chạy nền**

Run: `install.bat`
Expected: không có cửa sổ nào hiện ra; `%LOCALAPPDATA%\TeleMonitor\telemonitor.exe` tồn tại;
`reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v TeleMonitor` in ra đường dẫn exe.

- [ ] **Step 4: Kiểm tra theo dõi**

Chuyển qua lại Notepad → Chrome (mở vài tab) → Explorer.
Expected: mỗi lần đổi nhận đúng 1 tin; đứng yên một cửa sổ thì không nhận thêm tin.

- [ ] **Step 5: Kiểm tra ảnh nhạy cảm**

Mở một trang có tiêu đề chứa từ khóa trong danh sách, đợi 5 giây.
Expected: nhận 1 ảnh toàn màn hình kèm caption `⚠️ [TênMáy] ...`; lướt tiếp trong 5 phút không nhận thêm ảnh.

- [ ] **Step 6: Kiểm tra lệnh xem màn hình**

Trong chat Telegram với bot:
1. Gõ `/shot` → nhận 1 ảnh toàn màn hình trong vài giây.
2. Gõ `/live 20` → nhận ảnh mỗi 2 giây, tổng ~10 ảnh, tự dừng sau 20 giây.
3. Gõ `/live 20` rồi `/stop` sau 6 giây → ảnh dừng ngay, có tin "Đã dừng /live".
4. Gõ `/status` → nhận tin tên máy + uptime + thời gian live còn lại.
5. Từ một tài khoản Telegram **khác**, nhắn `/shot` cho bot.
   Expected: **không nhận được gì cả** — không ảnh, không phản hồi. Log ghi không có dòng xử lý nào.

- [ ] **Step 7: Kiểm tra tự khởi động**

Khởi động lại Windows.
Expected: không có cửa sổ, điện thoại nhận tin `🟢 Máy tính đã bật`.

- [ ] **Step 7: Kiểm tra chống chạy trùng**

Chạy `%LOCALAPPDATA%\TeleMonitor\telemonitor.exe` lần nữa.
Expected: không có gì xảy ra, không có tin nhắn thứ hai, log ghi `another instance is already running`.

- [ ] **Step 8: Commit trạng thái cuối**

```bash
git add -A
git commit -m "chore: verified end-to-end on Windows"
```
