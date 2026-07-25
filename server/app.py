"""FastAPI web front: upload .mp3 + email -> validate -> enqueue -> 200.

Validation order is deliberate, cheapest gate first:
  email shape -> .mp3 extension -> per-email quota (1 Sheets read) ->
  stream to disk under MAX_UPLOAD_MB -> "is this really TOEIC?" (~5s).
Everything the customer can get wrong is answered on screen; only real jobs
reach the Sheet and the pool.

Jobs run in an in-process pool of 2 threads (ponytail: same 'max 2 at once'
guarantee the spec's RQ pool gave, without Redis or a second process; add RQ
when you need jobs to survive a restart)."""

import os
import re
import shutil
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from server import config, sheets
from server.audio.verify import verify_toeic
from server.pipeline import JOBS_DIR, process_job

app = FastAPI(title="TOEIC Audio Cut")
pool = ThreadPoolExecutor(max_workers=2)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
STATIC = os.path.join(os.path.dirname(__file__), "static")
CHUNK = 1024 * 1024


def _cleanup(job_dir):
    shutil.rmtree(job_dir, ignore_errors=True)


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.post("/submit")
async def submit(file: UploadFile = File(...), email: str = Form(...)):
    # --- validate at the boundary, before reading the whole file ---
    if not EMAIL_RE.match(email.strip()):
        raise HTTPException(400, "Email không hợp lệ.")
    if not (file.filename or "").lower().endswith(".mp3"):
        raise HTTPException(400, "Chỉ nhận file .mp3.")
    email = email.strip()

    # Quota, read from the Sheet. A Sheets outage must NOT hand out free jobs.
    try:
        used = sheets.count_done(email)
    except Exception:
        traceback.print_exc()
        raise HTTPException(503, "Hệ thống đang bận, bạn vui lòng thử lại sau.")
    if used >= config.MAX_JOBS_PER_EMAIL:
        raise HTTPException(
            429,
            f"Email này đã dùng hết {config.MAX_JOBS_PER_EMAIL} lượt cắt file. "
            "Vui lòng liên hệ chúng tôi nếu bạn cần thêm lượt.")

    job_id = uuid.uuid4().hex
    job_dir = os.path.join(JOBS_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    dest = os.path.join(job_dir, "input.mp3")

    # Stream to disk, enforcing the size cap as we go (don't trust any header).
    size = 0
    try:
        with open(dest, "wb") as out:
            while chunk := await file.read(CHUNK):
                size += len(chunk)
                if size > config.MAX_UPLOAD_BYTES:
                    raise HTTPException(400, f"File vượt quá {config.MAX_UPLOAD_MB}MB.")
                out.write(chunk)
    except HTTPException:
        _cleanup(job_dir)
        raise
    except Exception:
        _cleanup(job_dir)
        raise HTTPException(500, "Lỗi khi lưu file.")

    if size == 0:
        _cleanup(job_dir)
        raise HTTPException(400, "File rỗng.")

    # Only a real TOEIC listening test can be cut by our fixed Q1-100 layout.
    try:
        reason = verify_toeic(dest)
    except Exception:
        traceback.print_exc()
        _cleanup(job_dir)
        raise HTTPException(503, "Không kiểm tra được file, bạn vui lòng thử lại sau.")
    if reason:
        print(f"[submit] rejected {file.filename}: {reason}")
        _cleanup(job_dir)
        raise HTTPException(
            400,
            "File này không phải bài nghe TOEIC đầy đủ (khoảng 45 phút, 100 câu). "
            "Hệ thống chỉ cắt được đề nghe TOEIC, bạn vui lòng kiểm tra lại file.")

    try:
        row = sheets.append_pending(email)
    except Exception:
        traceback.print_exc()
        _cleanup(job_dir)
        raise HTTPException(503, "Hệ thống đang bận, bạn vui lòng thử lại sau.")

    pool.submit(process_job, job_id, email, file.filename, row)
    left = config.MAX_JOBS_PER_EMAIL - used - 1
    return {"message": f"Đã nhận file. Link tải sẽ được gửi tới {email} "
                       f"trong vài phút. Bạn còn {left} lượt."}
