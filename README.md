# TOEIC Audio Cut Service

Upload 1 file MP3 bài nghe TOEIC + email → server cắt thành clip theo câu hỏi →
zip → (tùy chọn) upload Google Drive → gửi link về email.

## Chạy local (test)

```bash
# 1. cài deps (venv đã có sẵn)
.venv/bin/python -m pip install -r requirements.txt

# 2. chạy server
.venv/bin/uvicorn server.app:app --reload

# 3. mở http://127.0.0.1:8000 → chọn .mp3 + nhập email → Gửi xử lý
```

**Không cần Drive/Gmail để test.** Khi chưa cấu hình `.env`, zip kết quả được
giữ lại trong `results/<job_id>_<tên>_clips.zip` và "email" chỉ được in ra log
của server (kèm đường dẫn zip). Đủ để kiểm tra transcribe + cắt.

## Bật Drive + email (khi deploy)

Copy `.env.example` → `.env` và điền:

```
GOOGLE_SA_JSON=/path/service-account.json   # + share folder cho service account
GDRIVE_FOLDER_ID=<id folder>
GMAIL_USER=you@gmail.com
GMAIL_APP_PASSWORD=<app password 16 ký tự>
```

Có đủ → tự động upload Drive (link "anyone with the link") + gửi email thật.

## Thành phần

| File | Nhiệm vụ |
|------|----------|
| `server/app.py` | FastAPI: upload, validate (.mp3 ≤50MB, email), enqueue |
| `server/pipeline.py` | Job 7 bước: transcribe → cut → zip → upload → email → cleanup |
| `server/drive.py` | Upload Drive + share link |
| `server/mailer.py` | Gửi email (Gmail SMTP) |
| `server/config.py` | Đọc env |
| `transcribe.py` | MP3 → transcript.json (faster-whisper) |
| `cut.py` | transcript → clips/*.mp3 (ffmpeg), port 1-1 từ cut.js |

Hàng đợi: `ThreadPoolExecutor(max_workers=2)` trong tiến trình — cùng giới hạn
"tối đa 2 job cùng lúc" như spec, nhưng 1 process, không cần Redis/RQ. Thêm RQ
khi cần job sống sót qua restart.

## Yêu cầu hệ thống

`ffmpeg` + `ffprobe` (đã có qua Homebrew), Python 3.11+.

## Deploy VPS

```bash
apt install ffmpeg
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn server.app:app --host 0.0.0.0 --port 8000
```

Nginx (tùy chọn): `client_max_body_size 50m;`. Chạy uvicorn dưới systemd.
