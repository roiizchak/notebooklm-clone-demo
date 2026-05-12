"""End-to-end Phase 3.a deep research test against real Supabase + Gemini.

Exercises the full pipeline:
  - Create user + notebook
  - Add 3 small text sources covering a domain
  - POST /chat with mode='research'
  - Poll GET /research/{id} until status in {ready, partial, failed}
  - Assert non-empty content_md, >=3 sections, >=5 citations resolving to real chunks
  - Tear down via notebook DELETE

Gated by RUN_RESEARCH=1 env var (real Gemini calls, ~$0.05-$0.10).

Usage:
    RUN_RESEARCH=1 ./.venv/Scripts/python.exe tests/e2e_phase3a.py
"""

from __future__ import annotations

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
RUN_RESEARCH = os.environ.get("RUN_RESEARCH") == "1"

EMAIL = f"phase3a+{uuid.uuid4().hex[:10]}@gmail.com"
PASSWORD = "Phase3aTest123!"

# Three small, complementary text sources so deep research has material to
# distribute across sections.
SOURCES: list[tuple[str, str]] = [
    (
        "Apollo Background",
        "The Apollo program was a series of NASA missions in the 1960s and "
        "early 1970s. Apollo 11, launched July 16 1969, was the first to land "
        "humans on the Moon. Neil Armstrong and Buzz Aldrin walked on the "
        "lunar surface. Michael Collins remained in lunar orbit aboard "
        "Columbia. The mission returned 21.5 kg of lunar samples.",
    ),
    (
        "Saturn V Rocket",
        "The Saturn V was a three-stage liquid-fueled super heavy-lift launch "
        "vehicle developed by NASA under the Apollo program. It stood 110 m "
        "tall, weighed 2.8 million kg fueled, and produced 34.5 million "
        "newtons of thrust at liftoff. The first stage used five F-1 engines "
        "burning RP-1 and liquid oxygen. The third stage placed the Apollo "
        "spacecraft on a translunar trajectory.",
    ),
    (
        "Lunar Module",
        "The Apollo Lunar Module (LM) was the two-stage spacecraft that "
        "landed astronauts on the Moon and returned them to lunar orbit. "
        "The descent stage carried the landing engine, propellant tanks, and "
        "scientific equipment. The ascent stage carried the crew, life "
        "support, and a single ascent engine. Apollo 11's LM was Eagle.",
    ),
]


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
        json={"name": "Phase 3.a Research Test", "emoji": "🔭"},
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json()["data"]["id"]


def add_text_source(token: str, nb_id: str, name: str, content: str) -> str:
    print(f"[source] adding {name!r}...")
    r = httpx.post(
        f"{API_URL}/api/v1/notebooks/{nb_id}/sources/text",
        headers=hdr(token),
        json={"name": name, "content": content},
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json()["data"]["id"]


def wait_source_ready(token: str, nb_id: str, sid: str, timeout: int = 120) -> None:
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
            print(f"        source {sid[:8]} status={s['status']}")
            last_status = s["status"]
        if s["status"] == "ready":
            return
        if s["status"] == "failed":
            raise RuntimeError(f"Source ingest failed: {s.get('error_message')}")
        time.sleep(2)
    raise TimeoutError(f"Source {sid} did not become ready in {timeout}s")


def start_research(token: str, nb_id: str, question: str) -> str:
    print(f"[research] posting question: {question!r}")
    r = httpx.post(
        f"{API_URL}/api/v1/notebooks/{nb_id}/chat",
        headers=hdr(token),
        json={"message": question, "mode": "research"},
        timeout=30.0,
    )
    if r.status_code != 202:
        raise RuntimeError(f"Expected 202 on research start, got {r.status_code}: {r.text}")
    data = r.json()["data"]
    print(f"        report_id={data['research_report_id']} status={data['status']}")
    return data["research_report_id"]


def wait_research_complete(
    token: str, nb_id: str, report_id: str, timeout: int = 240
) -> dict:
    print("[research] polling for completion...")
    deadline = time.time() + timeout
    last_status = None
    last_sections = -1
    while time.time() < deadline:
        r = httpx.get(
            f"{API_URL}/api/v1/notebooks/{nb_id}/research/{report_id}",
            headers=hdr(token),
            timeout=15.0,
        )
        r.raise_for_status()
        report = r.json()["data"]
        status = report["status"]
        sections = report.get("sections") or []
        n_ready = sum(1 for s in sections if s.get("status") == "ready")
        if status != last_status or n_ready != last_sections:
            print(f"        status={status} sections_ready={n_ready}/{len(sections)}")
            last_status, last_sections = status, n_ready
        if status in ("ready", "partial"):
            return report
        if status == "failed":
            raise RuntimeError(f"Research failed: {report.get('error')}")
        time.sleep(3)
    raise TimeoutError(f"Research did not complete in {timeout}s")


def cleanup_notebook(token: str, nb_id: str) -> None:
    try:
        httpx.delete(
            f"{API_URL}/api/v1/notebooks/{nb_id}",
            headers=hdr(token),
            timeout=30.0,
        )
    except Exception as e:
        print(f"[cleanup] notebook delete failed (non-fatal): {e}")


def main() -> int:
    if not RUN_RESEARCH:
        print("Skipping deep research e2e (set RUN_RESEARCH=1 to enable, costs ~$0.05-$0.10).")
        return 0

    user_id = admin_create_user()
    token = sign_in()
    nb_id = create_notebook(token)

    try:
        # Add sources sequentially and wait for each to ingest.
        for name, content in SOURCES:
            sid = add_text_source(token, nb_id, name, content)
            wait_source_ready(token, nb_id, sid)

        question = (
            "Give me a multi-section overview of the Apollo 11 mission: the "
            "Saturn V launch vehicle, the Lunar Module landing, and the overall "
            "mission context."
        )

        report_id = start_research(token, nb_id, question)
        t0 = time.time()
        report = wait_research_complete(token, nb_id, report_id)
        elapsed = time.time() - t0
        print(f"[research] completed in {elapsed:.1f}s, status={report['status']}")

        # Assertions.
        content_md = report.get("content_md") or ""
        sections = report.get("sections") or []
        citations = report.get("citations") or []
        cost = report.get("cost_usd")

        assert content_md.strip(), "expected non-empty content_md"
        assert "## TL;DR" in content_md or "TL;DR" in content_md, (
            "expected TL;DR section in stitched report"
        )
        ready_sections = [s for s in sections if s.get("status") == "ready"]
        assert len(ready_sections) >= 3, (
            f"expected >= 3 ready sections, got {len(ready_sections)} "
            f"({[s.get('title') for s in sections]})"
        )
        assert len(citations) >= 5, (
            f"expected >= 5 global citations, got {len(citations)}"
        )
        # All citation numbers in content_md must resolve.
        import re
        cited_nums = {int(m) for m in re.findall(r"\[(\d+)\]", content_md)}
        valid_nums = {c["number"] for c in citations}
        unresolved = cited_nums - valid_nums
        assert not unresolved, f"unresolved citation numbers in stitched content: {unresolved}"

        # Cost guardrail.
        assert cost is not None and cost <= 0.20, (
            f"deep research cost too high: ${cost}"
        )

        print("[OK] all assertions passed")
        print(f"     elapsed: {elapsed:.1f}s")
        print(f"     sections: {len(ready_sections)} ready / {len(sections)} total")
        print(f"     citations: {len(citations)}")
        print(f"     cost: ${cost:.4f}")
        print(f"     content_md preview: {content_md[:200]!r}")
        return 0
    finally:
        cleanup_notebook(token, nb_id)


if __name__ == "__main__":
    sys.exit(main())
