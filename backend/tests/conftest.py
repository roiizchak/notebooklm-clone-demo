"""Pytest fixtures: env stubbing, mocked services, FastAPI test client."""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _stub_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide deterministic env vars so `Settings()` instantiates."""
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "test-anon-key")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("DEBUG", "true")

    # Reset Settings cache so the new env is picked up.
    from app.config import get_settings

    get_settings.cache_clear()


# ---------- Supabase mock ----------


class _Tbl:
    """In-memory stub that records the chained call sequence and returns
    deterministic results from a per-test dict."""

    def __init__(self, name: str, parent: "FakeSupabase") -> None:
        self._name = name
        self._parent = parent
        self._chain: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, attr: str):
        def _record(*args: Any, **kwargs: Any) -> "_Tbl":
            self._chain.append((attr, args, kwargs))
            return self

        return _record

    def execute(self) -> Any:
        self._parent.calls.append((self._name, self._chain))
        # Programmable response. A plain function/lambda is treated as a
        # response factory; a MagicMock (which is also callable) is used
        # as-is so tests can pass `MagicMock(data=[...])` directly.
        result = self._parent.responses.get(self._name, MagicMock(data=[]))
        if callable(result) and not isinstance(result, MagicMock):
            data = result(self._chain)
            return MagicMock(data=data)
        return result


class FakeSupabase:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[tuple[str, tuple, dict]]]] = []
        self.responses: dict[str, Any] = {}
        self.storage = MagicMock()
        self.storage.from_.return_value.upload.return_value = None
        self.storage.from_.return_value.remove.return_value = None
        self.rpc = MagicMock()

    def table(self, name: str) -> _Tbl:
        return _Tbl(name, self)


@pytest.fixture
def fake_supabase(monkeypatch: pytest.MonkeyPatch) -> FakeSupabase:
    fake = FakeSupabase()
    from app.services import supabase_client

    monkeypatch.setattr(supabase_client, "get_supabase", lambda: fake)

    # Patch the already-imported references in router/services modules.
    import app.routers.audio as audio_mod
    import app.routers.chat as chat_mod
    import app.routers.notebooks as notebooks_mod
    import app.routers.notes as notes_mod
    import app.routers.profile as profile_mod
    import app.routers.research as research_mod
    import app.routers.sources as sources_mod
    import app.routers.studies as studies_mod
    import app.services.audio as audio_svc_mod
    import app.services.rag as rag_mod
    import app.services.research as research_svc_mod
    import app.services.usage as usage_mod
    import app.services.ingestion as ingestion_mod

    for mod in (
        audio_mod,
        chat_mod,
        notebooks_mod,
        notes_mod,
        profile_mod,
        research_mod,
        sources_mod,
        studies_mod,
        audio_svc_mod,
        rag_mod,
        research_svc_mod,
        usage_mod,
        ingestion_mod,
    ):
        monkeypatch.setattr(mod, "get_supabase", lambda fake=fake: fake)
    return fake


# ---------- Auth bypass ----------


@pytest.fixture
def auth_user_id() -> str:
    return "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def app_client(fake_supabase, auth_user_id, monkeypatch: pytest.MonkeyPatch):
    """Returns a TestClient with `get_current_user` overridden."""
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.services.auth import AuthUser, get_current_user

    app = create_app()

    def _user_override() -> AuthUser:
        return AuthUser(user_id=auth_user_id, email="test@example.com")

    app.dependency_overrides[get_current_user] = _user_override
    return TestClient(app)
