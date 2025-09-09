"""Slack event background task processor."""

import asyncio
from typing import Any, Dict

from src.services.queue import get_task_queue
from src.utils.logging import get_logger

logger = get_logger(__name__)


async def process_slack_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Process a Slack event asynchronously."""
    event_type = payload.get("type")
    event_data = payload.get("event", {})
    
    logger.info(
        "Processing Slack event",
        event_type=event_type,
        event_subtype=event_data.get("type"),
        channel=event_data.get("channel"),
        user=event_data.get("user"),
    )
    
    try:
        if event_type == "event_callback":
            return await _handle_event_callback(event_data)
        elif event_type == "url_verification":
            return await _handle_url_verification(payload)
        else:
            logger.warning("Unknown event type", event_type=event_type)
            return {"status": "ignored", "reason": f"Unknown event type: {event_type}"}
    
    except Exception as e:
        logger.error(
            "Slack event processing failed",
            event_type=event_type,
            error=str(e),
            exc_info=True,
        )
        raise


async def process_slack_command(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Process a Slack slash command asynchronously."""
    command = payload.get("command")
    text = payload.get("text", "").strip()
    user_id = payload.get("user_id")
    channel_id = payload.get("channel_id")
    
    logger.info(
        "Processing Slack command",
        command=command,
        text=text[:100] + "..." if len(text) > 100 else text,
        user_id=user_id,
        channel_id=channel_id,
    )
    
    try:
        if command == "/query-data":
            return await _handle_data_query(text, user_id, channel_id)
        else:
            logger.warning("Unknown command", command=command)
            return {
                "status": "error",
                "message": f"Unknown command: {command}"
            }
    
    except Exception as e:
        logger.error(
            "Slack command processing failed",
            command=command,
            error=str(e),
            exc_info=True,
        )
        raise


async def _handle_event_callback(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle Slack event callback."""
    event_type = event_data.get("type")
    
    if event_type == "app_mention":
        return await _handle_app_mention(event_data)
    elif event_type == "message":
        return await _handle_message(event_data)
    else:
        logger.info("Ignoring event type", event_type=event_type)
        return {"status": "ignored", "reason": f"Unhandled event type: {event_type}"}


async def _handle_url_verification(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Handle Slack URL verification challenge."""
    challenge = payload.get("challenge")
    logger.info("URL verification challenge received", challenge=challenge)
    return {"challenge": challenge}


async def _handle_app_mention(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle bot mention in a channel."""
    text = event_data.get("text", "")
    user_id = event_data.get("user")
    channel_id = event_data.get("channel")
    thread_ts = event_data.get("thread_ts")
    
    # Remove bot mention from text
    import re
    query_text = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
    
    if not query_text:
        return await _send_help_message(channel_id, user_id, thread_ts)
    
    return await _handle_data_query(query_text, user_id, channel_id, thread_ts)


async def _handle_message(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle direct messages to the bot."""
    # Only handle DMs, not channel messages
    channel_type = event_data.get("channel_type")
    
    if channel_type != "im":
        return {"status": "ignored", "reason": "Not a direct message"}
    
    text = event_data.get("text", "").strip()
    user_id = event_data.get("user")
    channel_id = event_data.get("channel")
    
    if not text:
        return await _send_help_message(channel_id, user_id)
    
    return await _handle_data_query(text, user_id, channel_id)


async def _handle_data_query(
    query_text: str,
    user_id: str,
    channel_id: str,
    thread_ts: str = None
) -> Dict[str, Any]:
    """Handle a data query from the user."""
    
    # Send immediate acknowledgment
    await _send_processing_message(channel_id, user_id, thread_ts)
    
    # Queue the query for agent processing
    queue = await get_task_queue()
    
    agent_task_id = await queue.enqueue(
        task_type="process_agent_query",
        payload={
            "query": query_text,
            "user_id": user_id,
            "channel_id": channel_id,
            "thread_ts": thread_ts,
        },
        priority=1,  # High priority for user queries
    )
    
    logger.info(
        "Data query queued for agent processing",
        agent_task_id=agent_task_id,
        query=query_text[:100] + "..." if len(query_text) > 100 else query_text,
        user_id=user_id,
        channel_id=channel_id,
    )
    
    return {
        "status": "queued",
        "agent_task_id": agent_task_id,
        "message": "Query is being processed..."
    }


async def _send_processing_message(
    channel_id: str,
    user_id: str,
    thread_ts: str = None
) -> None:
    """Send processing acknowledgment message."""
    try:
        from src.services.slack_client import get_slack_service
        
        slack_service = get_slack_service()
        
        message = (
            f"<@{user_id}> I'm processing your query... "
            "This may take a moment while I search through the data. "
            "I'll send you the results as a CSV file when ready! 📊"
        )
        
        await slack_service.send_message(
            channel_id=channel_id,
            text=message,
            thread_ts=thread_ts
        )
        
    except Exception as e:
        logger.error("Failed to send processing message", error=str(e))


async def _send_help_message(
    channel_id: str,
    user_id: str,
    thread_ts: str = None
) -> Dict[str, Any]:
    """Send help message to user."""
    try:
        from src.services.slack_client import get_slack_service
        
        slack_service = get_slack_service()
        
        help_text = f"""
Hello <@{user_id}>! 👋 I'm your data query assistant.

I can help you get data from our systems using natural language queries. Here are some examples:

🔍 **Query Examples:**
• "Show me last week's performance metrics"
• "What were the top campaigns yesterday?"
• "Get user engagement data for the past month"
• "Find conversion rates by channel this quarter"

💡 **How to use me:**
• @ mention me in any channel with your query
• Send me a direct message with your question
• Use the `/query-data` slash command

I'll process your request and send you the results as a downloadable CSV file! 📈

Just ask me anything about your data and I'll do my best to help! 🚀
        """
        
        await slack_service.send_message(
            channel_id=channel_id,
            text=help_text.strip(),
            thread_ts=thread_ts
        )
        
        return {"status": "help_sent"}
        
    except Exception as e:
        logger.error("Failed to send help message", error=str(e))
        return {"status": "error", "error": str(e)}


async def start_slack_processor():
    """Start the Slack event processor worker."""
    logger.info("Starting Slack event processor")
    
    queue = await get_task_queue()
    
    # Register task handlers
    queue.register_handler("process_slack_event", process_slack_event)
    queue.register_handler("process_slack_command", process_slack_command)
    
    # Start processing tasks
    await queue.process_tasks()


if __name__ == "__main__":
    asyncio.run(start_slack_processor())