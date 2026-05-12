"""Client-facing config: caps, feature flags. Unauthenticated."""

from fastapi import APIRouter

from app.routers.sources import MAX_FILE_BYTES

router = APIRouter(prefix="/api/v1", tags=["config"])


@router.get("/config")
async def get_public_config() -> dict:
    return {"max_file_bytes": MAX_FILE_BYTES}
