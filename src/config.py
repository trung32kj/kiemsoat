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
        cfg["command_poll_timeout"] = max(
            5, min(50, int(cfg.get("command_poll_timeout") or 25))
        )
    except (TypeError, ValueError):
        cfg["command_poll_timeout"] = 25
    if not isinstance(cfg.get("sensitive_keywords"), list):
        cfg["sensitive_keywords"] = []
    if not isinstance(cfg.get("ignore_apps"), list):
        cfg["ignore_apps"] = list(DEFAULTS["ignore_apps"])
    return cfg
