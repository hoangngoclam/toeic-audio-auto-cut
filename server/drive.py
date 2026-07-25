"""Upload a file to Google Drive (service account) and return a
'anyone with the link' read-only share URL. Import is lazy so the app runs
locally without google libs configured."""

from server import config


def upload_and_share(file_path, name=None):
    """Upload file_path to the configured Drive folder, make it link-readable,
    return the shareable URL. Raises if Drive is not configured."""
    if not config.DRIVE_ENABLED:
        raise RuntimeError("Drive not configured (GOOGLE_SA_JSON / GDRIVE_FOLDER_ID)")

    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = service_account.Credentials.from_service_account_file(
        config.GOOGLE_SA_JSON, scopes=["https://www.googleapis.com/auth/drive"])
    service = build("drive", "v3", credentials=creds, cache_discovery=False)

    meta = {"name": name or file_path.split("/")[-1], "parents": [config.GDRIVE_FOLDER_ID]}
    media = MediaFileUpload(file_path, mimetype="application/zip", resumable=True)
    created = service.files().create(
        body=meta, media_body=media, fields="id").execute()
    file_id = created["id"]

    service.permissions().create(
        fileId=file_id, body={"role": "reader", "type": "anyone"}).execute()

    return f"https://drive.google.com/uc?export=download&id={file_id}"
