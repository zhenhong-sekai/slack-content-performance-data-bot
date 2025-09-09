"""Health check endpoints."""

import asyncio
from typing import Dict, Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from src.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


class HealthResponse(BaseModel):
    """Health check response model."""
    status: str
    version: str
    environment: str
    checks: Dict[str, Any]


class ServiceCheck(BaseModel):
    """Individual service check result."""
    healthy: bool
    response_time_ms: float
    error: str = None


async def check_redis_health() -> ServiceCheck:
    """Check Redis connectivity and performance."""
    import time
    start_time = time.time()
    
    try:
        from src.services.redis_client import get_redis_client
        redis_client = await get_redis_client()
        await redis_client.ping()
        
        response_time = (time.time() - start_time) * 1000
        return ServiceCheck(healthy=True, response_time_ms=round(response_time, 2))
    
    except Exception as e:
        response_time = (time.time() - start_time) * 1000
        return ServiceCheck(
            healthy=False, 
            response_time_ms=round(response_time, 2), 
            error=str(e)
        )


async def check_database_health() -> ServiceCheck:
    """Check database connectivity if configured."""
    if not settings.database_url:
        return ServiceCheck(healthy=True, response_time_ms=0.0)
    
    import time
    start_time = time.time()
    
    try:
        from src.database.connection import get_database
        db = await get_database()
        # Simple query to test connection
        await db.fetch("SELECT 1")
        
        response_time = (time.time() - start_time) * 1000
        return ServiceCheck(healthy=True, response_time_ms=round(response_time, 2))
    
    except Exception as e:
        response_time = (time.time() - start_time) * 1000
        return ServiceCheck(
            healthy=False,
            response_time_ms=round(response_time, 2),
            error=str(e)
        )


async def check_mcp_server_health() -> ServiceCheck:
    """Check MCP server connectivity."""
    import time
    import aiohttp
    
    start_time = time.time()
    
    try:
        timeout = aiohttp.ClientTimeout(total=settings.health_check_timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{settings.mcp_server_url}/health") as response:
                if response.status == 200:
                    response_time = (time.time() - start_time) * 1000
                    return ServiceCheck(healthy=True, response_time_ms=round(response_time, 2))
                else:
                    raise Exception(f"MCP server returned status {response.status}")
    
    except Exception as e:
        response_time = (time.time() - start_time) * 1000
        return ServiceCheck(
            healthy=False,
            response_time_ms=round(response_time, 2),
            error=str(e)
        )


async def check_storage_health() -> ServiceCheck:
    """Check file storage accessibility."""
    import time
    import os
    import tempfile
    
    start_time = time.time()
    
    try:
        # Ensure temp directory exists
        os.makedirs(settings.temp_file_path, exist_ok=True)
        
        # Test write/read/delete
        test_file = os.path.join(settings.temp_file_path, "health_check.txt")
        with open(test_file, "w") as f:
            f.write("health check")
        
        with open(test_file, "r") as f:
            content = f.read()
            if content != "health check":
                raise Exception("File content mismatch")
        
        os.remove(test_file)
        
        response_time = (time.time() - start_time) * 1000
        return ServiceCheck(healthy=True, response_time_ms=round(response_time, 2))
    
    except Exception as e:
        response_time = (time.time() - start_time) * 1000
        return ServiceCheck(
            healthy=False,
            response_time_ms=round(response_time, 2),
            error=str(e)
        )


@router.get("/", response_model=HealthResponse)
async def health_check():
    """Comprehensive health check endpoint."""
    logger.info("Health check requested")
    
    # Run all health checks concurrently
    redis_check, db_check, mcp_check, storage_check = await asyncio.gather(
        check_redis_health(),
        check_database_health(),
        check_mcp_server_health(),
        check_storage_health(),
        return_exceptions=True
    )
    
    # Handle any exceptions in health checks
    checks = {}
    
    if isinstance(redis_check, Exception):
        checks["redis"] = ServiceCheck(
            healthy=False, 
            response_time_ms=0.0, 
            error=str(redis_check)
        )
    else:
        checks["redis"] = redis_check
    
    if isinstance(db_check, Exception):
        checks["database"] = ServiceCheck(
            healthy=False,
            response_time_ms=0.0,
            error=str(db_check)
        )
    else:
        checks["database"] = db_check
    
    if isinstance(mcp_check, Exception):
        checks["mcp_server"] = ServiceCheck(
            healthy=False,
            response_time_ms=0.0,
            error=str(mcp_check)
        )
    else:
        checks["mcp_server"] = mcp_check
    
    if isinstance(storage_check, Exception):
        checks["storage"] = ServiceCheck(
            healthy=False,
            response_time_ms=0.0,
            error=str(storage_check)
        )
    else:
        checks["storage"] = storage_check
    
    # Determine overall health
    all_healthy = all(
        check.healthy for check in checks.values() 
        if isinstance(check, ServiceCheck)
    )
    
    status_code = status.HTTP_200_OK if all_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    overall_status = "healthy" if all_healthy else "unhealthy"
    
    response = HealthResponse(
        status=overall_status,
        version=settings.app_version,
        environment=settings.environment,
        checks={name: check.dict() for name, check in checks.items()}
    )
    
    if not all_healthy:
        logger.warning("Health check failed", checks=checks)
        raise HTTPException(status_code=status_code, detail=response.dict())
    
    logger.info("Health check passed")
    return response


@router.get("/ready")
async def readiness_check():
    """Simple readiness check for load balancers."""
    return {"status": "ready"}


@router.get("/live")
async def liveness_check():
    """Simple liveness check for container orchestrators."""
    return {"status": "alive"}