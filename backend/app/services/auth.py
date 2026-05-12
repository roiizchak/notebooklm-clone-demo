"""JWT authentication via Supabase JWKS.

Verifies Supabase-issued tokens by fetching the project's public JWKS,
caching it for 1h, and validating the RS256/ES256 signature on every
request. Replaces the unsafe `verify_signature=False` pattern from the
original spec.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt
from jose.exceptions import JWTError

from app.config import Settings, get_settings

# 1h JWKS cache TTL.
_JWKS_TTL_SECONDS = 3600

_security = HTTPBearer(auto_error=False)


@dataclass
class _JwksCache:
    keys: dict[str, Any] | None = None
    fetched_at: float = 0.0


_cache = _JwksCache()


@dataclass
class AuthUser:
    user_id: str
    email: str | None


def _jwks_url(settings: Settings) -> str:
    return f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"


def _fetch_jwks(settings: Settings, *, force: bool = False) -> dict[str, Any]:
    now = time.time()
    if (
        not force
        and _cache.keys is not None
        and (now - _cache.fetched_at) < _JWKS_TTL_SECONDS
    ):
        return _cache.keys

    resp = httpx.get(_jwks_url(settings), timeout=10.0)
    resp.raise_for_status()
    _cache.keys = resp.json()
    _cache.fetched_at = now
    return _cache.keys


def _decode(token: str, settings: Settings, *, force_refresh: bool = False) -> dict[str, Any]:
    jwks = _fetch_jwks(settings, force=force_refresh)
    return jwt.decode(
        token,
        jwks,
        algorithms=["RS256", "ES256"],
        audience="authenticated",
        options={"verify_signature": True, "verify_aud": True, "verify_exp": True},
    )


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
    settings: Settings = Depends(get_settings),
) -> AuthUser:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Authentication required")

    token = credentials.credentials

    try:
        payload = _decode(token, settings)
    except JWTError:
        # On signature failure, refresh JWKS once and retry (key rotation).
        try:
            payload = _decode(token, settings, force_refresh=True)
        except JWTError as e:
            raise HTTPException(status_code=401, detail="Invalid token") from e
    except httpx.HTTPError as e:
        raise HTTPException(status_code=503, detail="Auth backend unavailable") from e

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Invalid token claims")

    return AuthUser(user_id=sub, email=payload.get("email"))
