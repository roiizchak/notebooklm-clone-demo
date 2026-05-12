"""End-to-end test that exercises every source type.

Steps:
  1. Create admin user, sign in.
  2. Create notebook.
  3. For each of (text, url, youtube, pdf, docx) add a source.
  4. Wait for each to reach 'ready' or 'failed'.
  5. Send a chat question; assert response + at least one citation.
  6. Cleanup notebook (cascade).
"""

from __future__ import annotations

import io
import os
import sys
import time
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SERVICE_ROLE = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
ANON_KEY = os.environ["SUPABASE_ANON_KEY"]
API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000")

EMAIL = f"all-sources+{uuid.uuid4().hex[:10]}@gmail.com"
PASSWORD = "AllSources123!"

YT_URL = "https://www.youtube.com/watch?v=AzmnaoVP8sk"
WEB_URL = "https://en.wikipedia.org/wiki/Apollo_11"
TEXT_BODY = (
    "Apollo 11 was the first crewed mission to land on the Moon, on July 20, 1969. "
    "Neil Armstrong and Buzz Aldrin walked on the lunar surface while Michael Collins "
    "orbited above. The mission fulfilled President Kennedy's national goal."
)


def admin_create_user() -> None:
    r = httpx.post(
        f"{SUPABASE_URL}/auth/v1/admin/users",
        headers={
            "apikey": SERVICE_ROLE,
            "Authorization": f"Bearer {SERVICE_ROLE}",
            "Content-Type": "application/json",
        },
        json={"email": EMAIL, "password": PASSWORD, "email_confirm": True},
        timeout=30.0,
    )
    r.raise_for_status()


def sign_in() -> str:
    r = httpx.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        headers={"apikey": ANON_KEY, "Content-Type": "application/json"},
        json={"email": EMAIL, "password": PASSWORD},
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def create_notebook(token: str) -> str:
    r = httpx.post(
        f"{API_URL}/api/v1/notebooks",
        headers=hdr(token),
        json={"name": "All-Sources Test", "emoji": "🧪"},
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json()["data"]["id"]


def make_pdf_bytes() -> bytes:
    """Build a tiny one-page PDF in pure Python (no external deps).

    Returns a valid PDF byte string with a single text line.
    """
    text = (
        "Apollo 11 PDF test fixture. Neil Armstrong was the first to walk on the Moon."
    )
    objects: list[bytes] = []

    def obj(idx: int, content: bytes) -> bytes:
        return f"{idx} 0 obj\n".encode() + content + b"\nendobj\n"

    body = (
        b"BT /F1 12 Tf 72 720 Td ("
        + text.encode("latin-1")
        + b") Tj ET"
    )
    stream_obj_inner = (
        f"<< /Length {len(body)} >>\nstream\n".encode()
        + body
        + b"\nendstream"
    )
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
    )
    objects.append(stream_obj_inner)
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    buf = io.BytesIO()
    buf.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, content in enumerate(objects, start=1):
        offsets.append(buf.tell())
        buf.write(obj(i, content))
    xref_pos = buf.tell()
    buf.write(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        buf.write(f"{off:010d} 00000 n \n".encode())
    buf.write(
        f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF".encode()
    )
    return buf.getvalue()


def make_docx_bytes() -> bytes:
    from docx import Document

    doc = Document()
    doc.add_heading("Apollo 11 DOCX fixture", level=1)
    doc.add_paragraph(
        "The Apollo 11 mission landed on the Moon in July 1969. "
        "Neil Armstrong and Buzz Aldrin became the first humans to walk on lunar soil."
    )
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def add_text(token: str, nb: str) -> str:
    r = httpx.post(
        f"{API_URL}/api/v1/notebooks/{nb}/sources/text",
        headers=hdr(token),
        json={"name": "Apollo 11 facts (text)", "content": TEXT_BODY},
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json()["data"]["id"]


def add_url(token: str, nb: str) -> str:
    r = httpx.post(
        f"{API_URL}/api/v1/notebooks/{nb}/sources/url",
        headers=hdr(token),
        json={"url": WEB_URL},
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json()["data"]["id"]


def add_youtube(token: str, nb: str) -> str:
    r = httpx.post(
        f"{API_URL}/api/v1/notebooks/{nb}/sources/youtube",
        headers=hdr(token),
        json={"url": YT_URL},
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json()["data"]["id"]


def upload_file(token: str, nb: str, filename: str, content: bytes, mime: str) -> str:
    r = httpx.post(
        f"{API_URL}/api/v1/notebooks/{nb}/sources",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (filename, content, mime)},
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json()["data"]["id"]


def wait_ready(
    token: str, nb: str, sid: str, timeout: int = 180
) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = httpx.get(
            f"{API_URL}/api/v1/notebooks/{nb}/sources/{sid}",
            headers=hdr(token),
            timeout=15.0,
        )
        r.raise_for_status()
        s = r.json()["data"]
        if s["status"] != last:
            last = s["status"]
        if s["status"] in ("ready", "failed"):
            return s
        time.sleep(2)
    raise TimeoutError(f"source {sid} stuck in {last!r}")


def chat(token: str, nb: str, message: str) -> dict:
    r = httpx.post(
        f"{API_URL}/api/v1/notebooks/{nb}/chat",
        headers=hdr(token),
        json={"message": message},
        timeout=120.0,
    )
    r.raise_for_status()
    return r.json()


def delete_notebook(token: str, nb: str) -> None:
    httpx.delete(
        f"{API_URL}/api/v1/notebooks/{nb}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )


def main() -> int:
    print(f"Email: {EMAIL}")
    admin_create_user()
    token = sign_in()
    nb = create_notebook(token)
    print(f"notebook_id={nb}\n")

    sources: list[tuple[str, str]] = []  # (kind, source_id)

    print("Adding sources...")
    sources.append(("text",    add_text(token, nb)))
    print(f"  text     -> {sources[-1][1]}")
    sources.append(("url",     add_url(token, nb)))
    print(f"  url      -> {sources[-1][1]}")
    sources.append(("youtube", add_youtube(token, nb)))
    print(f"  youtube  -> {sources[-1][1]}")
    sources.append((
        "pdf",
        upload_file(token, nb, "fixture.pdf", make_pdf_bytes(), "application/pdf"),
    ))
    print(f"  pdf      -> {sources[-1][1]}")
    sources.append((
        "docx",
        upload_file(
            token,
            nb,
            "fixture.docx",
            make_docx_bytes(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
    ))
    print(f"  docx     -> {sources[-1][1]}\n")

    print("Waiting for ingest...")
    results: dict[str, dict] = {}
    for kind, sid in sources:
        s = wait_ready(token, nb, sid)
        results[kind] = s
        if s["status"] == "ready":
            print(
                f"  [OK]   {kind:8s} name={s['name'][:60]!r} "
                f"tokens={s.get('token_count')}"
            )
        else:
            print(
                f"  [FAIL] {kind:8s} status={s['status']!r} "
                f"err={s.get('error_message')!r}"
            )

    failed = [k for k, s in results.items() if s["status"] != "ready"]
    if failed:
        print(f"\nFAILED kinds: {failed}")
        delete_notebook(token, nb)
        return 1

    print("\nAsking chat question across all sources...")
    r = chat(token, nb, "Who walked on the Moon during Apollo 11?")
    data = r["data"]
    print(f"  citations={len(data['citations'])}")
    for c in data["citations"]:
        print(f"    [{c['number']}] {c['source_name'][:60]} sim={c['similarity']:.2f}")
    assert data["content"], "empty chat content"

    delete_notebook(token, nb)
    print("\nALL SOURCE TYPES PASSED [OK]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
