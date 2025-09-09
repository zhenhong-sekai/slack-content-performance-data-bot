"""Application configuration management."""

from functools import lru_cache
from typing import Optional

from pydantic import Field, validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable support."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # Application
    app_name: str = Field(default="slack-data-query-bot")
    app_version: str = Field(default="0.1.0")
    debug: bool = Field(default=False)
    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")
    
    # Security (Optional - not needed for basic bot functionality)
    secret_key: str = Field(default="default-secret-key-for-dev")
    jwt_secret_key: str = Field(default="default-jwt-secret-key-for-dev")
    
    # Slack Configuration (Socket Mode)
    slack_bot_token: str = Field(min_length=10)
    slack_signing_secret: str = Field(min_length=10)
    slack_app_token: str = Field(min_length=10)  # Required for Socket Mode
    
    # OpenAI Configuration
    openai_api_key: str = Field(min_length=10)
    openai_base_url: str = Field(default="https://yunwu.ai/v1")
    openai_model: str = Field(default="gpt-4o")
    
    # MCP Server Configuration
    mcp_server_url: str = Field(default="http://localhost:3000")
    mcp_server_timeout: int = Field(default=30, ge=5, le=300)
    
    # Redis Configuration
    redis_url: str = Field(default="redis://localhost:6379/0")
    redis_password: Optional[str] = Field(default=None)
    redis_max_connections: int = Field(default=10, ge=1, le=100)
    
    # Database Configuration (Optional)
    database_url: Optional[str] = Field(default=None)
    database_pool_size: int = Field(default=10, ge=1, le=50)
    database_pool_timeout: int = Field(default=30, ge=5, le=300)
    
    # File Storage
    temp_file_path: str = Field(default="/tmp/slack_bot_files")
    max_file_size_mb: int = Field(default=50, ge=1, le=500)
    file_cleanup_hours: int = Field(default=1, ge=1, le=24)
    
    # Performance
    max_concurrent_queries: int = Field(default=10, ge=1, le=100)
    query_timeout_seconds: int = Field(default=60, ge=10, le=600)
    rate_limit_per_minute: int = Field(default=30, ge=1, le=1000)
    
    # Monitoring
    metrics_port: int = Field(default=8001, ge=1000, le=65535)
    health_check_timeout: int = Field(default=5, ge=1, le=60)
    
    # External Services
    prometheus_pushgateway_url: Optional[str] = Field(default=None)
    sentry_dsn: Optional[str] = Field(default=None)
    
    @validator("log_level")
    def validate_log_level(cls, v):
        """Validate log level is one of the standard levels."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"log_level must be one of: {valid_levels}")
        return v.upper()
    
    @validator("environment")
    def validate_environment(cls, v):
        """Validate environment is one of the expected values."""
        valid_envs = ["development", "staging", "production", "test"]
        if v.lower() not in valid_envs:
            raise ValueError(f"environment must be one of: {valid_envs}")
        return v.lower()
    
    @validator("slack_bot_token")
    def validate_slack_bot_token(cls, v):
        """Validate Slack bot token format."""
        if not v.startswith("xoxb-"):
            raise ValueError("slack_bot_token must start with 'xoxb-'")
        return v
    
    @validator("slack_app_token")
    def validate_slack_app_token(cls, v):
        """Validate Slack app token format."""
        if not v.startswith("xapp-"):
            raise ValueError("slack_app_token must start with 'xapp-'")
        return v
    
    @validator("openai_api_key")
    def validate_openai_api_key(cls, v):
        """Validate OpenAI API key format."""
        # Support both standard OpenAI keys (sk-) and custom API keys
        if len(v) < 10:
            raise ValueError("openai_api_key must be at least 10 characters long")
        return v
    
    @validator("redis_url")
    def validate_redis_url(cls, v):
        """Validate Redis URL format."""
        if not v.startswith(("redis://", "rediss://")):
            raise ValueError("redis_url must start with 'redis://' or 'rediss://'")
        return v
    
    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment == "production"
    
    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.environment == "development"
    
    @property
    def is_testing(self) -> bool:
        """Check if running in test environment."""
        return self.environment == "test"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Global settings instance
settings = get_settings()