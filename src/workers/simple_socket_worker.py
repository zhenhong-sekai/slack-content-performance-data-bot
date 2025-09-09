"""Simple Socket Mode worker without Redis dependencies."""

import asyncio
import signal

from src.services.slack_socket_simple import get_simple_slack_service
from src.utils.logging import get_logger

logger = get_logger(__name__)


class SimpleSocketModeWorker:
    """Simple worker that handles Slack Socket Mode events without Redis."""
    
    def __init__(self):
        self.slack_service = None
        self.running = False
    
    async def start(self):
        """Start the simple Socket Mode worker."""
        logger.info("Starting Simple Socket Mode worker (no Redis/PostgreSQL)...")
        
        try:
            # Initialize Slack service
            self.slack_service = await get_simple_slack_service()
            
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
        if not self.running:
            return
        
        logger.info("Stopping Simple Socket Mode worker...")
        
        try:
            if self.slack_service:
                await self.slack_service.stop()
            
            self.running = False
            logger.info("Simple Socket Mode worker stopped successfully")
            
        except Exception as e:
            logger.error(f"Error stopping Simple Socket Mode worker: {e}")
    
    def _register_shutdown_handlers(self):
        """Register signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
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