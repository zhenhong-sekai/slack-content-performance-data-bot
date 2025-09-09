"""Socket Mode worker for handling Slack events in real-time."""

import asyncio
import signal
from typing import Dict, Any

from src.services.slack_socket_client import get_slack_socket_service
from src.services.queue import get_task_queue
from src.utils.logging import get_logger

logger = get_logger(__name__)


class SocketModeWorker:
    """Worker that handles Slack Socket Mode events."""
    
    def __init__(self):
        self.slack_service = None
        self.task_queue = None
        self.running = False
    
    async def start(self):
        """Start the Socket Mode worker."""
        logger.info("Starting Socket Mode worker...")
        
        try:
            # Initialize services
            self.slack_service = await get_slack_socket_service()
            self.task_queue = await get_task_queue()
            
            # Register shutdown handlers
            self._register_shutdown_handlers()
            
            # Mark as running
            self.running = True
            
            logger.info("Socket Mode worker initialized successfully")
            
            # Start the Socket Mode handler (this blocks)
            await self.slack_service.start()
            
        except KeyboardInterrupt:
            logger.info("Socket Mode worker interrupted by user")
        except Exception as e:
            logger.error(f"Socket Mode worker failed: {e}", exc_info=True)
            raise
        finally:
            await self.stop()
    
    async def stop(self):
        """Stop the Socket Mode worker."""
        if not self.running:
            return
        
        logger.info("Stopping Socket Mode worker...")
        
        try:
            if self.slack_service:
                await self.slack_service.stop()
            
            self.running = False
            logger.info("Socket Mode worker stopped successfully")
            
        except Exception as e:
            logger.error(f"Error stopping Socket Mode worker: {e}")
    
    def _register_shutdown_handlers(self):
        """Register signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating shutdown...")
            asyncio.create_task(self.stop())
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)


async def start_socket_mode_worker():
    """Start the Socket Mode worker."""
    worker = SocketModeWorker()
    await worker.start()


if __name__ == "__main__":
    asyncio.run(start_socket_mode_worker())