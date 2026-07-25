"""Customer log in a Google Sheet: one row per accepted job.

Tab `customers-info`, columns: A Email | B Status | C Link resource | D Time.
Status goes `pending` -> `done` / `error`. The per-email quota counts only
`done` rows, so a failed job doesn't burn the customer's 5 tries.

No-op + log when GOOGLE_SA_JSON / GOOGLE_SHEET_ID are absent (same as
drive.py and mailer.py), so local testing needs no creds — with the quota
disabled, which is logged loudly.
"""

import re
from datetime import datetime

from server import config

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _values():
    """Sheets values() client. ponytail: rebuilt per call — 2 calls per job,
    caching it would only buy a race on credential refresh."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(
        config.GOOGLE_SA_JSON, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds,
                 cache_discovery=False).spreadsheets().values()


def _range(a1):
    # Quoted: the tab name has a hyphen.
    return f"'{config.SHEET_TAB}'!{a1}"


def count_done(email):
    """Number of finished jobs already logged for this email. Raises on API
    failure — the caller must not accept a job it can't quota-check."""
    if not config.SHEETS_ENABLED:
        print("[sheets] disabled — quota NOT enforced")
        return 0

    rows = _values().get(
        spreadsheetId=config.GOOGLE_SHEET_ID, range=_range("A2:B"),
    ).execute().get("values", [])

    want = email.strip().lower()
    return sum(1 for r in rows
               if len(r) >= 2
               and r[0].strip().lower() == want
               and r[1].strip().lower() == "done")


def append_pending(email):
    """Log a `pending` row; return its 1-based row number (None when disabled)."""
    if not config.SHEETS_ENABLED:
        print(f"[sheets] disabled — would log {email}")
        return None

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    res = _values().append(
        spreadsheetId=config.GOOGLE_SHEET_ID,
        range=_range("A:D"),
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [[email, "pending", "", now]]},
    ).execute()

    # updatedRange looks like "'customers-info'!A7:D7".
    m = re.search(r"![A-Z]+(\d+)", res.get("updates", {}).get("updatedRange", ""))
    return int(m.group(1)) if m else None


def set_status(row, status, link=""):
    """Update B/C of a logged row. No-op when Sheets is off or row is unknown."""
    if not (config.SHEETS_ENABLED and row):
        return
    _values().update(
        spreadsheetId=config.GOOGLE_SHEET_ID,
        range=_range(f"B{row}:C{row}"),
        valueInputOption="USER_ENTERED",
        body={"values": [[status, link]]},
    ).execute()
    print(f"[sheets] row {row} -> {status}")
