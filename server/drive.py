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
    # supportsAllDrives is what makes GDRIVE_FOLDER_ID on a Shared drive work, and
    # a Shared drive is mandatory here: a service account has no storage quota of
    # its own, so uploading into a My Drive folder always 403s.
    try:
        created = service.files().create(
            body=meta, media_body=media, fields="id",
            supportsAllDrives=True).execute()
        file_id = created["id"]

        service.permissions().create(
            fileId=file_id, body={"role": "reader", "type": "anyone"},
            supportsAllDrives=True).execute()
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
        hint = (" — GDRIVE_FOLDER_ID is on a My Drive, where a service account has no "
                "storage quota. It must be a folder inside a Shared drive that the SA "
                "is a member of (Content manager)")
    elif str(status) == "404":
        hint = (" — GDRIVE_FOLDER_ID not found: wrong id, or the SA is not a member of "
                "that Shared drive (a Shared drive folder is invisible to it otherwise)")
    elif "sharingRateLimit" in body or "cannotShare" in body:
        hint = (" — the Workspace admin blocks 'anyone with the link' sharing; allow "
                "external link sharing for that Shared drive")
    elif str(status) == "403":
        hint = " — Drive API disabled for the project, or the SA lacks write access on that folder"
    else:
        hint = ""
    return f"Drive upload failed ({status}): {reason}{hint}"
