"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Supabase
    supabase_url: str = Field(..., description="Supabase project URL")
    supabase_anon_key: str = Field(..., description="Supabase anon (public) key")
    supabase_service_role_key: str = Field(..., description="Supabase service role key (backend only)")

    # Gemini
    google_api_key: str = Field(..., description="Google AI Studio API key")

    # App
    app_name: str = "NotebookLM Reimagined"
    debug: bool = False

    # CORS
    cors_origins: str = "http://localhost:3000"

    # Phase 3.a deep research
    research_daily_limit_per_user: int = Field(
        default=10,
        description="Max successful + in-flight research reports per user per 24h",
    )

    # Per-user daily caps on paid Gemini endpoints (F1 cost guardrail).
    chat_daily_limit_per_user: int = Field(
        default=300,
        description="Max chat (mode='chat') generations per user per 24h",
    )
    studies_daily_limit_per_user: int = Field(
        default=50,
        description="Max study-material generations per user per 24h",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def supabase_project_ref(self) -> str:
        # Extract `xxx` from `https://xxx.supabase.co`
        host = self.supabase_url.replace("https://", "").replace("http://", "")
        return host.split(".")[0]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
