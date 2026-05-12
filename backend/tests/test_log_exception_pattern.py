"""B-COR-06: every bare `except Exception:` must either log via .exception()
(preserves traceback) or carry a `# noqa: BLE001 — <reason>` comment justifying
why a broad catch is correct (fire-and-forget retry, best-effort cleanup, etc)."""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]  # backend/
SCAN_DIRS = [REPO_ROOT / "app" / "routers", REPO_ROOT / "app" / "services"]


def _scan_file(p: Path) -> list[str]:
    text = p.read_text(encoding="utf-8")
    offenders: list[str] = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not re.search(r"except\s+Exception\b", line):
            continue
        # Capture this line + the next 8 indented lines as the block.
        block_lines = [line]
        for j in range(i + 1, min(i + 9, len(lines))):
            if lines[j].strip() == "":
                continue
            if not lines[j].startswith(" "):
                break
            block_lines.append(lines[j])
        block = "\n".join(block_lines)

        if ".exception(" in block:
            continue
        if "# noqa: BLE001" in line or "# noqa: BLE001" in block:
            continue
        offenders.append(f"{p}:{i + 1}: {line.strip()}")
    return offenders


def test_bare_excepts_log_with_traceback_or_noqa() -> None:
    offenders: list[str] = []
    for root in SCAN_DIRS:
        for f in root.rglob("*.py"):
            offenders.extend(_scan_file(f))
    assert not offenders, (
        "bare `except Exception` must use .exception() OR carry "
        "`# noqa: BLE001 — <reason>`:\n" + "\n".join(offenders)
    )
