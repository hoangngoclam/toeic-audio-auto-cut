# TOEIC Audio Cut Service — Design

Date: 2026-07-24

## Mục tiêu

Public pipeline cắt file nghe TOEIC (đang chạy local) thành một dịch vụ web trên VPS.
Người dùng upload 1 file MP3 + email → server cắt thành các clip theo câu hỏi →
đóng gói zip → upload Google Drive → gửi link tải về email.

## Phạm vi (scope)

- CÓ: web upload đơn giản, hàng đợi xử lý, cắt audio bằng Python, upload Drive, gửi email.
- KHÔNG (YAGNI): tài khoản người dùng, trang theo dõi tiến trình, lịch sử job, thanh toán,
  hỗ trợ định dạng khác ngoài MP3, cắt song song nhiều-core/GPU.

## Kiến trúc

```
Browser ──upload mp3 + email──► FastAPI (web)
                                   │ validate (.mp3, ≤50MB) + lưu file tạm + enqueue job
                                   ▼
                                Redis queue ──► RQ Worker (pool = 2)
                                                  1. transcribe (whisper → segments)
                                                  2. cut         (segments → clips/*.mp3)
                                                  3. zip clips   → <basename>_clips.zip
                                                  4. upload zip  → Google Drive (service account)
                                                  5. share link  "anyone with the link"
                                                  6. email link  (Gmail SMTP)
                                                  7. cleanup     (xóa file tạm + clips + zip)
```

Whisper transcribe là CPU-bound. Trên 1 VPS, nhiều job KHÔNG chạy nhanh hơn khi song song —
queue + pool giới hạn (2 worker) nhận nhiều upload cùng lúc nhưng xử lý có kiểm soát.

## Thành phần (mỗi phần 1 nhiệm vụ rõ ràng)

| Thành phần | File | Nhiệm vụ | Phụ thuộc |
|-----------|------|----------|-----------|
| Web/API | `server/app.py` | Nhận upload, validate, enqueue, trả thông báo | FastAPI, RQ, Redis |
| Trang upload | `server/static/index.html` | Form: chọn `.mp3` + nhập email + submit | — |
| Job xử lý | `server/worker.py` | Chạy 7 bước pipeline cho 1 job | các module dưới |
| Transcribe | `transcribe.py` (đã có) | MP3 → segments JSON | faster-whisper |
| Cắt clip | `cut.py` (PORT từ `cut.js`) | segments → `clips/*.mp3` | ffmpeg |
| Drive | `server/drive.py` | Upload file + tạo link chia sẻ | google-api-python-client, service account |
| Email | `server/mailer.py` | Gửi email link (hoặc báo lỗi) | smtplib, Gmail App Password |
| Config | `server/config.py` | Đọc secrets/settings từ env | python-dotenv |

`transcribe.py` refactor nhẹ: bọc phần transcribe thành hàm `transcribe(audio, out_path)`
để worker gọi trực tiếp, vẫn giữ được chạy CLI.

`cut.py` là port 1-1 từ `cut.js` (cùng logic tìm cue "Questions X through Y" / "Number N",
cùng layout TOEIC: Q1–31 lẻ, Q32–100 nhóm 3). Sau khi port xong → xóa `cut.js` và `web/`.

## Luồng dữ liệu

1. `POST /submit` (multipart): `file` (.mp3), `email`.
2. Validate: đuôi `.mp3`, size ≤ 50MB, email hợp lệ. Lỗi → trả 400 + thông báo.
3. Lưu file vào `jobs/<job_id>/input.mp3`. Enqueue `process_job(job_id, email)`.
4. Trả HTTP 200: "Đã nhận. Link tải sẽ gửi về email của bạn."
5. Worker chạy pipeline. Kết quả: email chứa link Drive, hoặc email báo lỗi.
6. Worker xóa `jobs/<job_id>/` sau khi xong.

## Xử lý lỗi

- Validate tại biên (web) trước khi nhận file lớn.
- Mỗi bước worker bọc try/except; lỗi bất kỳ → gửi email báo lỗi thân thiện cho khách + log chi tiết server-side.
- "Không tìm thấy cue nào" (transcript lạ) → coi là lỗi job, báo email.
- `finally` luôn dọn file tạm (thành công hay thất bại) để không đầy đĩa.
- Không nuốt lỗi im lặng; log traceback.

## Bảo mật

- Service account JSON, Gmail App Password, Redis URL → đọc từ env / file ngoài git.
  Thêm `.gitignore` cho credentials `*.json`, `.env`, `jobs/`, `clips/`.
- Validate & sanitize tên file (dùng `job_id` sinh sẵn, không tin tên file client).
- Giới hạn size 50MB chặn ở cả FastAPI và check thủ công.
- Drive link: "anyone with the link" (read-only) — chấp nhận vì đây là clip đề luyện, không nhạy cảm.

## Config (env)

```
REDIS_URL=redis://localhost:6379
GOOGLE_SA_JSON=/path/service-account.json
GDRIVE_FOLDER_ID=<id folder đã share cho service account>
GMAIL_USER=you@gmail.com
GMAIL_APP_PASSWORD=<app password 16 ký tự>
MAX_UPLOAD_MB=50
WHISPER_MODEL=small
```

## Deploy VPS

- Cài `ffmpeg`, Python 3.11+, Redis.
- 3 process (systemd): `redis`, `uvicorn server.app:app`, `rq worker`.
- (Tùy chọn) Nginx reverse proxy với `client_max_body_size 50m`.

## Kiểm thử

- `cut.py`: self-check assert với `transcript.json` sẵn có — số clip & nhãn khớp output của `cut.js`.
- Validate: test từ chối file không phải mp3 / >50MB / email sai.
- Drive & mailer: dùng interface/mock trong test, không gọi thật.

## Điểm bỏ qua (ponytail), thêm khi cần

- Trang theo dõi tiến trình — thêm khi khách cần biết trạng thái.
- Nhiều worker song song thật (multi-core/GPU) — thêm khi volume vượt 1 worker CPU.
- Rate limit / chống spam upload — thêm khi bị lạm dụng.
- Xóa file Drive cũ tự động — thêm khi Drive đầy.
