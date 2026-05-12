"""Supabase service-role client.

Backend uses the service-role key to bypass RLS for cross-row operations
(e.g. resolving JWT to user, writing usage_logs). Application code MUST
still filter by user_id explicitly on every query (defense-in-depth).

A new client is created per OS thread because the underlying sync httpx
connection pool is not safe to share across threads on Windows: concurrent
BackgroundTasks each running their own asyncio loop would race the HTTP/2
multiplexer and yield WinError 10035 / ReadError. Thread-local storage
gives each thread its own pool with negligible per-call overhead.
"""

from __future__ import annotations

import threading

from supabase import Client, create_client

from app.config import get_settings

_local = threading.local()


def get_supabase() -> Client:
    client = getattr(_local, "client", None)
    if client is None:
        settings = get_settings()
        client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
        )
        _local.client = client
    return client
