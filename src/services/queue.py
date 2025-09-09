"""Async task queue implementation using Redis."""

import asyncio
import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from redis.asyncio import Redis

from src.config import settings
from src.services.redis_client import get_redis_client
from src.utils.logging import get_logger

logger = get_logger(__name__)


class TaskQueue:
    """Redis-based async task queue."""
    
    def __init__(self, redis_client: Redis, queue_name: str = "slack_bot_tasks"):
        self.redis = redis_client
        self.queue_name = queue_name
        self.processing_queue = f"{queue_name}:processing"
        self.failed_queue = f"{queue_name}:failed"
        self.results_prefix = f"{queue_name}:result"
        self.task_handlers: Dict[str, Callable] = {}
    
    async def enqueue(
        self,
        task_type: str,
        payload: Dict[str, Any],
        priority: int = 0,
        delay_seconds: int = 0,
        retry_count: int = 3,
    ) -> str:
        """Enqueue a task for processing."""
        task_id = str(uuid.uuid4())
        
        task_data = {
            "id": task_id,
            "type": task_type,
            "payload": payload,
            "priority": priority,
            "retry_count": retry_count,
            "max_retries": retry_count,
            "created_at": datetime.utcnow().isoformat(),
            "scheduled_at": (
                datetime.utcnow() + timedelta(seconds=delay_seconds)
            ).isoformat(),
        }
        
        # Serialize task data
        task_json = json.dumps(task_data)
        
        if delay_seconds > 0:
            # Schedule task for later execution
            score = (datetime.utcnow() + timedelta(seconds=delay_seconds)).timestamp()
            await self.redis.zadd(f"{self.queue_name}:delayed", {task_json: score})
        else:
            # Add to priority queue (higher priority first)
            await self.redis.lpush(self.queue_name, task_json)
        
        logger.info(
            "Task enqueued",
            task_id=task_id,
            task_type=task_type,
            priority=priority,
            delay_seconds=delay_seconds,
        )
        
        return task_id
    
    async def dequeue(self, timeout: int = 10) -> Optional[Dict[str, Any]]:
        """Dequeue a task for processing."""
        # First, move any ready delayed tasks to main queue
        await self._process_delayed_tasks()
        
        # Block and wait for a task
        result = await self.redis.brpop(self.queue_name, timeout=timeout)
        
        if not result:
            return None
        
        _, task_json = result
        task_data = json.loads(task_json)
        
        # Move to processing queue
        await self.redis.lpush(self.processing_queue, task_json)
        
        logger.info("Task dequeued", task_id=task_data["id"], task_type=task_data["type"])
        
        return task_data
    
    async def complete_task(self, task_id: str, result: Any = None) -> None:
        """Mark a task as completed."""
        # Remove from processing queue
        await self._remove_from_processing(task_id)
        
        # Store result if provided
        if result is not None:
            result_key = f"{self.results_prefix}:{task_id}"
            await self.redis.setex(
                result_key,
                3600,  # 1 hour TTL
                json.dumps({
                    "task_id": task_id,
                    "result": result,
                    "completed_at": datetime.utcnow().isoformat(),
                })
            )
        
        logger.info("Task completed", task_id=task_id)
    
    async def fail_task(self, task_id: str, error: str) -> bool:
        """Mark a task as failed and potentially retry."""
        task_json = await self._remove_from_processing(task_id)
        
        if not task_json:
            logger.warning("Task not found in processing queue", task_id=task_id)
            return False
        
        task_data = json.loads(task_json)
        task_data["retry_count"] -= 1
        task_data["last_error"] = error
        task_data["failed_at"] = datetime.utcnow().isoformat()
        
        if task_data["retry_count"] > 0:
            # Retry with exponential backoff
            delay = (task_data["max_retries"] - task_data["retry_count"]) ** 2 * 10
            
            logger.info(
                "Task failed, retrying",
                task_id=task_id,
                error=error,
                retry_count=task_data["retry_count"],
                delay_seconds=delay,
            )
            
            # Re-enqueue with delay
            score = (datetime.utcnow() + timedelta(seconds=delay)).timestamp()
            await self.redis.zadd(
                f"{self.queue_name}:delayed",
                {json.dumps(task_data): score}
            )
            return True
        else:
            # Move to failed queue
            await self.redis.lpush(self.failed_queue, json.dumps(task_data))
            
            logger.error(
                "Task permanently failed",
                task_id=task_id,
                error=error,
                max_retries=task_data["max_retries"],
            )
            return False
    
    async def get_result(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get task result by ID."""
        result_key = f"{self.results_prefix}:{task_id}"
        result_json = await self.redis.get(result_key)
        
        if result_json:
            return json.loads(result_json)
        
        return None
    
    async def get_queue_stats(self) -> Dict[str, int]:
        """Get queue statistics."""
        return {
            "pending": await self.redis.llen(self.queue_name),
            "processing": await self.redis.llen(self.processing_queue),
            "failed": await self.redis.llen(self.failed_queue),
            "delayed": await self.redis.zcard(f"{self.queue_name}:delayed"),
        }
    
    def register_handler(self, task_type: str, handler: Callable) -> None:
        """Register a task handler function."""
        self.task_handlers[task_type] = handler
        logger.info("Task handler registered", task_type=task_type)
    
    async def process_tasks(self) -> None:
        """Main task processing loop."""
        logger.info("Task processor started")
        
        while True:
            try:
                task = await self.dequeue(timeout=5)
                
                if not task:
                    continue
                
                task_id = task["id"]
                task_type = task["type"]
                
                # Find handler
                handler = self.task_handlers.get(task_type)
                if not handler:
                    await self.fail_task(task_id, f"No handler for task type: {task_type}")
                    continue
                
                try:
                    # Execute handler
                    result = await handler(task["payload"])
                    await self.complete_task(task_id, result)
                    
                except Exception as e:
                    logger.error(
                        "Task handler failed",
                        task_id=task_id,
                        task_type=task_type,
                        error=str(e),
                        exc_info=True,
                    )
                    await self.fail_task(task_id, str(e))
                
            except Exception as e:
                logger.error("Task processor error", error=str(e), exc_info=True)
                await asyncio.sleep(1)  # Brief pause before retrying
    
    async def _process_delayed_tasks(self) -> None:
        """Move ready delayed tasks to main queue."""
        now = datetime.utcnow().timestamp()
        
        # Get ready tasks
        ready_tasks = await self.redis.zrangebyscore(
            f"{self.queue_name}:delayed",
            0,
            now,
            withscores=True
        )
        
        if ready_tasks:
            # Move to main queue
            pipe = self.redis.pipeline()
            for task_json, _ in ready_tasks:
                pipe.lpush(self.queue_name, task_json)
                pipe.zrem(f"{self.queue_name}:delayed", task_json)
            
            await pipe.execute()
            
            logger.info("Moved delayed tasks to queue", count=len(ready_tasks))
    
    async def _remove_from_processing(self, task_id: str) -> Optional[str]:
        """Remove task from processing queue by ID."""
        processing_tasks = await self.redis.lrange(self.processing_queue, 0, -1)
        
        for task_json in processing_tasks:
            task_data = json.loads(task_json)
            if task_data["id"] == task_id:
                await self.redis.lrem(self.processing_queue, 1, task_json)
                return task_json
        
        return None


# Global queue instance
_task_queue: Optional[TaskQueue] = None


async def get_task_queue() -> TaskQueue:
    """Get or create task queue instance."""
    global _task_queue
    
    if _task_queue is None:
        redis_client = await get_redis_client()
        _task_queue = TaskQueue(redis_client)
    
    return _task_queue