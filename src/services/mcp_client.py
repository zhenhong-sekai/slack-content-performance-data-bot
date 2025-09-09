"""MCP (Model Context Protocol) client implementation."""

import asyncio
import json
from typing import Any, Dict, List, Optional

import aiohttp
from aiohttp import ClientTimeout, ClientError

from src.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class MCPClient:
    """Client for communicating with MCP servers."""
    
    def __init__(
        self,
        server_url: str = None,
        timeout: int = None,
        max_retries: int = 5,
        retry_delay: float = 1.0,
    ):
        self.server_url = server_url or settings.mcp_server_url
        self.timeout = timeout or settings.mcp_server_timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self._create_session()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self._close_session()
    
    async def _create_session(self):
        """Create HTTP session with proper configuration."""
        if self._session is None or self._session.closed:
            timeout = ClientTimeout(total=self.timeout)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": f"{settings.app_name}/{settings.app_version}",
                },
                connector=aiohttp.TCPConnector(
                    limit=10,
                    keepalive_timeout=30,
                    enable_cleanup_closed=True,
                )
            )
    
    async def _close_session(self):
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout: Optional[int] = None,
        retry_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Call an MCP tool with the given arguments."""
        
        await self._create_session()
        
        request_data = {
            "jsonrpc": "2.0",
            "id": f"req_{asyncio.current_task().get_name()}_{tool_name}",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        
        actual_timeout = timeout or self.timeout
        actual_retries = retry_count if retry_count is not None else self.max_retries
        
        logger.info(
            "Calling MCP tool",
            tool_name=tool_name,
            arguments=arguments,
            timeout=actual_timeout,
            retries=actual_retries,
        )
        
        last_error = None
        
        for attempt in range(actual_retries + 1):
            try:
                # Add timeout to session for this request
                timeout_config = ClientTimeout(total=actual_timeout)
                
                async with self._session.post(
                    f"{self.server_url}/mcp",
                    json=request_data,
                    timeout=timeout_config
                ) as response:
                    
                    response_text = await response.text()
                    
                    if response.status == 200:
                        response_data = json.loads(response_text)
                        
                        # Check for JSON-RPC errors
                        if "error" in response_data:
                            error_info = response_data["error"]
                            raise MCPError(
                                f"MCP tool error: {error_info.get('message', 'Unknown error')}",
                                code=error_info.get("code"),
                                data=error_info.get("data")
                            )
                        
                        # Extract result
                        result = response_data.get("result")
                        if result is None:
                            raise MCPError("MCP tool returned no result")
                        
                        logger.info(
                            "MCP tool call successful",
                            tool_name=tool_name,
                            attempt=attempt + 1,
                            response_size=len(response_text),
                        )
                        
                        return result
                    
                    else:
                        raise MCPError(
                            f"MCP server returned status {response.status}: {response_text}",
                            status_code=response.status
                        )
            
            except (ClientError, asyncio.TimeoutError, json.JSONDecodeError, MCPError) as e:
                last_error = e
                
                if attempt < actual_retries:
                    delay = self.retry_delay * (2 ** attempt)  # Exponential backoff
                    
                    logger.warning(
                        "MCP tool call failed, retrying",
                        tool_name=tool_name,
                        attempt=attempt + 1,
                        max_retries=actual_retries,
                        error=str(e),
                        retry_delay=delay,
                    )
                    
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "MCP tool call failed after all retries",
                        tool_name=tool_name,
                        attempts=actual_retries + 1,
                        error=str(e),
                        exc_info=True,
                    )
        
        # If we get here, all retries failed
        raise MCPError(f"MCP tool call failed after {actual_retries + 1} attempts: {str(last_error)}")
    
    async def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools from the MCP server."""
        
        await self._create_session()
        
        request_data = {
            "jsonrpc": "2.0",
            "id": "list_tools_request",
            "method": "tools/list",
            "params": {}
        }
        
        try:
            async with self._session.post(
                f"{self.server_url}/mcp",
                json=request_data
            ) as response:
                
                if response.status == 200:
                    response_data = await response.json()
                    
                    if "error" in response_data:
                        raise MCPError(f"Failed to list tools: {response_data['error']}")
                    
                    tools = response_data.get("result", {}).get("tools", [])
                    
                    logger.info("Retrieved MCP tools list", tool_count=len(tools))
                    
                    return tools
                
                else:
                    error_text = await response.text()
                    raise MCPError(f"Failed to list tools: HTTP {response.status} - {error_text}")
        
        except (ClientError, asyncio.TimeoutError, json.JSONDecodeError) as e:
            logger.error("Failed to list MCP tools", error=str(e))
            raise MCPError(f"Failed to list tools: {str(e)}")
    
    async def check_health(self) -> Dict[str, Any]:
        """Check MCP server health."""
        
        await self._create_session()
        
        try:
            async with self._session.get(f"{self.server_url}/health") as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    raise MCPError(f"Health check failed: HTTP {response.status} - {error_text}")
        
        except (ClientError, asyncio.TimeoutError) as e:
            logger.error("MCP health check failed", error=str(e))
            raise MCPError(f"Health check failed: {str(e)}")


class MCPError(Exception):
    """Custom exception for MCP-related errors."""
    
    def __init__(self, message: str, code: Optional[int] = None, data: Any = None, status_code: Optional[int] = None):
        super().__init__(message)
        self.code = code
        self.data = data
        self.status_code = status_code


# Circuit breaker pattern for MCP calls
class MCPCircuitBreaker:
    """Circuit breaker to prevent cascading failures with MCP server."""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: type = MCPError,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half-open
    
    async def call(self, func, *args, **kwargs):
        """Execute function with circuit breaker protection."""
        
        if self.state == "open":
            if self._should_attempt_reset():
                self.state = "half-open"
                logger.info("Circuit breaker entering half-open state")
            else:
                raise MCPError("Circuit breaker is open - MCP server unavailable")
        
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        
        except self.expected_exception as e:
            self._on_failure()
            raise
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        if self.last_failure_time is None:
            return True
        
        import time
        return (time.time() - self.last_failure_time) >= self.recovery_timeout
    
    def _on_success(self):
        """Handle successful call."""
        self.failure_count = 0
        self.state = "closed"
        self.last_failure_time = None
    
    def _on_failure(self):
        """Handle failed call."""
        import time
        
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            logger.warning(
                "Circuit breaker opened",
                failure_count=self.failure_count,
                threshold=self.failure_threshold,
            )


# Global instances
_mcp_client: Optional[MCPClient] = None
_circuit_breaker: Optional[MCPCircuitBreaker] = None


def get_mcp_client() -> MCPClient:
    """Get or create MCP client instance."""
    global _mcp_client
    
    if _mcp_client is None:
        _mcp_client = MCPClient()
    
    return _mcp_client


def get_circuit_breaker() -> MCPCircuitBreaker:
    """Get or create circuit breaker instance."""
    global _circuit_breaker
    
    if _circuit_breaker is None:
        _circuit_breaker = MCPCircuitBreaker()
    
    return _circuit_breaker