"""FastAPI web front: upload .mp3 + email -> validate -> enqueue -> 200.

Jobs run in an in-process pool of 2 threads (ponytail: same 'max 2 at once'
guarantee the spec's RQ pool gave, without Redis or a second process; add RQ
when you need jobs to survive a restart). Whisper releases the GIL in the
C extension, so 2 CPU jobs really do run concurrently."""

import os
import re
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from server import config
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

    pool.submit(process_job, job_id, email.strip(), file.filename)
    return {"message": "Đã nhận. Link tải sẽ gửi về email của bạn."}
