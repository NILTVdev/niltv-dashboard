"""Google Sheets access for the onboarding pipeline.

Writes the staff "NIL TV Applications" sheet (export). Auth is the same
service account the GA4 / Search Console pulls use (``GOOGLE_CREDENTIALS_JSON``,
falling back to ``GA4_CREDENTIALS_JSON``); the target sheet must be shared
with that account's client_email as an editor.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from backend.config import get_settings

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class SheetsError(RuntimeError):
    pass


def credentials_path() -> str:
    s = get_settings()
    return s.google_credentials_json or s.ga4_credentials_json


def service_account_email() -> str:
    """client_email of the service account (share sheets with this)."""
    import json

    path = credentials_path()
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh).get("client_email", "")
    except OSError:
        return ""


def client():
    path = credentials_path()
    if not path:
        raise SheetsError("GOOGLE_CREDENTIALS_JSON / GA4_CREDENTIALS_JSON is not configured")
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as e:  # pragma: no cover
        raise SheetsError("google-api-python-client is not installed") from e
    creds = service_account.Credentials.from_service_account_file(path, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _explain(e: Exception, spreadsheet_id: str) -> SheetsError:
    msg = str(e)
    if "403" in msg or "PERMISSION_DENIED" in msg:
        return SheetsError(
            f"no access to spreadsheet {spreadsheet_id}: share it with {service_account_email() or 'the service account'}"
        )
    if "404" in msg:
        return SheetsError(f"spreadsheet {spreadsheet_id} not found (check the id)")
    return SheetsError(f"Sheets API error on {spreadsheet_id}: {msg[:300]}")


def ensure_tab(svc, spreadsheet_id: str, title: str) -> None:
    meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets.properties.title").execute()
    if title in [sh["properties"]["title"] for sh in meta.get("sheets", [])]:
        return
    svc.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
    ).execute()


def write_table(spreadsheet_id: str, tab: str, header: list[str], rows: list[list[Any]]) -> int:
    """Replace the whole tab with header + rows. Returns rows written."""
    svc = client()
    try:
        ensure_tab(svc, spreadsheet_id, tab)
        svc.spreadsheets().values().clear(spreadsheetId=spreadsheet_id, range=f"'{tab}'").execute()
        values = [header] + [["" if v is None else v for v in r] for r in rows]
        svc.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"'{tab}'!A1",
            valueInputOption="RAW",
            body={"values": values},
        ).execute()
        # Freeze the header row + bold it (best effort).
        sheet_id = _sheet_id(svc, spreadsheet_id, tab)
        if sheet_id is not None:
            svc.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": [
                {"updateSheetProperties": {
                    "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                    "fields": "gridProperties.frozenRowCount"}},
                {"repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                    "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                    "fields": "userEnteredFormat.textFormat.bold"}},
            ]}).execute()
    except SheetsError:
        raise
    except Exception as e:  # noqa: BLE001
        raise _explain(e, spreadsheet_id) from e
    return len(rows)


def _sheet_id(svc, spreadsheet_id: str, title: str) -> Optional[int]:
    meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets.properties").execute()
    for sh in meta.get("sheets", []):
        if sh["properties"]["title"] == title:
            return sh["properties"]["sheetId"]
    return None
