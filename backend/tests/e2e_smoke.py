"""End-to-end smoke test against a real Supabase project + Gemini.

Steps:
  1. Use Supabase Admin API to create a pre-confirmed user.
  2. Sign in via password to obtain a user JWT.
  3. Call backend /api/v1/notebooks (create + list).
  4. Add a text source.
  5. Poll until source.status == 'ready'.
  6. Send a chat message; assert content + at least one citation.
  7. Clean up: delete notebook (cascades sources/chunks/messages).

Usage:
    python tests/e2e_smoke.py
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv

# Load env from backend/.env explicitly.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SERVICE_ROLE = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
ANON_KEY = os.environ["SUPABASE_ANON_KEY"]
API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000")

EMAIL = f"smoke+{uuid.uuid4().hex[:10]}@example.test"
PASSWORD = "SmokeTest123!"

# Long enough to force chunking into multiple pieces (>800 tokens / chunk).
_PARAGRAPH = (
    "The Apollo 11 mission landed humans on the Moon for the first time on July 20, 1969. "
    "Neil Armstrong was the first person to step onto the lunar surface, followed by Buzz Aldrin. "
    "Michael Collins remained in the command module orbiting the Moon. "
    "The mission's main goal was to perform a crewed lunar landing and return safely to Earth, "
    "fulfilling President John F. Kennedy's national goal set in 1961. "
    "The Saturn V rocket carried the Apollo 11 spacecraft from Kennedy Space Center. "
    "Armstrong and Aldrin spent about two and a quarter hours together outside the spacecraft. "
    "They collected 21.5 kilograms of lunar material to bring back to Earth. "
    "The astronauts planted the United States flag on the Moon's surface. "
    "They left behind a plaque reading 'We came in peace for all mankind'. "
    "The mission was watched live on television by an estimated 650 million people. "
    "Apollo 11 effectively ended the Space Race between the United States and the Soviet Union. "
)
SAMPLE_TEXT = _PARAGRAPH * 6  # ~6 chunks at ~800 tokens each.


def admin_create_user() -> str:
    print(f"[1/7] Creating user {EMAIL} via admin API…")
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
    user = r.json()
    print(f"      user_id={user['id']}")
    return user["id"]


def sign_in() -> str:
    print(f"[2/7] Signing in to obtain JWT…")
    r = httpx.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        headers={"apikey": ANON_KEY, "Content-Type": "application/json"},
        json={"email": EMAIL, "password": PASSWORD},
        timeout=30.0,
    )
    r.raise_for_status()
    token = r.json()["access_token"]
    print(f"      access_token len={len(token)}")
    return token


def hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def create_notebook(token: str) -> str:
    print(f"[3/7] Creating notebook…")
    r = httpx.post(
        f"{API_URL}/api/v1/notebooks",
        headers=hdr(token),
        json={"name": "Apollo 11 Smoke Test", "emoji": "🚀"},
        timeout=30.0,
    )
    r.raise_for_status()
    nb_id = r.json()["data"]["id"]
    print(f"      notebook_id={nb_id}")
    return nb_id


def add_text_source(token: str, nb_id: str) -> str:
    print(f"[4/7] Adding text source…")
    r = httpx.post(
        f"{API_URL}/api/v1/notebooks/{nb_id}/sources/text",
        headers=hdr(token),
        json={"name": "Apollo 11 facts", "content": SAMPLE_TEXT},
        timeout=30.0,
    )
    r.raise_for_status()
    sid = r.json()["data"]["id"]
    print(f"      source_id={sid}")
    return sid


def wait_for_source_ready(token: str, nb_id: str, sid: str, timeout: int = 90) -> dict:
    print(f"[5/7] Waiting for source ingest to complete…")
    deadline = time.time() + timeout
    last_status = None
    while time.time() < deadline:
        r = httpx.get(
            f"{API_URL}/api/v1/notebooks/{nb_id}/sources/{sid}",
            headers=hdr(token),
            timeout=15.0,
        )
        r.raise_for_status()
        s = r.json()["data"]
        if s["status"] != last_status:
            print(f"      status={s['status']} token_count={s.get('token_count')}")
            last_status = s["status"]
        if s["status"] == "ready":
            return s
        if s["status"] == "failed":
            raise RuntimeError(f"Ingest failed: {s.get('error_message')}")
        time.sleep(2)
    raise TimeoutError(f"Source did not reach 'ready' within {timeout}s")


def chat(token: str, nb_id: str, message: str) -> dict:
    print(f"[6/7] Sending chat message: {message!r}")
    r = httpx.post(
        f"{API_URL}/api/v1/notebooks/{nb_id}/chat",
        headers=hdr(token),
        json={"message": message},
        timeout=60.0,
    )
    r.raise_for_status()
    return r.json()


def delete_notebook(token: str, nb_id: str) -> None:
    print(f"[7/7] Cleaning up notebook…")
    r = httpx.delete(
        f"{API_URL}/api/v1/notebooks/{nb_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )
    r.raise_for_status()


def main() -> int:
    try:
        admin_create_user()
        token = sign_in()
        nb_id = create_notebook(token)
        sid = add_text_source(token, nb_id)
        ready = wait_for_source_ready(token, nb_id, sid)
        chunks = ready.get("token_count")
        print(f"      ingest done, total_tokens={chunks}, summary={ready.get('source_guide')}")

        result = chat(token, nb_id, "Who walked on the Moon during Apollo 11?")
        data = result["data"]
        print(f"      response: {data['content'][:200]}…")
        print(f"      citations: {len(data['citations'])}")
        for c in data["citations"]:
            print(f"        [{c['number']}] {c['source_name']} similarity={c['similarity']:.3f}")
        usage = result.get("usage", {})
        print(f"      cost=${usage.get('cost_usd')} model={usage.get('model_used')}")

        assert data["content"], "empty response content"
        assert len(data["citations"]) >= 1, "expected at least one citation"

        print("\nSMOKE TEST PASSED [OK]")

        delete_notebook(token, nb_id)
        return 0
    except Exception as e:
        print(f"\nSMOKE TEST FAILED [FAIL] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
