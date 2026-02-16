from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@postgres:5432/mh"
    mcp_base_url: str = "http://mcp:7000"
    frontend_url: str = "http://localhost:3000"
    nominatim_base_url: str = "https://nominatim.openstreetmap.org"
    overpass_base_url: str = "https://overpass-api.de"
    therapist_search_enabled: bool = True
    therapist_search_user_agent: str = "mh-skills-coach/0.1 (dev)"
    therapist_search_radius_km_default: int = 10
    therapist_search_limit: int = 10
    demo_mode: bool = False
    dev_mode: bool = False
    llm_provider: Literal["ollama", "openai", "mock"] = "ollama"
    embed_provider: Literal["ollama", "openai", "mock"] = "ollama"
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "gemma2:2b"
    ollama_embed_model: str = "nomic-embed-text"
    openai_api_key: str | None = None
    openai_chat_model: str = "gpt-4o-mini"
    openai_embed_model: str = "text-embedding-3-small"
    embedding_dim: int | None = None
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_price_id: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"
    session_cookie_name: str = "mh_session"
    cookie_secure: bool = False
    cookie_samesite: str = "lax"  # "lax" for localhost, "none" for tunnel/https

    # LangSmith tracing (Week 1)
    langsmith_api_key: str | None = None
    langchain_tracing_v2: str = "false"
    langchain_project: str = "mh-skills-coach"

    # Structured logging (Week 1)
    log_level: str = "INFO"
    log_format: str = "json"  # "json" for production, "text" for local dev

    # Rate limiting (Week 2)
    rate_limit_chat_requests: int = 10   # max requests per window
    rate_limit_window_seconds: int = 60  # rolling window in seconds

    # Resilience (Week 2)
    llm_timeout_seconds: float = 30.0   # timeout for all LLM calls
    llm_max_retries: int = 3            # tenacity retry attempts

    # Conversation memory
    conversation_history_max_turns: int = 10  # max user+assistant turn pairs kept per session


settings = Settings()
