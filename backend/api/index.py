"""Vercel Python entry point.

Vercel's `@vercel/python` runtime expects a top-level `app` (FastAPI / ASGI).
"""

import sys
from pathlib import Path

# Ensure parent dir (the backend project root) is on sys.path so
# `from app.main import app` resolves both locally and on Vercel.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from app.main import app  # noqa: E402

__all__ = ["app"]
