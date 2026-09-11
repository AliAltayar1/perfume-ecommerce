from typing import List, Union
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Project metadata
    PROJECT_NAME: str = "Perfume & Personal Care E-Commerce API"
    API_V1_STR: str = "/api/v1"
    DEBUG: bool = True
    ENVIRONMENT: str = "development"

    # Security & JWT
    SECRET_KEY: str = "change-this-to-a-secure-random-secret-key-in-production-min-32-chars"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15  # Short-lived (15 minutes)
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7      # Long-lived (7 days)

    # Cookie settings
    COOKIE_SECURE: bool = False  # Set to True in HTTPS production
    COOKIE_SAMESITE: str = "lax"  # "lax", "strict", or "none"

    # PostgreSQL Database
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "perfume_ecommerce"
    DATABASE_URL: str | None = None
    DB_ECHO: bool = False

    # CORS (Must be explicit origins when allow_credentials=True)
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            if v.startswith("[") and v.endswith("]"):
                import json
                try:
                    origins = json.loads(v)
                except Exception:
                    origins = [i.strip(" '\"") for i in v.strip("[]").split(",") if i.strip(" '\"")]
            else:
                origins = [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, list):
            origins = v
        else:
            raise ValueError(f"Invalid CORS format: {v}")

        # Normalize: strip trailing slashes (browser origin headers never include trailing slash)
        cleaned_origins = [str(o).rstrip("/") for o in origins]

        # Disallow wildcard when credentials are enabled
        if "*" in cleaned_origins:
            raise ValueError("Wildcard '*' origin is forbidden when allow_credentials=True")
        return cleaned_origins

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    @model_validator(mode="after")
    def validate_production_invariants(self) -> "Settings":
        if self.is_production:
            if self.SECRET_KEY == "change-this-to-a-secure-random-secret-key-in-production-min-32-chars":
                raise ValueError(
                    "CRITICAL: Default placeholder SECRET_KEY detected in production mode! "
                    "Set a unique, cryptographically secure SECRET_KEY in production."
                )
            if len(self.SECRET_KEY) < 32:
                raise ValueError("SECRET_KEY must be at least 32 characters in production.")
            if self.DEBUG:
                raise ValueError("DEBUG mode must be set to False in production.")
        return self

    @property
    def async_database_url(self) -> str:
        """
        Returns an asyncpg PostgreSQL connection URL.
        """
        if self.DATABASE_URL:
            if self.DATABASE_URL.startswith("postgresql://"):
                return self.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
            return self.DATABASE_URL
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()
