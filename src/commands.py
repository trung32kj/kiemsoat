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
    """One /live run at a time; a new /live extends the current deadline."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ends_at = 0.0
        self._thread: threading.Thread | None = None

    def start(self, seconds: int, on_frame) -> None:
        with self._lock:
            self._ends_at = time.monotonic() + seconds
            if self._thread and self._thread.is_alive():
                return  # running loop picks up the new deadline
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
            # Reentrant-safe check: threading.Lock is not reentrant, so never
            # call remaining() while already holding self._lock.
            with self._lock:
                if self._ends_at - time.monotonic() <= 0:
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
        self.poll_timeout = cfg.get("command_poll_timeout", 25)
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
                updates = telegram.get_updates(
                    self.token, self.offset, timeout=self.poll_timeout
                )
                backoff = 5
                for upd in updates:
                    self.offset = max(self.offset, int(upd.get("update_id", 0)) + 1)
                    try:
                        self._handle(upd)
                    except Exception:  # noqa: BLE001 - one bad update must not stop the loop
                        log.exception("command handling failed")
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
