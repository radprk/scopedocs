"""Application configuration using Pydantic Settings."""

import os
from typing import List, Optional
from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Database
    database_url: str = "postgresql://localhost:5432/scopedocs"
    
    # Security
    jwt_secret: str = "dev-secret-change-in-production"
    jwt_expiration_hours: int = 24
    encryption_key: Optional[str] = None  # Falls back to jwt_secret if not set
    
    # CORS - comma-separated list of allowed origins
    cors_origins: str = "http://localhost:3000,http://localhost:8000"
    
    # Rate limiting
    rate_limit_requests: int = 100  # requests per window
    rate_limit_window: int = 60  # seconds
    
    # OAuth
    github_client_id: Optional[str] = None
    github_client_secret: Optional[str] = None
    slack_client_id: Optional[str] = None
    slack_client_secret: Optional[str] = None
    linear_client_id: Optional[str] = None
    linear_client_secret: Optional[str] = None
    
    # AI
    together_api_key: Optional[str] = None
    
    # Redis (for OAuth state, rate limiting)
    redis_url: Optional[str] = None  # Falls back to database if not set
    
    # Environment
    environment: str = "development"
    debug: bool = False
    
    @field_validator('cors_origins', mode='before')
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, list):
            return ','.join(v)
        return v
    
    def get_cors_origins_list(self) -> List[str]:
        """Get CORS origins as a list."""
        return [o.strip() for o in self.cors_origins.split(',') if o.strip()]
    
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.environment.lower() == "production"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        # Map environment variables
        env_prefix = ""


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Convenience function for backwards compatibility
def get_database_url() -> str:
    """Get database URL from settings."""
    settings = get_settings()
    return os.environ.get("POSTGRES_DSN") or os.environ.get("DATABASE_URL") or settings.database_url
