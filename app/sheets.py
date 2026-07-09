"""Google Sheets → PDF export via service account auth.

Uses only google-auth (JWT/RSA), httpx (HTTP), and pypdf (PDF merge).
No system-level dependencies required.
"""
import io
import json
import logging
import time

import google.auth.crypt
import google.auth.jwt
import httpx
from pypdf import PdfReader, PdfWriter

logger = logging.getLogger(__name__)

_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
_TOKEN_URI = "https://oauth2.googleapis.com/token"
_EXPORT_URL = "https://docs.google.com/spreadsheets/d/{sheet_id}/export"
_EXPORT_PARAMS = {
    "format": "pdf",
    "size": "A4",
    "portrait": "true",
    "fitw": "false",
    "fith": "true",
    "gridlines": "false",
    "printtitle": "false",
    "sheetnames": "false",
}


async def _get_access_token(creds_path: str) -> str:
    with open(creds_path) as f:
        info = json.load(f)

    signer = google.auth.crypt.RSASigner.from_service_account_info(info)
    now = int(time.time())
    payload = {
        "iss": info["client_email"],
        "sub": info["client_email"],
        "scope": _SCOPE,
        "aud": _TOKEN_URI,
        "iat": now,
        "exp": now + 3600,
    }
    assertion = google.auth.jwt.encode(signer, payload)
    if isinstance(assertion, bytes):
        assertion = assertion.decode("utf-8")

    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            _TOKEN_URI,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )
        r.raise_for_status()
        return r.json()["access_token"]


async def _export_tab(sheet_id: str, gid: str, token: str) -> bytes:
    """Export a single sheet tab as PDF bytes."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            _EXPORT_URL.format(sheet_id=sheet_id),
            params={**_EXPORT_PARAMS, "gid": gid},
            headers={"Authorization": f"Bearer {token}"},
            follow_redirects=True,
        )
        r.raise_for_status()
        return r.content


def _first_page(pdf_bytes: bytes) -> PdfReader:
    return PdfReader(io.BytesIO(pdf_bytes))


def _merge_first_pages(pdfs: list[bytes]) -> bytes:
    """Return a PDF containing only page 1 of each input PDF."""
    writer = PdfWriter()
    for pdf_bytes in pdfs:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if reader.pages:
            writer.add_page(reader.pages[0])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


async def export_sheet_as_pdf(sheet_id: str, creds_path: str, gids: list[str]) -> bytes:
    """Export each sheet tab in gids and merge their first pages into one PDF.

    If gids is empty, exports the full document in a single request (no blank-page removal).
    Raises httpx.HTTPError on API failure.
    """
    token = await _get_access_token(creds_path)

    if not gids:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                _EXPORT_URL.format(sheet_id=sheet_id),
                params=_EXPORT_PARAMS,
                headers={"Authorization": f"Bearer {token}"},
                follow_redirects=True,
            )
            r.raise_for_status()
            return r.content

    tab_pdfs = []
    for gid in gids:
        tab_pdfs.append(await _export_tab(sheet_id, gid, token))

    return _merge_first_pages(tab_pdfs)
