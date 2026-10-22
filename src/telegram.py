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
                "409 Conflict: bot đang có webhook. Mở "
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
