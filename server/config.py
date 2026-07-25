"""Settings from environment (.env). Groq is REQUIRED (it's the only ASR
backend); Drive, Gmail and Sheets are optional for local testing — without
their creds the pipeline still cuts clips, keeps the zip in results/, prints
the "email", and does not enforce the per-email quota."""

import os

from dotenv import load_dotenv

load_dotenv()

MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "50"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

# Groq hosted Whisper is the only backend (faster-whisper needed ~1GB RSS per
# worker, which doesn't fit the 2GB VPS). server/audio/ reads GROQ_* from env
# itself — it must stay importable without the web layer; this check is here
# only so a misconfigured box dies at startup instead of mid-job.
if not os.environ.get("GROQ_API_KEY"):
    raise RuntimeError("GROQ_API_KEY is not set (see .env.example)")

# Optional: Google Drive upload (service account).
GOOGLE_SA_JSON = os.environ.get("GOOGLE_SA_JSON", "")
GDRIVE_FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID", "")

# Optional: customer log + quota in a Google Sheet (same service account).
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")
SHEET_TAB = os.environ.get("SHEET_TAB", "customers-info")
MAX_JOBS_PER_EMAIL = int(os.environ.get("MAX_JOBS_PER_EMAIL", "5"))

# Optional: Gmail SMTP.
GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

# Where job failures are reported. Defaults to the operator rather than "" so a
# box that was never configured still shouts instead of failing silently.
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "lammt1998@gmail.com")

DRIVE_ENABLED = bool(GOOGLE_SA_JSON and GDRIVE_FOLDER_ID)
EMAIL_ENABLED = bool(GMAIL_USER and GMAIL_APP_PASSWORD)
SHEETS_ENABLED = bool(GOOGLE_SA_JSON and GOOGLE_SHEET_ID)
