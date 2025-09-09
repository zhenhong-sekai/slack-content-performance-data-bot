"""FastAPI application entry point."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.health import router as health_router
from src.api.middleware import (
    ErrorHandlerMiddleware,
    LoggingMiddleware,
    SecurityHeadersMiddleware,
)
from src.config import settings
from src.utils.logging import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting Slack Data Query Bot", version=settings.app_version)
    
    # Initialize services
    await startup_services()
    
    yield
    
    # Shutdown
    logger.info("Shutting down Slack Data Query Bot")
    await shutdown_services()


async def startup_services():
    """Initialize application services."""
    try:
        # Initialize Redis connection
        from src.services.redis_client import get_redis_client
        redis_client = await get_redis_client()
        await redis_client.ping()
        logger.info("Redis connection established")
        
        # Initialize database if configured
        if settings.database_url:
            from src.database.connection import get_database
            db = await get_database()
            logger.info("Database connection established")
        
        logger.info("All services initialized successfully")
    except Exception as e:
        logger.error("Failed to initialize services", error=str(e))
        raise


async def shutdown_services():
    """Clean up application services."""
    try:
        # Close Redis connection
        from src.services.redis_client import close_redis_connection
        await close_redis_connection()
        logger.info("Redis connection closed")
        
        # Close database connection if configured
        if settings.database_url:
            from src.database.connection import close_database
            await close_database()
            logger.info("Database connection closed")
        
        logger.info("All services shutdown successfully")
    except Exception as e:
        logger.error("Error during service shutdown", error=str(e))


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    
    # Configure logging
    configure_logging()
    
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Slack bot for querying data through MCP and returning CSV results",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )
    
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.is_development else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Add custom middleware
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(ErrorHandlerMiddleware)
    
    # Include routers
    app.include_router(health_router, prefix="/health", tags=["health"])
    
    # Socket Mode - no webhook endpoints needed
    # Slack events are handled via WebSocket connection
    
    return app


# Create app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.is_development,
        log_level=settings.log_level.lower(),
    )