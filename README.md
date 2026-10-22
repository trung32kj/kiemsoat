# TeleMonitor

Agent chạy nền trên Windows, báo hoạt động về Telegram và cho phép xem màn hình từ xa
bằng lệnh chat.

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

**Cách nhanh nhất:** bấm đúp `telemonitor.exe`. Nó tự copy vào
`%LOCALAPPDATA%\TeleMonitor`, bật tự khởi động, chạy nền và hiện hộp thoại xác nhận.
Nếu `config.json` nằm cạnh file exe tải về, nó được copy theo.

**Hoặc chạy `install.bat`** — làm đúng việc trên nhưng cho cả thư mục project.

Sau khi cài, sửa `%LOCALAPPDATA%\TeleMonitor\config.json` nếu cần (điền `bot_token`,
`chat_id`, `device_name`), rồi khởi động lại app.

Kiểm tra cấu hình: `%LOCALAPPDATA%\TeleMonitor\telemonitor.exe --test`

Bấm exe lần nữa khi đã cài thì nó chỉ chạy app, không cài lại.

## Nhiều máy

Dùng **cùng một bot** cho mọi máy. Trên mỗi máy:

1. Copy `telemonitor.exe` + `config.json` vào `%LOCALAPPDATA%\TeleMonitor\`.
2. Đặt `device_name` khác nhau (`PC-Van-Phong`, `Laptop-Me`, ...).
3. Chạy `telemonitor.exe --install` rồi `telemonitor.exe`.

Mọi tin nhắn có tiền tố `[TênMáy]` nên xem một chat là biết máy nào.

## Từ khóa nhạy cảm

Danh sách cố định nằm ở [src/capture.py](src/capture.py) — 108 từ khóa, chia 5 nhóm:

| Nhóm | Ví dụ |
|---|---|
| Web người lớn quốc tế | `pornhub`, `xvideos`, `xhamster`, `onlyfans`, `brazzers` |
| Hentai / JAV châu Á | `hentai`, `nhentai`, `missav`, `javhd`, `dlsite` |
| Cam site | `chaturbate`, `stripchat`, `bongacams` |
| Cờ bạc / cá độ | `789bet`, `w88`, `fun88`, `xoilac`, `nhà cái`, `lô đề`, `đá gà` |
| Tiếng Việt / ma túy | `phim sex`, `phim heo`, `khiêu dâm`, `gái gọi`, `ma túy`, `cần sa` |

Thêm từ khóa riêng cho một máy mà không cần build lại: `config.json` →
`"sensitive_keywords": ["tên riêng", "..."]`.

So khớp dùng **ranh giới từ** nên không bắt nhầm: `sex` không khớp trong "Es**sex**",
`jav` không khớp trong "**Jav**aScript". Xổ số hợp pháp (`xổ số miền bắc`) cũng không khớp.

Sửa danh sách cố định thì phải chạy lại `build.bat`.



## Tự động cập nhật

App kiểm tra GitHub Releases lúc khởi động (sau 30 giây) và mỗi 6 giờ. Có bản mới thì
tự tải, xác minh SHA-256, thay file exe đang chạy và khởi động lại — không hỏi gì.

Bật bằng cách điền `update_repo` trong `config.json`:

```json
"update_repo": "your-github-user/telemonitor"
```

Để trống = tắt cập nhật.

### Phát hành bản mới

1. Sửa `VERSION` trong [src/main.py](src/main.py) (vd `1.1.0`), chạy `build.bat`.
2. Tính hash và tạo release:

```bat
certutil -hashfile dist\telemonitor.exe SHA256 > dist\telemonitor.exe.sha256
```

3. Lên GitHub → Releases → Draft a new release:
   - Tag: `v1.1.0` (phải khớp `VERSION`, có tiền tố `v`)
   - Đính 2 file: `telemonitor.exe` và `telemonitor.exe.sha256`
   - Publish.

Thiếu 1 trong 2 file thì app bỏ qua bản đó và ghi log lỗi — không cài file chưa xác minh.

Kiểm tra thủ công: `%LOCALAPPDATA%\TeleMonitor\telemonitor.exe --update`

## Cấu hình

| Key | Ý nghĩa |
|---|---|
| `bot_token` | Token bot Telegram |
| `chat_id` | Chat nhận tin (chỉ chat này điều khiển được) |
| `device_name` | Tên máy hiện trong tin nhắn (rỗng = hostname) |
| `poll_interval` | Giây giữa 2 lần kiểm tra (tối thiểu 0.5) |
| `send_startup_message` | Gửi tin khi khởi động |
| `track_activity` | Theo dõi chuyển ứng dụng |
| `sensitive_keywords` | Thêm từ khóa nhạy cảm ngoài danh sách có sẵn |
| `sensitive_cooldown` | Giây tối thiểu giữa 2 ảnh (tối thiểu 30) |
| `enable_commands` | Bật nhận lệnh `/shot`, `/live`, `/stop`, `/status` |
| `command_poll_timeout` | Giây long-poll getUpdates (5–50) |
| `update_repo` | `user/repo` GitHub để tự cập nhật (rỗng = tắt) |
| `update_check_interval` | Giây giữa 2 lần kiểm tra bản mới (tối thiểu 600) |
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
