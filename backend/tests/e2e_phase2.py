"""End-to-end Phase 2 test against a real Supabase project + Gemini.

Exercises the Phase 2 surface:
  - Direct-to-Storage upload via signed URL (PDF)
  - Source ingestion (existing pipeline triggered by upload-complete)
  - Study materials generation (flashcards / quiz / study_guide / faq)
  - Notes CRUD (written + saved-from-chat + pin/unpin/delete)
  - Audio overview generation (gemini-3.1-flash-tts-preview multi-speaker)

Set RUN_AUDIO=1 to include the audio generation step (costs ~$0.15-$0.30).
Otherwise audio is skipped.

Usage:
    python tests/e2e_phase2.py
    RUN_AUDIO=1 python tests/e2e_phase2.py
"""

from __future__ import annotations

import os
import struct
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
RUN_AUDIO = os.environ.get("RUN_AUDIO") == "1"

EMAIL = f"phase2+{uuid.uuid4().hex[:10]}@gmail.com"
PASSWORD = "Phase2Test123!"


def hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def admin_create_user() -> str:
    print(f"[setup] creating user {EMAIL}...")
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
    return r.json()["id"]


def sign_in() -> str:
    print("[setup] signing in...")
    r = httpx.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        headers={"apikey": ANON_KEY, "Content-Type": "application/json"},
        json={"email": EMAIL, "password": PASSWORD},
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def create_notebook(token: str) -> str:
    print("[setup] creating notebook...")
    r = httpx.post(
        f"{API_URL}/api/v1/notebooks",
        headers=hdr(token),
        json={"name": "Phase 2 Test", "emoji": "🧪"},
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json()["data"]["id"]


def make_tiny_pdf() -> bytes:
    """Generate a minimal valid PDF byte string with extractable text.

    Tiny single-page PDF with the text "Apollo 11 landed on the Moon in 1969."
    We use a hand-crafted PDF rather than a library to keep the test stack lean.
    """
    body = (
        b"%PDF-1.4\n"
        b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n"
        b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n"
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n"
        b"4 0 obj<< /Length 78 >>stream\n"
        b"BT /F1 14 Tf 72 720 Td (Apollo 11 landed on the Moon in 1969.) Tj ET\n"
        b"endstream\nendobj\n"
        b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n"
        b"xref\n0 6\n0000000000 65535 f \n"
        b"0000000010 00000 n \n0000000053 00000 n \n0000000102 00000 n \n"
        b"0000000202 00000 n \n0000000314 00000 n \n"
        b"trailer<< /Size 6 /Root 1 0 R >>\nstartxref\n381\n%%EOF\n"
    )
    return body


def upload_via_signed_url(token: str, nb_id: str, content: bytes, filename: str, mime: str) -> str:
    print(f"[upload] init -> put -> complete for {filename} ({len(content)} bytes)...")
    init = httpx.post(
        f"{API_URL}/api/v1/notebooks/{nb_id}/sources/upload-init",
        headers=hdr(token),
        json={"filename": filename, "mime_type": mime, "size": len(content)},
        timeout=30.0,
    )
    init.raise_for_status()
    data = init.json()["data"]
    print(f"        signed_url issued for source_id={data['source_id']}")

    put = httpx.put(
        data["signed_url"],
        content=content,
        headers={"Content-Type": mime},
        timeout=60.0,
    )
    put.raise_for_status()
    print(f"        PUT {put.status_code}")

    done = httpx.post(
        f"{API_URL}/api/v1/notebooks/{nb_id}/sources/upload-complete",
        headers=hdr(token),
        json={"source_id": data["source_id"]},
        timeout=30.0,
    )
    done.raise_for_status()
    return data["source_id"]


def wait_for_source_ready(token: str, nb_id: str, sid: str, timeout: int = 120) -> dict:
    print(f"[upload] waiting for ingest of {sid}...")
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = httpx.get(
            f"{API_URL}/api/v1/notebooks/{nb_id}/sources/{sid}",
            headers=hdr(token),
            timeout=15.0,
        )
        r.raise_for_status()
        s = r.json()["data"]
        if s["status"] != last:
            print(f"        status={s['status']}")
            last = s["status"]
        if s["status"] == "ready":
            return s
        if s["status"] == "failed":
            raise RuntimeError(f"Ingest failed: {s.get('error_message')}")
        time.sleep(2)
    raise TimeoutError(f"Source did not reach ready in {timeout}s")


def gen_study(token: str, nb_id: str, kind: str) -> dict:
    print(f"[study] generating {kind}...")
    r = httpx.post(
        f"{API_URL}/api/v1/notebooks/{nb_id}/studies/{kind}/generate",
        headers=hdr(token),
        timeout=120.0,
    )
    r.raise_for_status()
    return r.json()["data"]


def assert_shapes(studies: dict[str, dict]) -> None:
    fc = studies["flashcards"]["payload"]
    assert isinstance(fc.get("flashcards"), list) and len(fc["flashcards"]) >= 1
    assert "front" in fc["flashcards"][0] and "back" in fc["flashcards"][0]
    qz = studies["quiz"]["payload"]
    assert isinstance(qz.get("questions"), list) and len(qz["questions"]) >= 1
    q0 = qz["questions"][0]
    assert "q" in q0 and isinstance(q0.get("options"), list) and len(q0["options"]) == 4
    assert isinstance(q0.get("correct_index"), int) and 0 <= q0["correct_index"] < 4
    sg = studies["study_guide"]["payload"]
    assert sg.get("summary") or sg.get("key_concepts") or sg.get("objectives")
    fq = studies["faq"]["payload"]
    assert isinstance(fq.get("faqs"), list) and len(fq["faqs"]) >= 1


def chat_to_get_message_id(token: str, nb_id: str) -> str:
    print("[notes] sending chat to obtain a message id for save-from-chat...")
    r = httpx.post(
        f"{API_URL}/api/v1/notebooks/{nb_id}/chat",
        headers=hdr(token),
        json={"message": "Summarise in one sentence."},
        timeout=120.0,
    )
    r.raise_for_status()
    return r.json()["data"]["message_id"]


def notes_flow(token: str, nb_id: str) -> None:
    print("[notes] CRUD...")
    written = httpx.post(
        f"{API_URL}/api/v1/notebooks/{nb_id}/notes",
        headers=hdr(token),
        json={"type": "written", "title": "First note", "content": "Hello world"},
        timeout=15.0,
    )
    written.raise_for_status()
    n1 = written.json()["data"]
    assert n1["type"] == "written"

    msg_id = chat_to_get_message_id(token, nb_id)
    saved = httpx.post(
        f"{API_URL}/api/v1/notebooks/{nb_id}/notes",
        headers=hdr(token),
        json={
            "type": "saved_response",
            "content": "From chat",
            "original_message_id": msg_id,
        },
        timeout=15.0,
    )
    saved.raise_for_status()
    n2 = saved.json()["data"]
    assert n2["type"] == "saved_response"
    assert n2["original_message_id"] == msg_id

    pin = httpx.patch(
        f"{API_URL}/api/v1/notebooks/{nb_id}/notes/{n1['id']}",
        headers=hdr(token),
        json={"is_pinned": True},
        timeout=15.0,
    )
    pin.raise_for_status()

    listed = httpx.get(
        f"{API_URL}/api/v1/notebooks/{nb_id}/notes",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15.0,
    )
    listed.raise_for_status()
    rows = listed.json()["data"]
    assert any(r["id"] == n1["id"] and r["is_pinned"] for r in rows)
    assert rows[0]["is_pinned"] is True, "pinned note should sort first"

    rm = httpx.delete(
        f"{API_URL}/api/v1/notebooks/{nb_id}/notes/{n2['id']}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15.0,
    )
    rm.raise_for_status()
    print("        notes CRUD OK")


def audio_flow(token: str, nb_id: str) -> None:
    print("[audio] generating 5-minute overview (this may take ~60-180s)...")
    r = httpx.post(
        f"{API_URL}/api/v1/notebooks/{nb_id}/audio/generate",
        headers=hdr(token),
        json={"target_minutes": 5},
        timeout=30.0,
    )
    r.raise_for_status()
    aid = r.json()["data"]["id"]

    deadline = time.time() + 240
    last = None
    while time.time() < deadline:
        s = httpx.get(
            f"{API_URL}/api/v1/notebooks/{nb_id}/audio/{aid}",
            headers=hdr(token),
            timeout=15.0,
        )
        s.raise_for_status()
        row = s.json()["data"]
        if row["status"] != last:
            print(f"        status={row['status']}")
            last = row["status"]
        if row["status"] == "ready":
            url = httpx.get(
                f"{API_URL}/api/v1/notebooks/{nb_id}/audio/{aid}/url",
                headers=hdr(token),
                timeout=15.0,
            ).json()["data"]["signed_url"]
            head = httpx.get(url, headers={"Range": "bytes=0-43"}, timeout=15.0)
            assert head.status_code in (200, 206), f"unexpected GET status {head.status_code}"
            data = head.content
            assert data[:4] == b"RIFF" and data[8:12] == b"WAVE", "WAV header missing"
            print(f"        audio ready, duration={row['duration_seconds']}s, cost=${row.get('cost_usd')}")
            return
        if row["status"] == "failed":
            raise RuntimeError(f"audio gen failed: {row.get('error')}")
        time.sleep(5)
    raise TimeoutError("audio did not become ready in 240s")


def cleanup_notebook(token: str, nb_id: str) -> None:
    print("[cleanup] deleting notebook...")
    httpx.delete(
        f"{API_URL}/api/v1/notebooks/{nb_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    ).raise_for_status()


def main() -> int:
    try:
        admin_create_user()
        token = sign_in()
        nb_id = create_notebook(token)

        sid = upload_via_signed_url(
            token, nb_id, make_tiny_pdf(), "tiny.pdf", "application/pdf"
        )
        wait_for_source_ready(token, nb_id, sid)

        studies = {}
        for kind in ("flashcards", "quiz", "study_guide", "faq"):
            studies[kind] = gen_study(token, nb_id, kind)
        assert_shapes(studies)
        print("        study materials OK (counts:",
              len(studies["flashcards"]["payload"]["flashcards"]),
              "fc,",
              len(studies["quiz"]["payload"]["questions"]),
              "qz,",
              len(studies["faq"]["payload"]["faqs"]),
              "faqs)")

        notes_flow(token, nb_id)

        if RUN_AUDIO:
            audio_flow(token, nb_id)
        else:
            print("[audio] SKIPPED (set RUN_AUDIO=1 to include)")

        cleanup_notebook(token, nb_id)
        print("\nPHASE 2 E2E PASSED [OK]")
        return 0
    except Exception as e:
        print(f"\nPHASE 2 E2E FAILED [FAIL] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
