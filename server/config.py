"""Settings from environment (.env). Drive + email are OPTIONAL for local
testing: when their creds are absent the pipeline still cuts clips and keeps
the zip in results/ instead of uploading/emailing."""

import os

from dotenv import load_dotenv

load_dotenv()

MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "50"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")

# Optional: Google Drive upload (service account).
GOOGLE_SA_JSON = os.environ.get("GOOGLE_SA_JSON", "")
GDRIVE_FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID", "")

# Optional: Gmail SMTP.
GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

DRIVE_ENABLED = bool(GOOGLE_SA_JSON and GDRIVE_FOLDER_ID)
EMAIL_ENABLED = bool(GMAIL_USER and GMAIL_APP_PASSWORD)
