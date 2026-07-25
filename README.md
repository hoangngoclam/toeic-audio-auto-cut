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

**Chỉ cần `GROQ_API_KEY`; không cần Drive/Sheet/Gmail để test.** Khi chưa cấu hình,
zip kết quả được giữ lại trong `results/<job_id>_<tên>_clips.zip`, "email" chỉ in ra log
của server, và **giới hạn 5 lượt/email không được áp dụng** (log sẽ ghi rõ). Đủ để kiểm
tra transcribe + cắt.

## Bật Drive + Sheet + email (khi deploy)

Copy `.env.example` → `.env` và điền:

```
GROQ_API_KEY=gsk_...                        # bắt buộc
GOOGLE_SA_JSON=/path/service-account.json   # + share folder & sheet cho service account
GDRIVE_FOLDER_ID=<id folder>
GOOGLE_SHEET_ID=<id sheet>                  # phần /d/<id>/edit trong URL
SHEET_TAB=customers-info
MAX_JOBS_PER_EMAIL=5
GMAIL_USER=you@gmail.com
GMAIL_APP_PASSWORD=<app password 16 ký tự>
```

Có đủ → tự động upload Drive (link "anyone with the link"), ghi log khách vào Sheet + chặn
quá 5 lượt/email, và gửi email thật.

**Nhớ share Google Sheet cho email của service account với quyền Editor**, nếu không mọi
lượt gửi sẽ trả về 503.

Sheet dùng tab `customers-info`, mỗi job 1 dòng:

| A Email | B Status | C Link resource | D Time |
|---|---|---|---|
| `khach@example.com` | `pending` → `done` / `error` | link Drive | `2026-07-25 14:03:21` |

## Khi job lỗi (`status = error`)

Hệ thống gửi **2 email** ngay lúc job thất bại:

- **Khách hàng** — thư xin lỗi, nói rõ **lượt không bị tính** nên gửi lại được. Không có
  traceback (khách không đọc được và cũng không giúp gì).
- **Admin** (`ADMIN_EMAIL`, mặc định `lammt1998@gmail.com`) — job id, email khách, tên file,
  thời gian, kèm **nguyên văn traceback**. Đây là cách bạn biết có lỗi mà không phải ngồi
  nhìn Sheet.

Hai lần gửi độc lập nhau: một hộp thư chết không làm mất thư kia, và cả hai đều không che
lỗi gốc (vẫn ghi ra `journalctl -u toeic-cut`).

Lưu ý: lỗi **503 lúc submit** (không đọc được Google Sheet) chỉ ghi log, không gửi mail —
lỗi đó khách thấy ngay trên màn hình, và mail hoá sẽ spam mỗi lần có người bấm gửi.

## Giới hạn & kiểm tra đầu vào

- **5 lượt / 1 email.** Chỉ đếm các job `done` trong Sheet — job lỗi không tính, khách gửi
  lại được. Hết lượt → HTTP 429 + thông báo trên web.
- **Chỉ nhận đề nghe TOEIC đầy đủ.** `server/audio/verify.py` kiểm tra ngay trong request
  (~5 giây): độ dài 35–60 phút, rồi transcribe 90 giây đầu và đòi ≥2 từ khoá phần
  directions ("listening test", "Part One", "picture in your test book"…). Không đạt → 400
  + thông báo trên màn hình, và **không** tốn tiền transcribe cả file.
  Lưu ý: file TOEIC đã bị cắt mất phần mở đầu cũng sẽ bị từ chối.

## Thành phần

| File | Nhiệm vụ |
|------|----------|
| `server/app.py` | FastAPI: validate email/.mp3 → quota → upload ≤50MB → verify TOEIC → enqueue |
| `server/pipeline.py` | Job: transcribe → cut → zip → upload → email → ghi Sheet → cleanup |
| `server/sheets.py` | Log khách + đếm quota trên Google Sheet |
| `server/drive.py` | Upload Drive + share link |
| `server/mailer.py` | Gửi email (Gmail SMTP) |
| `server/config.py` | Đọc env |
| `server/audio/verify.py` | Có đúng là đề nghe TOEIC không? (độ dài + 90s đầu) |
| `server/audio/groq_asr.py` | MP3 → transcript.json qua Whisper trên Groq |
| `server/audio/cut.py` | transcript → clips/*.mp3 (ffmpeg) |

## Nhận dạng giọng nói (ASR)

Chỉ dùng Groq (`whisper-large-v3-turbo`): tiến trình ~150MB RAM, vừa VPS 2GB —
faster-whisper cũ cần ~1GB RAM mỗi worker nên đã bỏ. Cần `GROQ_API_KEY` trong `.env`
(thiếu key → server báo lỗi ngay khi khởi động).

Chạy riêng các bước audio (debug nhanh, không cần server; `groq_asr` in thời gian từng bước):

```bash
.venv/bin/python -m server.audio.groq_asr test-files/Test_07.mp3 transcript.json
.venv/bin/python -m server.audio.cut test-files/Test_07.mp3 clips transcript.json

.venv/bin/python -m server.audio.verify test-files/Test_07.mp3   # file này có được nhận?
.venv/bin/python -m server.audio.verify                          # self-check bộ từ khoá
```

Hàng đợi: `ThreadPoolExecutor(max_workers=2)` trong tiến trình — cùng giới hạn
"tối đa 2 job cùng lúc" như spec, nhưng 1 process, không cần Redis/RQ. Thêm RQ
khi cần job sống sót qua restart.

## Yêu cầu hệ thống

`ffmpeg` + `ffprobe` (đã có qua Homebrew), Python 3.11+.

## Deploy VPS

Một lệnh, chạy **trên** VPS (Ubuntu + Caddy) trong thư mục clone:

```bash
git clone https://github.com/hoangngoclam/toeic-audio-auto-cut.git && cd toeic-audio-auto-cut

sudo DOMAIN=toeic.example.com ./deploy.sh   # lần 1: cài ffmpeg/venv/deps + tạo .env, rồi dừng
nano .env                                   # bạn tự điền: GROQ_API_KEY, GOOGLE_*, GMAIL_*
sudo DOMAIN=toeic.example.com ./deploy.sh   # lần 2: systemd + Caddy + chạy
```

`deploy.sh` **không bao giờ ghi giá trị vào `.env`** — chỉ tạo file mẫu 0600 rồi đọc lại để
kiểm tra. Lần chạy đầu vẫn cài hết những gì không cần secret, sau đó dừng ở bước kiểm tra
config. Nếu `GROQ_API_KEY` trống → dừng; `GOOGLE_SHEET_ID`/`GOOGLE_SA_JSON` trống → chỉ
cảnh báo (app chạy được, nhưng không có log khách và **không chặn quota**);
`GOOGLE_SA_JSON` trỏ tới file không tồn tại / user chạy service không đọc được → dừng.
File service-account `.json` bạn tự upload lên VPS (đã bị gitignore).

`deploy.sh` cài ffmpeg + venv, tạo `.env`, systemd unit `toeic-cut`, site Caddy
`/etc/caddy/conf.d/toeic-cut.caddy`, rồi kiểm tra app đã lên. Chạy lại bao nhiêu lần cũng
được. Nhớ điền `GOOGLE_SHEET_ID` + `GOOGLE_SA_JSON` vào `.env` trên VPS, không thì quota
không được áp dụng.

Update: `git pull && sudo systemctl restart toeic-cut`.
Biến tùy chọn: `PORT` (8001), `SERVICE` (toeic-cut), `RUN_USER`. `DOMAIN` có thể là IP
(khi đó chỉ HTTP, không TLS).
