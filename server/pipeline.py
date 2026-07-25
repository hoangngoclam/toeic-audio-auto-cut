"""The job: transcribe -> cut -> zip -> upload(Drive) -> email -> cleanup.

Runs in a worker thread. Every step is wrapped: any failure emails a friendly
error to the customer, marks the Sheet row `error`, and logs the traceback
server-side. jobs/<id>/ is always removed in finally so the disk doesn't fill.

sheet_row is the row app.py already logged as `pending` (None when Sheets is
unconfigured). Only `done` rows count against the per-email quota, so a failed
job costs the customer nothing.

When Drive/email aren't configured (local testing) the zip is kept in results/
and its path is logged instead of uploaded/emailed."""

import os
import shutil
import traceback

from server import config, drive, mailer, sheets
from server.audio.cut import cut
from server.audio.groq_asr import transcribe_groq

JOBS_DIR = "jobs"
RESULTS_DIR = "results"


def _log_status(row, status, link=""):
    """Sheet bookkeeping must never sink a job that already produced a link."""
    try:
        sheets.set_status(row, status, link)
    except Exception:
        traceback.print_exc()


def process_job(job_id, email, original_name, sheet_row=None):
    job_dir = os.path.join(JOBS_DIR, job_id)
    input_mp3 = os.path.join(job_dir, "input.mp3")
    clips_dir = os.path.join(job_dir, "clips")
    basename = os.path.splitext(original_name)[0] or "toeic"
    zip_base = os.path.join(job_dir, f"{basename}_clips")

    try:
        print(f"[job {job_id}] transcribing {input_mp3} ...")
        transcript_path = os.path.join(job_dir, "transcript.json")
        transcribe_groq(input_mp3, transcript_path)

        print(f"[job {job_id}] cutting ...")
        clips = cut(input_mp3, clips_dir, transcript_path)
        print(f"[job {job_id}] {len(clips)} clips")

        print(f"[job {job_id}] zipping ...")
        zip_path = shutil.make_archive(zip_base, "zip", clips_dir)

        if config.DRIVE_ENABLED:
            print(f"[job {job_id}] uploading to Drive ...")
            link = drive.upload_and_share(zip_path, f"{basename}_clips.zip")
        else:
            # ponytail: no Drive configured -> keep the zip locally for testing.
            os.makedirs(RESULTS_DIR, exist_ok=True)
            kept = os.path.join(RESULTS_DIR, f"{job_id}_{basename}_clips.zip")
            shutil.move(zip_path, kept)
            link = os.path.abspath(kept)
            print(f"[job {job_id}] Drive disabled — zip kept at {link}")

        mailer.send_result(email, link)
        _log_status(sheet_row, "done", link)
        print(f"[job {job_id}] DONE -> {link}")

    except Exception:
        traceback.print_exc()
        _log_status(sheet_row, "error")
        try:
            mailer.send_error(email)
        except Exception:
            traceback.print_exc()
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)
        print(f"[job {job_id}] cleaned up {job_dir}")
