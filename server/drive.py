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
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    creds = service_account.Credentials.from_service_account_file(
        config.GOOGLE_SA_JSON, scopes=["https://www.googleapis.com/auth/drive"])
    service = build("drive", "v3", credentials=creds, cache_discovery=False)

    meta = {"name": name or file_path.split("/")[-1], "parents": [config.GDRIVE_FOLDER_ID]}
    media = MediaFileUpload(file_path, mimetype="application/zip", resumable=True)
    try:
        created = service.files().create(
            body=meta, media_body=media, fields="id").execute()
        file_id = created["id"]

        service.permissions().create(
            fileId=file_id, body={"role": "reader", "type": "anyone"}).execute()
    except HttpError as e:
        raise RuntimeError(_explain(e)) from e

    return f"https://drive.google.com/uc?export=download&id={file_id}"


def _explain(e):
    """Turn an HttpError into one line an operator can act on.

    Worth the branches: Drive is where this pipeline fails, and the raw error is
    20 lines of JSON whose useful part scrolls off the end of a journalctl page."""
    body = str(e)
    status = getattr(e, "status_code", None) or getattr(getattr(e, "resp", None), "status", "?")
    reason = getattr(e, "reason", "") or body
    if "storageQuota" in body or "storage quota" in body:
        hint = (" — a service account has NO Drive storage of its own. Point "
                "GDRIVE_FOLDER_ID at a folder on a Shared drive with the SA added as "
                "member, or leave Drive unconfigured to keep the zip in results/")
    elif str(status) == "404":
        hint = " — GDRIVE_FOLDER_ID not found, or the folder isn't shared with the service account"
    elif str(status) == "403":
        hint = " — Drive API disabled for the project, or the SA lacks Editor on that folder"
    else:
        hint = ""
    return f"Drive upload failed ({status}): {reason}{hint}"
