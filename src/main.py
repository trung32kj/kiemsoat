"""TeleMonitor entry point: hidden Windows agent reporting activity to Telegram."""
from __future__ import annotations

import ctypes
import logging
import logging.handlers
import os
import queue
import shutil
import subprocess
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
import updater
import wininfo

APP_NAME = "TeleMonitor"
VERSION = "1.0.0"
MUTEX_NAME = "Local\\TeleMonitorMutex"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
LOG_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_NAME
UPDATE_DIR = LOG_DIR / "update"
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


def is_installed() -> bool:
    """True when this exe already lives in the install folder."""
    if not getattr(sys, "frozen", False):
        return True
    return Path(sys.executable).parent == LOG_DIR


def self_install() -> int:
    """Copy this exe into %LOCALAPPDATA%\\TeleMonitor, enable autostart, launch it.

    Runs when the user double-clicks the downloaded exe. The running copy cannot
    be moved while executing, so it copies itself, registers the installed copy,
    starts it, and exits. A MessageBox explains each outcome because there is no
    console.
    """
    target_dir = LOG_DIR
    target = target_dir / "telemonitor.exe"
    source = Path(sys.executable)

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        say(f"Không tạo được thư mục {target_dir}:\n{exc}", error=True, box=True)
        return 1

    # Carry the user's config along when one sits next to the downloaded exe.
    src_cfg = source.parent / "config.json"
    dst_cfg = target_dir / "config.json"
    if src_cfg.exists() and src_cfg != dst_cfg:
        try:
            shutil.copy2(src_cfg, dst_cfg)
        except OSError as exc:
            log.warning("không copy được config.json: %s", exc)

    if source.resolve() != target.resolve():
        try:
            shutil.copy2(source, target)
        except OSError as exc:
            say(f"Không copy được file exe:\n{exc}", error=True, box=True)
            return 1

    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{target}"')
    except OSError as exc:
        say(f"Không bật được tự khởi động:\n{exc}", error=True, box=True)
        return 1

    subprocess.Popen([str(target)], close_fds=True)
    msg = (
        f"Đã cài TeleMonitor.\n\n"
        f"Thư mục: {target_dir}\n"
        f"Tự khởi động: đã bật\n\n"
        f"Nếu chưa điền bot_token / chat_id, mở config.json trong thư mục trên."
    )
    say(msg, box=True)
    return 0


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
        say(
            f"Thiếu bot_token / chat_id.\n\nMở file này và điền:\n"
            f"{config.config_path()}\n\nSau đó chạy lại telemonitor.exe.",
            error=True,
            box=True,
        )
        return
    log.info("start device=%s interval=%s", cfg["device_name"], cfg["poll_interval"])
    sender = Sender(cfg)
    sender.start()
    if cfg["enable_commands"]:
        commands.CommandListener(cfg, sender, commands.LiveSession()).start()
        log.info("command listener enabled (/shot, /live, /stop, /status)")
    if cfg["update_repo"]:
        def on_update_error(reason: str) -> None:
            sender.put(
                "text",
                f"❌ [{telegram.escape(cfg['device_name'])}] "
                f"Cập nhật thất bại: {telegram.escape(reason)[:300]}",
            )

        updater.start_watcher(cfg, VERSION, UPDATE_DIR, on_update_error)
        log.info("update watcher enabled for %s (v%s)", cfg["update_repo"], VERSION)
    if cfg["send_startup_message"]:
        stamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        sender.put(
            "text",
            f"🟢 <b>Máy tính đã bật</b>\n"
            f"🖥️ <b>{telegram.escape(cfg['device_name'])}</b>\n"
            f"🕒 {stamp}\n"
            f"🔖 v{telegram.escape(VERSION)}",
        )
    poll_forever(cfg, sender)


def do_update() -> int:
    cfg = config.load()
    repo = cfg.get("update_repo", "")
    if not repo:
        say("update_repo rỗng trong config.json — không có nguồn cập nhật.", error=True, box=True)
        return 1
    try:
        info = updater.check(repo, VERSION)
    except updater.UpdateError as exc:
        say(f"Kiểm tra thất bại: {exc}", error=True, box=True)
        return 1
    if not info:
        say(f"Đang là bản mới nhất (v{VERSION}).", box=True)
        return 0
    try:
        dest = UPDATE_DIR / (updater.APP_EXE_NAME + ".new")
        updater.download(info["url"], info["sha256_url"], dest)
        say(f"Đã tải và xác minh {info['version']}. Đang cài...", box=True)
        updater.apply(dest)
    except updater.UpdateError as exc:
        say(f"Cập nhật thất bại: {exc}", error=True, box=True)
        return 1
    return 0


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
    updater.cleanup_old()
    if "--install" in args:
        install_autostart()
        return 0
    if "--uninstall" in args:
        uninstall_autostart()
        return 0
    if "--test" in args:
        return test_send()
    if "--update" in args:
        return do_update()
    if "--version" in args:
        say(f"{APP_NAME} v{VERSION}")
        return 0
    if "--install" not in args and "--uninstall" not in args and not is_installed():
        return self_install()
    if not acquire_single_instance():
        log.info("another instance is already running, exiting")
        return 0
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
