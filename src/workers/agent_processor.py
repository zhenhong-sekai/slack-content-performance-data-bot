"""Agent processor for handling query processing workflows."""

import asyncio
from typing import Any, Dict

from src.agents.state import create_initial_state
from src.agents.workflow import get_agent_workflow
from src.services.queue import get_task_queue
from src.services.slack_socket_client import get_slack_socket_service
from src.utils.logging import get_logger

logger = get_logger(__name__)


async def process_agent_query(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Process a query through the agent workflow."""
    
    query = payload.get("query", "")
    user_id = payload.get("user_id", "")
    channel_id = payload.get("channel_id", "")
    thread_ts = payload.get("thread_ts")
    
    logger.info(
        "Starting agent query processing",
        query=query[:100] + "..." if len(query) > 100 else query,
        user_id=user_id,
        channel_id=channel_id,
    )
    
    try:
        # Create initial state
        initial_state = create_initial_state(
            query=query,
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
        )
        
        # Get compiled workflow
        workflow = get_agent_workflow()
        
        # Execute workflow
        config = {"configurable": {"thread_id": f"query_{user_id}_{channel_id}"}}
        
        final_state = None
        async for state in workflow.astream(initial_state, config=config):
            final_state = state
            logger.debug(
                "Workflow step completed",
                step=list(state.keys())[0] if state else "unknown",
                user_id=user_id,
            )
        
        if not final_state:
            raise Exception("Workflow did not produce a final state")
        
        # Send results to Slack
        await send_results_to_slack(final_state)
        
        logger.info(
            "Agent query processing completed",
            query=query[:50] + "..." if len(query) > 50 else query,
            user_id=user_id,
            success=final_state.get("error") is None,
            processing_steps=len(final_state.get("processing_steps", [])),
        )
        
        return {
            "status": "completed",
            "success": final_state.get("error") is None,
            "error": final_state.get("error"),
            "csv_path": final_state.get("csv_path"),
            "result_summary": final_state.get("result_summary"),
        }
        
    except Exception as e:
        logger.error(
            "Agent query processing failed",
            query=query,
            user_id=user_id,
            error=str(e),
            exc_info=True,
        )
        
        # Send error to Slack
        try:
            await send_error_to_slack(
                channel_id=channel_id,
                user_id=user_id,
                thread_ts=thread_ts,
                query=query,
                error=str(e),
            )
        except Exception as slack_error:
            logger.error(f"Failed to send error to Slack: {slack_error}")
        
        return {
            "status": "failed",
            "success": False,
            "error": str(e),
        }


async def send_results_to_slack(state: Dict[str, Any]) -> None:
    """Send query results to Slack."""
    
    channel_id = state.get("channel_id")
    user_id = state.get("user_id")
    thread_ts = state.get("thread_ts")
    query = state.get("query", "")
    csv_path = state.get("csv_path")
    result_summary = state.get("result_summary", "")
    error = state.get("error")
    
    if not channel_id or not user_id:
        logger.error("Missing channel_id or user_id in state")
        return
    
    slack_service = await get_slack_socket_service()
    
    try:
        if error:
            # Send error message
            blocks = slack_service.create_error_blocks(error, query)
            
            await slack_service.send_message(
                channel_id=channel_id,
                text=f"❌ Query failed: {error}",
                blocks=blocks,
                thread_ts=thread_ts,
            )
        
        elif csv_path:
            # Send success message with file
            processed_data = state.get("processed_data", {})
            row_count = processed_data.get("row_count")
            
            # Upload CSV file
            await slack_service.upload_file(
                file_path=csv_path,
                channel_id=channel_id,
                thread_ts=thread_ts,
                title=f"Query Results - {query[:50]}{'...' if len(query) > 50 else ''}",
                initial_comment=f"<@{user_id}> {result_summary}",
            )
            
            logger.info(
                "Results sent to Slack",
                channel_id=channel_id,
                user_id=user_id,
                csv_path=csv_path,
                row_count=row_count,
            )
        
        else:
            # Send generic completion message
            await slack_service.send_message(
                channel_id=channel_id,
                text=f"<@{user_id}> {result_summary or 'Query completed, but no results were generated.'}",
                thread_ts=thread_ts,
            )
    
    except Exception as e:
        logger.error(
            "Failed to send results to Slack",
            channel_id=channel_id,
            error=str(e),
            exc_info=True,
        )
        raise


async def send_error_to_slack(
    channel_id: str,
    user_id: str,
    query: str,
    error: str,
    thread_ts: str = None,
) -> None:
    """Send error message to Slack."""
    
    try:
        slack_service = await get_slack_socket_service()
        
        # Create user-friendly error message
        if "timeout" in error.lower():
            user_error = (
                "Your query is taking longer than expected. "
                "Please try a more specific query or try again later."
            )
        elif "mcp" in error.lower() or "server" in error.lower():
            user_error = (
                "I'm having trouble accessing the data right now. "
                "Please try again in a few minutes."
            )
        elif "validation" in error.lower() or "understand" in error.lower():
            user_error = (
                "I couldn't understand your query. Could you please rephrase it? "
                "Try being more specific about what data you're looking for."
            )
        else:
            user_error = (
                "Something went wrong while processing your query. "
                "Please try rephrasing your question or contact support if this continues."
            )
        
        blocks = slack_service.create_error_blocks(user_error, query)
        
        await slack_service.send_message(
            channel_id=channel_id,
            text=f"❌ <@{user_id}> {user_error}",
            blocks=blocks,
            thread_ts=thread_ts,
        )
        
        logger.info(
            "Error message sent to Slack",
            channel_id=channel_id,
            user_id=user_id,
        )
    
    except Exception as e:
        logger.error(f"Failed to send error to Slack: {e}")


async def start_agent_processor():
    """Start the agent processor worker."""
    logger.info("Starting agent processor")
    
    queue = await get_task_queue()
    
    # Register agent task handler
    queue.register_handler("process_agent_query", process_agent_query)
    
    # Start processing tasks
    await queue.process_tasks()


if __name__ == "__main__":
    asyncio.run(start_agent_processor())