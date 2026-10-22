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


def test_config_command_keys_normalized():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        path.write_text(json.dumps({"enable_commands": False,
                                    "command_poll_timeout": 999}), encoding="utf-8")
        cfg = config.load(path)
        assert cfg["enable_commands"] is False
        assert cfg["command_poll_timeout"] == 50, "phải kẹp tối đa 50"


def test_tracker_reports_only_changes():
    from tracker import ChangeTracker
    t = ChangeTracker()
    assert t.changed("chrome.exe", "Tin tức") is True, "lần đầu phải gửi"
    assert t.changed("chrome.exe", "Tin tức") is False, "trùng thì không gửi"
    assert t.changed("chrome.exe", "Tin tức - Google Chrome") is True, "đổi title phải gửi"
    assert t.changed("notepad.exe", "x.txt") is True, "đổi app phải gửi"
    assert t.changed("notepad.exe", "") is True, "app mới dù title rỗng vẫn phải gửi"
    assert t.changed("notepad.exe", "") is False, "cùng app, title rỗng vẫn rỗng thì bỏ qua"
    assert t.changed("", "x") is False, "app rỗng bỏ qua"


def test_tracker_is_case_insensitive():
    from tracker import ChangeTracker
    t = ChangeTracker()
    assert t.changed("Chrome.exe", "ABC") is True
    assert t.changed("chrome.exe", "abc") is False


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
    body, ctype = _multipart({"caption": "x"},
                             {"photo": ("a.jpg", b"\xff\xd8junk", "image/jpeg")})
    assert b'filename="a.jpg"' in body
    assert b"Content-Type: image/jpeg" in body
    assert b"\xff\xd8junk" in body


def test_capture_is_sensitive():
    from capture import is_sensitive
    assert is_sensitive("Pornhub - Google Chrome") is True
    assert is_sensitive("Tin tức hôm nay") is False
    assert is_sensitive("") is False
    assert is_sensitive("XVideos", ["xvideos"]) is True
    assert is_sensitive("my custom site", ["CUSTOM"]) is True, "phải không phân biệt hoa thường"
    assert is_sensitive("nothing here", [""]) is False, "từ khóa rỗng bỏ qua"


def test_capture_matches_vietnamese_terms():
    from capture import is_sensitive
    assert is_sensitive("Phim sex Việt Nam mới nhất") is True
    assert is_sensitive("Cá độ bóng đá - Nhà cái uy tín") is True
    assert is_sensitive("Xôi Lạc TV - Trực tiếp bóng đá") is True
    assert is_sensitive("Gái gọi Hà Nội") is True
    assert is_sensitive("Ma túy và tác hại") is True


def test_capture_no_false_positives():
    from capture import is_sensitive
    assert is_sensitive("Essex County Council") is False, "sex không được khớp trong Essex"
    assert is_sensitive("JavaScript Tutorial") is False, "jav không được khớp trong JavaScript"
    assert is_sensitive("Xổ số miền Bắc hôm nay") is False, "xổ số hợp pháp không bị chặn"
    assert is_sensitive("Học lập trình Python") is False
    assert is_sensitive("Sunwin không phải tên người") is True, "tên thương hiệu vẫn khớp"


def test_capture_keyword_count():
    from capture import SENSITIVE_KEYWORDS
    assert len(SENSITIVE_KEYWORDS) >= 80, len(SENSITIVE_KEYWORDS)
    assert len(set(SENSITIVE_KEYWORDS)) == len(SENSITIVE_KEYWORDS), "không được trùng từ khóa"


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
    assert parse("/live abc", "PC1") is None, "token không phải số = tên máy khác"
    assert parse("/live 45 PC1", "PC1") == ("live", 45, "PC1")


def test_command_parse_ignores_others():
    from commands import parse
    assert parse("hello", "PC1") is None
    assert parse("", "PC1") is None
    assert parse("/unknown", "PC1") is None
    assert parse("/stop@MyBot", "PC1") == ("stop", 0, ""), "bỏ @botname"
    assert parse("/STATUS", "PC1") == ("status", 0, "")


def test_live_session_runs_and_expires():
    import time
    from commands import LiveSession
    frames = []
    live = LiveSession()
    live.start(2, lambda: frames.append(time.monotonic()))
    time.sleep(2.6)
    assert 1 <= len(frames) <= 3, f"phải chụp 1-3 khung, được {len(frames)}"
    assert live.remaining() == 0, "hết giờ phải về 0"


def test_live_session_stop_is_immediate():
    import time
    from commands import LiveSession
    frames = []
    live = LiveSession()
    live.start(60, lambda: frames.append(1))
    time.sleep(0.2)
    live.stop()
    assert live.remaining() == 0
    time.sleep(2.4)
    assert len(frames) <= 2, f"sau /stop không được chụp tiếp, được {len(frames)}"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("all passed")
