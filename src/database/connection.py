"""Database connection management."""

from typing import Optional

import asyncpg

from src.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)

_database_pool: Optional[asyncpg.Pool] = None


async def get_database() -> asyncpg.Pool:
    """Get or create database connection pool."""
    global _database_pool
    
    if not settings.database_url:
        raise ValueError("DATABASE_URL is not configured")
    
    if _database_pool is None:
        try:
            _database_pool = await asyncpg.create_pool(
                settings.database_url,
                min_size=1,
                max_size=settings.database_pool_size,
                command_timeout=settings.database_pool_timeout,
                server_settings={
                    'application_name': settings.app_name,
                    'jit': 'off',
                }
            )
            
            # Test connection
            async with _database_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            
            logger.info(
                "Database pool initialized",
                pool_size=settings.database_pool_size,
                timeout=settings.database_pool_timeout,
            )
            
        except Exception as e:
            logger.error("Failed to initialize database pool", error=str(e))
            raise
    
    return _database_pool


async def close_database() -> None:
    """Close database connection pool."""
    global _database_pool
    
    if _database_pool:
        try:
            await _database_pool.close()
            _database_pool = None
            logger.info("Database pool closed")
        except Exception as e:
            logger.error("Error closing database pool", error=str(e))