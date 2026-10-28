"""First-run setup dialog: ask for bot token and chat id instead of editing JSON."""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("TeleMonitor")


def _test_credentials(token: str, chat_id: str) -> str | None:
    """Return an error message, or None when the bot can message the chat."""
    import telegram

    try:
        me = telegram.get_me(token)
    except telegram.TelegramError as exc:
        return f"Token không hợp lệ:\n{exc}"
    try:
        telegram.send_message(
            token, chat_id, f"✅ Kết nối thành công tới <b>{me}</b>"
        )
    except telegram.TelegramError as exc:
        return (
            f"Không gửi được tin tới chat_id {chat_id}:\n{exc}\n\n"
            "Kiểm tra bạn đã bấm Start trong chat với bot chưa."
        )
    return None


def ask_config(cfg: dict, path: Path) -> dict | None:
    """Show a small window. Returns the updated config, or None if cancelled."""
    import tkinter as tk
    from tkinter import messagebox, ttk

    result: dict | None = None

    root = tk.Tk()
    root.title("TeleMonitor — Cấu hình lần đầu")
    root.resizable(False, False)
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass

    frame = ttk.Frame(root, padding=16)
    frame.grid(row=0, column=0, sticky="nsew")

    ttk.Label(
        frame,
        text="Nhập thông tin bot Telegram. Lấy token từ @BotFather,\n"
        "lấy chat_id từ @userinfobot.",
        justify="left",
    ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

    ttk.Label(frame, text="Bot token").grid(row=1, column=0, sticky="w", pady=4)
    token_var = tk.StringVar(value=cfg.get("bot_token", ""))
    token_entry = ttk.Entry(frame, textvariable=token_var, width=48, show="•")
    token_entry.grid(row=1, column=1, sticky="we", pady=4)

    show_var = tk.BooleanVar(value=False)

    def toggle_show() -> None:
        token_entry.configure(show="" if show_var.get() else "•")

    ttk.Checkbutton(
        frame, text="Hiện token", variable=show_var, command=toggle_show
    ).grid(row=2, column=1, sticky="w")

    ttk.Label(frame, text="Chat ID").grid(row=3, column=0, sticky="w", pady=4)
    chat_var = tk.StringVar(value=cfg.get("chat_id", ""))
    ttk.Entry(frame, textvariable=chat_var, width=48).grid(
        row=3, column=1, sticky="we", pady=4
    )

    ttk.Label(frame, text="Tên máy").grid(row=4, column=0, sticky="w", pady=4)
    name_var = tk.StringVar(value=cfg.get("device_name", ""))
    ttk.Entry(frame, textvariable=name_var, width=48).grid(
        row=4, column=1, sticky="we", pady=4
    )
    ttk.Label(
        frame, text="Để trống thì dùng tên máy Windows", foreground="#666"
    ).grid(row=5, column=1, sticky="w")

    status = ttk.Label(frame, text="", foreground="#c00", wraplength=420)
    status.grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def on_save() -> None:
        nonlocal result
        token = token_var.get().strip()
        chat = chat_var.get().strip()
        if not token or not chat:
            status.configure(text="Cần nhập cả Bot token và Chat ID.")
            return
        status.configure(text="Đang kiểm tra...", foreground="#666")
        root.update_idletasks()
        err = _test_credentials(token, chat)
        if err:
            status.configure(text=err.splitlines()[0], foreground="#c00")
            messagebox.showerror("Không kết nối được", err, parent=root)
            return
        result = dict(cfg)
        result["bot_token"] = token
        result["chat_id"] = chat
        result["device_name"] = name_var.get().strip() or cfg.get("device_name", "")
        root.destroy()

    def on_cancel() -> None:
        nonlocal result
        result = None
        root.destroy()

    buttons = ttk.Frame(frame)
    buttons.grid(row=7, column=0, columnspan=2, sticky="e", pady=(14, 0))
    ttk.Button(buttons, text="Huỷ", command=on_cancel).pack(side="right", padx=(8, 0))
    ttk.Button(buttons, text="Lưu và chạy", command=on_save).pack(side="right")

    root.bind("<Return>", lambda _e: on_save())
    root.bind("<Escape>", lambda _e: on_cancel())
    token_entry.focus_set()
    root.update_idletasks()
    root.lift()
    root.mainloop()

    if result is None:
        return None
    try:
        path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        log.info("config saved to %s", path)
    except OSError as exc:
        log.error("không ghi được config: %s", exc)
        return None
    return result
