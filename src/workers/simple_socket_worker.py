"""Simple Socket Mode worker without Redis dependencies."""

import asyncio
import signal
import sys
import os

from src.services.slack_socket_simple import get_simple_slack_service
from src.utils.logging import get_logger

logger = get_logger(__name__)


class SimpleSocketModeWorker:
    """Simple worker that handles Slack Socket Mode events without Redis."""
    
    def __init__(self):
        self.slack_service = None
        self.running = False
        self._shutdown_requested = False
    
    async def start(self):
        """Start the simple Socket Mode worker."""
        logger.info("Starting Simple Socket Mode worker (no Redis/PostgreSQL)...")
        
        try:
            # Initialize Slack service
            self.slack_service = await get_simple_slack_service()
            
            # Pre-initialize the LangGraph ReAct agent to avoid delays on first query
            logger.info("Pre-initializing LangGraph ReAct agent...")
            try:
                # Check temp directory exists and is writable
                import os
                from src.config import settings
                temp_dir = settings.temp_file_path
                if not os.path.exists(temp_dir):
                    logger.info(f"Creating temp directory: {temp_dir}")
                    os.makedirs(temp_dir, exist_ok=True)
                
                # Test temp directory is writable
                test_file = os.path.join(temp_dir, 'test_write.tmp')
                try:
                    with open(test_file, 'w') as f:
                        f.write('test')
                    os.remove(test_file)
                    logger.info(f"Temp directory {temp_dir} is writable")
                except Exception as e:
                    raise RuntimeError(f"Temp directory {temp_dir} is not writable: {str(e)}")
                
                # Initialize agent
                from src.agents.langgraph_react_agent import get_langgraph_react_agent
                agent = await get_langgraph_react_agent()
                
                # Validate agent initialization
                if not agent.graph:
                    raise RuntimeError("Agent graph not initialized")
                if not agent.mcp_client:
                    raise RuntimeError("MCP client not initialized")
                if not agent.tools:
                    raise RuntimeError("Agent tools not initialized")
                
                # Test MCP client connection
                logger.info(f"Testing MCP client connection to {settings.mcp_server_url}")
                tools = await agent.mcp_client.get_tools()
                if not tools:
                    raise RuntimeError("MCP client returned no tools")
                
                logger.info("LangGraph ReAct agent pre-initialized successfully",
                          has_graph=bool(agent.graph),
                          has_mcp_client=bool(agent.mcp_client),
                          tool_count=len(agent.tools),
                          mcp_url=settings.mcp_server_url,
                          temp_dir=temp_dir)
                          
            except Exception as e:
                logger.error("Failed to pre-initialize LangGraph ReAct agent",
                           error=str(e),
                           error_type=type(e).__name__,
                           mcp_url=settings.mcp_server_url,
                           temp_dir=settings.temp_file_path,
                           exc_info=True)
                raise RuntimeError(f"Agent pre-initialization failed: {str(e)}")
            
            # Register shutdown handlers
            self._register_shutdown_handlers()
            
            # Mark as running
            self.running = True
            
            logger.info("Simple Socket Mode worker initialized successfully")
            
            # Start the Socket Mode handler (this blocks)
            await self.slack_service.start()
            
        except KeyboardInterrupt:
            logger.info("Simple Socket Mode worker interrupted by user")
        except Exception as e:
            logger.error(f"Simple Socket Mode worker failed: {e}", exc_info=True)
            raise
        finally:
            await self.stop()
    
    async def stop(self):
        """Stop the simple Socket Mode worker."""
        if not self.running or self._shutdown_requested:
            return
        
        self._shutdown_requested = True
        logger.info("Stopping Simple Socket Mode worker...")
        
        try:
            if self.slack_service:
                await self.slack_service.stop()
            
            self.running = False
            logger.info("Simple Socket Mode worker stopped successfully")
            
        except Exception as e:
            logger.error(f"Error stopping Simple Socket Mode worker: {e}")
        finally:
            # Force exit after cleanup
            logger.info("Forcing process exit...")
            os._exit(0)
    
    def _register_shutdown_handlers(self):
        """Register signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            if not self._shutdown_requested:
                logger.info(f"Received signal {signum}, initiating shutdown...")
                asyncio.create_task(self.stop())
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)


async def start_simple_socket_worker():
    """Start the simple Socket Mode worker."""
    worker = SimpleSocketModeWorker()
    await worker.start()


if __name__ == "__main__":
    asyncio.run(start_simple_socket_worker())