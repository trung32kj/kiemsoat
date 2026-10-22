# TeleMonitor — Thiết kế

Ngày: 2026-10-23

## Mục tiêu

Ứng dụng Python chạy nền trên Windows (không cửa sổ), tự khởi động cùng Windows,
gửi thông báo qua Telegram Bot:

1. Khi máy bật: tên thiết bị + thời gian.
2. Khi người dùng chuyển ứng dụng/tab trình duyệt: tên app + window title, có chống lặp.
3. Khi phát hiện trang nhạy cảm (theo danh sách từ khóa cố định): chụp toàn màn hình,
   gửi ảnh, giới hạn 1 ảnh / 5 phút / máy.

Nhiều máy dùng chung 1 bot: mỗi máy 1 `config.json` với `device_name` riêng,
mọi tin nhắn có tiền tố `[TênMáy]`.

4. Tự động cập nhật: kiểm tra GitHub Releases, tải bản mới, xác minh SHA-256,
   thay exe đang chạy và khởi động lại (xem mục "Tự động cập nhật").

## Tự động cập nhật

Cơ chế: **self-replace**. Windows không cho ghi đè file exe đang chạy, nên app
đổi tên exe hiện tại thành `.old`, chép exe mới vào đúng tên cũ, chạy lại nó,
rồi thoát. Exe mới xoá file `.old` lúc khởi động.

Module `src/updater.py`:

| Hàm | Việc |
|---|---|
| `parse_version(s) -> tuple[int, ...]` | `"v1.2.3"` → `(1,2,3)`; so sánh được, không dùng packaging |
| `check(repo, timeout) -> dict \| None` | Gọi `api.github.com/repos/<repo>/releases/latest`; trả `{version, url, sha256, size}`; `None` nếu không có bản mới hoặc bị tắt |
| `download(url, dest, expected_sha, timeout) -> None` | Tải về `%LOCALAPPDATA%\TeleMonitor\update\telemonitor.new.exe`, tính SHA-256, so khớp, ném `UpdateError` nếu lệch |
| `apply(new_exe) -> None` | `os.replace` exe hiện tại → `.old`, chép `new_exe` → vị trí cũ, `subprocess.Popen([exe])`, `os._exit(0)` |
| `cleanup_old()` | Xoá `telemonitor.exe.old` nếu còn (gọi lúc khởi động) |

Nguồn version và hash: release tag `v1.2.3` + asset `telemonitor.exe` + file
`telemonitor.exe.sha256` trong cùng release. Không có file `.sha256` → bỏ qua
bản đó, ghi log, không cài (fail closed).

Chu kỳ: kiểm tra lúc khởi động (sau 30 giây để không chậm startup) và mỗi
`update_check_interval` giây (mặc định 6 giờ). Chỉ chạy khi `update_repo` khác rỗng.

Bảo mật: chỉ tải qua HTTPS từ `api.github.com` và `objects.githubusercontent.com`;
SHA-256 bắt buộc; nếu hash lệch thì xoá file tải về và ghi log ERROR.

Thông báo Telegram: `⬆️ [Máy] Đã cập nhật lên v1.2.3` sau khi khởi động lại,
hoặc `❌ Cập nhật thất bại: <lý do>`.

CLI: `--update` kiểm tra và cài ngay (dùng để test thủ công).

## Kiến trúc

Một process, một vòng poll, một worker thread gửi tin. Không GUI, không server.

| Module | Trách nhiệm | Phụ thuộc |
|---|---|---|
| `src/config.py` | Đọc/tạo `config.json` cạnh exe, giá trị mặc định, kiểm tra hợp lệ | stdlib |
| `src/wininfo.py` | `GetForegroundWindow` → (tên exe, window title) qua ctypes | stdlib |
| `src/tracker.py` | Quyết định có gửi hay không (dedupe theo cặp app+title) | stdlib |
| `src/capture.py` | Dò từ khóa nhạy cảm, chụp toàn màn hình → JPEG bytes | Pillow |
| `src/telegram.py` | `sendMessage` / `sendPhoto` qua `urllib.request`, multipart tự viết | stdlib |
| `src/commands.py` | Poll `getUpdates`, xác thực chat_id, xử lý `/shot`, `/live N`, `/stop`, `/status` | stdlib |
| `src/main.py` | Vòng lặp, hàng đợi gửi, mutex 1-instance, logging, CLI | stdlib |

Ranh giới: `wininfo`, `capture`, `telegram` không biết gì về nhau; `main` là nơi duy nhất
ghép chúng lại. Mỗi module test được độc lập.

## Luồng

```
Windows logon → HKCU\...\Run → telemonitor.exe
  → tạo mutex Local\TeleMonitorMutex (đã có instance thì thoát)
  → gửi tin khởi động
  → loop mỗi poll_interval giây:
       (app, title) = wininfo.active()
       nếu rỗng hoặc trong ignore_apps → bỏ qua
       nếu tracker thấy mới → đẩy tin nhắn vào queue
       nếu title khớp từ khóa nhạy cảm và quá cooldown → chụp màn hình, đẩy ảnh vào queue
  → worker thread: lấy queue, gửi, retry 3 lần, backoff
```

Queue tối đa 100 phần tử, bỏ phần tử cũ nhất khi đầy. Mạng hỏng không chặn vòng poll.

## Định dạng tin nhắn

Khởi động:

```
🟢 Máy tính đã bật
🖥️ PC-Van-Phong
🕒 23/10/2026 08:15:32
```

Chuyển ứng dụng:

```
[PC-Van-Phong] chrome.exe
— Tin tức - Google Chrome
```

Ảnh nhạy cảm: caption `⚠️ [PC-Van-Phong] <title>`.

Parse mode HTML, escape ký tự đặc biệt.

## Nhận diện trang nhạy cảm

Chrome/Edge không đưa URL vào window title, chỉ có tiêu đề trang. Vì vậy nhận diện
dựa trên **từ khóa cố định trong code** (`capture.SENSITIVE_KEYWORDS`) so khớp
case-insensitive với title. Giới hạn đã biết: site lạ không có tên trong title sẽ
không bị phát hiện. Chọn hướng này theo yêu cầu (nhẹ, không phụ thuộc UI Automation).

Danh sách mở rộng thêm được qua `config.json` → `sensitive_keywords`.

## Chống lặp

`tracker.ChangeTracker` giữ cặp `(app, title)` cuối cùng đã gửi. Chỉ gửi khi cặp khác
cặp trước. Title rỗng/không đổi → không gửi. Chuyển A → B → A gửi lại A (đúng ý người dùng).

## Lệnh điều khiển hai chiều (xem màn hình)

Agent chạy thêm một thread poll `getUpdates` (long polling, timeout 25s) để nhận lệnh
từ chat Telegram. **Không mở port, không cần IP công khai** — chỉ HTTPS ra ngoài, nên
chạy được sau NAT/4G.

Xác thực: mọi update có `message.chat.id` khác `chat_id` trong config bị **bỏ qua im lặng**
(không trả lời, tránh lộ sự tồn tại của agent).

Lệnh hỗ trợ:

| Lệnh | Việc |
|---|---|
| `/shot` | Chụp toàn màn hình, gửi ngay (bỏ qua cooldown) |
| `/live N` | Chụp 1 ảnh mỗi 2 giây trong N giây (N mặc định 30, tối đa 300) |
| `/stop` | Dừng phiên `/live` đang chạy |
| `/status` | Trả tên máy, thời gian hoạt động, phiên live còn bao lâu |

Nhiều máy: lệnh có thể kèm tên máy — `/shot PC-Van-Phong`. Máy nào có `device_name`
khớp mới thực hiện; lệnh không kèm tên thì **tất cả máy** thực hiện. `/status` luôn trả
lời mọi máy (không kèm tên) để liệt kê các máy đang sống.

Giới hạn: `/live` tối đa 300 giây, 1 ảnh/2 giây → tối đa 150 ảnh, tự dừng khi hết giờ.
Ảnh gửi qua chat Telegram riêng, TLS. Không lưu ảnh ra đĩa.

`getUpdates` không hoạt động nếu bot đã đặt webhook. Khi khởi động, nếu `getUpdates`
trả lỗi 409, ghi log rõ ràng: cần gọi `deleteWebhook` cho bot này trước.

## Cấu hình

`config.json` đặt cạnh file exe:

```json
{
  "bot_token": "",
  "chat_id": "",
  "device_name": "",
  "poll_interval": 2.0,
  "send_startup_message": true,
  "track_activity": true,
  "sensitive_keywords": [],
  "sensitive_cooldown": 300,
  "enable_commands": true,
  "command_poll_timeout": 25,
  "ignore_apps": ["LockApp.exe", "SearchHost.exe", "ShellExperienceHost.exe",
                  "StartMenuExperienceHost.exe", "TextInputHost.exe"]
}
```

`device_name` rỗng → lấy `socket.gethostname()`. Thiếu file → tạo file mẫu và ghi log lỗi.
`bot_token`/`chat_id` rỗng → chạy nhưng không gửi, ghi log cảnh báo.

## CLI

- `telemonitor.exe` (mặc định): chạy nền.
- `--install`: ghi `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\TeleMonitor`.
- `--uninstall`: xoá khoá trên.
- `--test`: gửi 1 tin thử rồi thoát, in lỗi ra console (dùng để kiểm tra token/chat id).

## Đóng gói

PyInstaller `--onefile --noconsole --name telemonitor`. Không console, không tray.
`install.bat` copy exe + config vào `%LOCALAPPDATA%\TeleMonitor`, chạy `--install`.
`uninstall.bat` chạy `--uninstall` và xoá thư mục.

## Log

`%LOCALAPPDATA%\TeleMonitor\app.log`, RotatingFileHandler 1MB × 3.

## Kiểm thử

`tests/test_core.py` — assert thuần, không framework:
- `ChangeTracker`: lần đầu gửi, trùng thì không, đổi app gửi, đổi title gửi, title rỗng bỏ qua.
- `capture.is_sensitive`: khớp/không khớp, từ khóa mở rộng, không phân biệt hoa thường.
- `telegram` multipart: biên đúng, có boundary, tên field đúng.
- `config`: default điền đủ, file hỏng → quay về default.

## Ngoài phạm vi

- Không đọc URL thật của trình duyệt (đã nêu giới hạn).
- Không gửi log/keylogger, không chặn trang, không điều khiển máy từ xa.
- Không tự cập nhật.
