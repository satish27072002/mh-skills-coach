from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@postgres:5432/mh"
    mcp_base_url: str = "http://mcp:7000"
    frontend_url: str = "http://localhost:3000"
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "gemma2:2b"
    ollama_embed_model: str = "nomic-embed-text"
    embedding_dim: int = 768
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_price_id: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"
    session_cookie_name: str = "mh_session"
    cookie_secure: bool = False


settings = Settings()
