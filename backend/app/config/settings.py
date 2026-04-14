from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    mongodb_url: str = "mongodb://localhost:27017"
    mongodb_database_name: str = "jarvis_db"
    mongodb_fallback_url: str = "mongodb://localhost:27017"
    mongodb_server_selection_timeout_ms: int = 5000
    mongodb_connect_timeout_ms: int = 10000
    mongodb_socket_timeout_ms: int = 20000
    mongodb_allow_start_without_connection: bool = True
    mongodb_fallback_to_local: bool = True
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    gemini_embedding_model: str = "models/embedding-001"
    embedding_dimensions: int = 1536
    cors_origins: str = "http://localhost:5173"
    jwt_secret_key: str = "replace_with_a_long_secret"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440
    analysis_fast_mode: bool = True
    analysis_llm_refinement: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
