#!/usr/bin/env python3
"""
Simple runner for OptiBot without Redis/PostgreSQL dependencies.

This script runs OptiBot in a simplified mode that processes all queries
directly without using background task queues or persistent storage.
"""

import asyncio
import sys
import os

# Add src to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.workers.simple_socket_worker import start_simple_socket_worker
from src.utils.logging import configure_logging, get_logger

def main():
    """Main entry point for simple OptiBot."""
    print("🚀 Starting OptiBot (Simplified Mode - No Redis/PostgreSQL)")
    print("📋 This version processes queries directly without background queuing")
    print("")
    
    # Configure logging
    configure_logging()
    logger = get_logger(__name__)
    
    try:
        # Run the simple socket worker
        asyncio.run(start_simple_socket_worker())
    except KeyboardInterrupt:
        print("\n👋 OptiBot shutting down...")
        logger.info("OptiBot shutdown by user")
    except Exception as e:
        print(f"\n❌ OptiBot failed to start: {e}")
        logger.error(f"OptiBot startup failed: {e}", exc_info=True)
        sys.exit(1)
    finally:
        print("✅ OptiBot stopped")
        sys.exit(0)

if __name__ == "__main__":
    main()