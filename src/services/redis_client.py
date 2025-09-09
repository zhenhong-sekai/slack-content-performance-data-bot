"""Redis client implementation."""

from typing import Optional

import redis.asyncio as redis
from redis.asyncio import Redis

from src.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)

_redis_client: Optional[Redis] = None


async def get_redis_client() -> Redis:
    """Get or create Redis client instance."""
    global _redis_client
    
    if _redis_client is None:
        try:
            # Parse Redis URL and create connection pool
            _redis_client = redis.from_url(
                settings.redis_url,
                password=settings.redis_password,
                max_connections=settings.redis_max_connections,
                retry_on_timeout=True,
                socket_connect_timeout=5,
                socket_keepalive=True,
                socket_keepalive_options={},
                health_check_interval=30,
            )
            
            # Test connection
            await _redis_client.ping()
            
            logger.info(
                "Redis client initialized",
                url=settings.redis_url.split('@')[-1],  # Hide credentials
                max_connections=settings.redis_max_connections,
            )
            
        except Exception as e:
            logger.error("Failed to initialize Redis client", error=str(e))
            raise
    
    return _redis_client


async def close_redis_connection() -> None:
    """Close Redis connection."""
    global _redis_client
    
    if _redis_client:
        try:
            await _redis_client.close()
            _redis_client = None
            logger.info("Redis connection closed")
        except Exception as e:
            logger.error("Error closing Redis connection", error=str(e))