"""Simplified Slack Socket Mode client without Redis queuing."""

import asyncio
import re
from typing import Any, Dict, List, Optional

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_sdk.errors import SlackApiError

from src.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class SimpleSlackSocketService:
    """Simplified Slack Socket Mode service - processes queries directly."""
    
    def __init__(self):
        # Initialize Slack Bolt app for Socket Mode
        self.app = AsyncApp(
            token=settings.slack_bot_token,
            signing_secret=settings.slack_signing_secret,
        )
        
        self._bot_user_id: Optional[str] = None
        self._handler: Optional[AsyncSocketModeHandler] = None
        
        # Register event handlers
        self._register_handlers()
    
    def _register_handlers(self):
        """Register Slack event handlers."""
        
        # Handle app mentions (@OptiBot)
        @self.app.event("app_mention")
        async def handle_app_mention(event, say):
            await self._handle_mention(event, say)
        
        # Handle direct messages
        @self.app.event("message")
        async def handle_message(event, say):
            # Only handle DMs (channel type 'im')
            if event.get("channel_type") == "im":
                await self._handle_direct_message(event, say)
        
        # Handle message replies in threads
        @self.app.event("message")
        async def handle_thread_reply(event, say):
            # Check if this is a thread reply to our bot
            if event.get("thread_ts") and not event.get("bot_id"):
                await self._handle_thread_reply(event, say)
    
    async def initialize(self):
        """Initialize the Socket Mode service."""
        try:
            # Get bot user ID
            auth_response = await self.app.client.auth_test()
            self._bot_user_id = auth_response["user_id"]
            
            # Check bot scopes for debugging
            try:
                scopes = auth_response.get("response_metadata", {}).get("scopes", [])
                logger.info("Bot OAuth scopes", scopes=scopes)
            except Exception as scope_error:
                logger.warning("Could not retrieve bot scopes", error=str(scope_error))
            
            logger.info(
                "Simple Slack Socket Mode service initialized",
                bot_user_id=self._bot_user_id,
                team_id=auth_response.get("team_id"),
                app_id=auth_response.get("app_id"),
            )
            
        except SlackApiError as e:
            logger.error(f"Failed to initialize Slack Socket Mode service: {e}")
            raise
    
    async def start(self):
        """Start the Socket Mode handler."""
        if not settings.slack_app_token:
            raise ValueError("SLACK_APP_TOKEN is required for Socket Mode")
        
        self._handler = AsyncSocketModeHandler(
            self.app, 
            settings.slack_app_token
        )
        
        logger.info("Starting Simple Slack Socket Mode handler...")
        await self._handler.start_async()
    
    async def stop(self):
        """Stop the Socket Mode handler."""
        if self._handler:
            await self._handler.close_async()
            logger.info("Simple Slack Socket Mode handler stopped")
    
    async def _handle_mention(self, event: Dict[str, Any], say):
        """Handle @ mentions of the bot."""
        text = event.get("text", "")
        user_id = event.get("user")
        channel_id = event.get("channel")
        thread_ts = event.get("thread_ts")
        message_ts = event.get("ts")
        
        # Remove bot mention from text
        clean_text = self._extract_query_from_mention(text)
        
        logger.info(
            "App mention received",
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            query_length=len(clean_text),
        )
        
        if not clean_text.strip():
            await self._send_help_message(say, user_id, thread_ts)
            return
        
        # Send processing acknowledgment - use message_ts if not already in a thread
        await self._send_processing_message(say, user_id, thread_ts or message_ts)
        
        # Process query DIRECTLY (no queuing)
        await self._process_query_directly(
            query=clean_text,
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=thread_ts or message_ts,
            say=say
        )
    
    async def _handle_direct_message(self, event: Dict[str, Any], say):
        """Handle direct messages to the bot."""
        text = event.get("text", "").strip()
        user_id = event.get("user")
        channel_id = event.get("channel")
        
        # Ignore bot messages and messages with subtypes
        if event.get("bot_id") or event.get("subtype"):
            return
        
        logger.info(
            "Direct message received",
            user_id=user_id,
            channel_id=channel_id,
            query_length=len(text),
        )
        
        if not text:
            await self._send_help_message(say, user_id)
            return
        
        # Send processing acknowledgment
        await self._send_processing_message(say, user_id)
        
        # Process query DIRECTLY (no queuing)
        await self._process_query_directly(
            query=text,
            user_id=user_id,
            channel_id=channel_id,
            say=say
        )
    
    async def _handle_thread_reply(self, event: Dict[str, Any], say):
        """Handle replies in threads where bot was mentioned."""
        text = event.get("text", "").strip()
        user_id = event.get("user")
        channel_id = event.get("channel")
        thread_ts = event.get("thread_ts")
        
        # Only handle if it's a reply to a thread and not from a bot
        if not thread_ts or event.get("bot_id"):
            return
        
        logger.info(
            "Thread reply received",
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            query_length=len(text),
        )
        
        if not text:
            return
        
        # Send processing acknowledgment in thread
        await self._send_processing_message(say, user_id, thread_ts)
        
        # Process query DIRECTLY (no queuing)
        await self._process_query_directly(
            query=text,
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            say=say
        )
    
    async def _process_query_directly(
        self, 
        query: str, 
        user_id: str, 
        channel_id: str, 
        say,
        thread_ts: str = None
    ):
        """Process query directly using simple MCP agent."""
        try:
            # Import here to avoid circular imports
            from src.agents.langgraph_react_agent import get_langgraph_react_agent
            
            logger.info(
                "Processing query with LangGraph ReAct agent",
                query=query[:50] + "..." if len(query) > 50 else query,
                user_id=user_id,
            )
            
            # Get the LangGraph ReAct agent
            agent = await get_langgraph_react_agent()
            
            # Process the query
            result = await agent.process_query(query, user_id, channel_id, thread_ts)
            
            # Send results to Slack
            await self._send_agent_results_to_slack(
                result=result,
                say=say,
                user_id=user_id,
                channel_id=channel_id,
                thread_ts=thread_ts,
                query=query
            )
            
            logger.info(
                "Query processing completed",
                query=query[:50] + "..." if len(query) > 50 else query,
                user_id=user_id,
                success=result["success"],
            )
            
        except Exception as e:
            logger.error(
                "Query processing failed",
                query=query[:50] + "..." if len(query) > 50 else query,
                user_id=user_id,
                error=str(e),
                exc_info=True,
            )
            
            # Send error message directly
            await self._send_error_message(say, user_id, query, str(e), thread_ts)
    
    async def _send_agent_results_to_slack(
        self,
        result: Dict[str, Any],
        say,
        user_id: str,
        channel_id: str,
        thread_ts: str,
        query: str
    ):
        """Send simple agent results to Slack."""
        try:
            if not result["success"]:
                # Send error message
                await self._send_error_message(say, user_id, query, result["error"], thread_ts)
                return
            
            # Send the agent's response
            response_text = result["response"]
            csv_files = result.get("csv_files", [])
            
            # If there are CSV files, upload them to Slack
            if csv_files:
                for csv_file in csv_files:
                    upload_success = await self._upload_csv_file_with_fallback(
                        csv_file=csv_file,
                        channel_id=channel_id,
                        user_id=user_id,
                        query=query,
                        response_text=response_text,
                        thread_ts=thread_ts,
                        say=say
                    )
            else:
                # Just send the text response
                await say(
                    text=f"<@{user_id}> {response_text}",
                    thread_ts=thread_ts,
                )
            
            logger.info("Agent results sent to Slack successfully")
        
        except Exception as e:
            logger.error(f"Failed to send agent results to Slack: {e}")
            await say(
                text=f"<@{user_id}> I completed your query but encountered an issue sending the results: {str(e)}",
                thread_ts=thread_ts,
            )
    
    async def _upload_csv_file_with_fallback(
        self,
        csv_file: Dict[str, Any],
        channel_id: str,
        user_id: str,
        query: str,
        response_text: str,
        thread_ts: str,
        say
    ) -> bool:
        """Upload CSV file to Slack with fallback mechanisms."""
        import os
        
        try:
            logger.info("Attempting to upload CSV file", 
                       filename=csv_file["filename"], 
                       channel_id=channel_id, 
                       user_id=user_id,
                       filepath=csv_file["filepath"])
            
            # Check if file exists and get size
            if not os.path.exists(csv_file["filepath"]):
                logger.error("CSV file not found", filepath=csv_file["filepath"])
                await say(
                    text=f"<@{user_id}> {response_text}\n\n❌ CSV file was generated but not found on disk.",
                    thread_ts=thread_ts,
                )
                return False
                
            file_size = os.path.getsize(csv_file["filepath"])
            logger.info("File details", filepath=csv_file["filepath"], size_bytes=file_size)
            
            # Try files_upload_v2 first (current recommended method)
            try:
                with open(csv_file["filepath"], 'rb') as file_content:
                    upload_response = await self.app.client.files_upload_v2(
                        channel=channel_id,
                        file=file_content,
                        filename=csv_file["filename"],
                        title=f"Query Results - {query[:50]}{'...' if len(query) > 50 else ''}",
                        initial_comment=f"<@{user_id}> {response_text}",
                        thread_ts=thread_ts,
                    )
                    
                logger.info("CSV file uploaded successfully via files_upload_v2", 
                           filename=csv_file["filename"],
                           response=upload_response)
                
                # Clean up the local CSV file after successful upload
                try:
                    os.remove(csv_file["filepath"])
                    logger.info("CSV file deleted after successful upload", filepath=csv_file["filepath"])
                except Exception as cleanup_error:
                    logger.warning("Failed to delete CSV file after upload", 
                                  filepath=csv_file["filepath"], 
                                  error=str(cleanup_error))
                
                return True
                
            except SlackApiError as e:
                logger.warning("files_upload_v2 failed, trying alternative approach", 
                             error=str(e), 
                             error_code=e.response.get("error"))
                
                # If channel not found, the bot likely doesn't have permission
                if e.response.get("error") == "channel_not_found":
                    await say(
                        text=(f"<@{user_id}> {response_text}\n\n"
                             "❌ I don't have permission to upload files to this channel. "
                             "Please add me to the channel or grant the bot `files:write` permission."),
                        thread_ts=thread_ts,
                    )
                    return False
                
                # For other API errors, try sending as a snippet instead
                await self._send_csv_as_snippet(
                    csv_file=csv_file,
                    channel_id=channel_id,
                    user_id=user_id,
                    query=query,
                    response_text=response_text,
                    thread_ts=thread_ts,
                    say=say
                )
                return True
                
        except Exception as e:
            logger.error("Unexpected error during file upload", 
                       filename=csv_file.get("filename", "unknown"),
                       error=str(e),
                       error_type=type(e).__name__)
            
            await say(
                text=f"<@{user_id}> {response_text}\n\n❌ Upload failed: {str(e)}",
                thread_ts=thread_ts,
            )
            return False
    
    async def _send_csv_as_snippet(
        self,
        csv_file: Dict[str, Any],
        channel_id: str,
        user_id: str,
        query: str,
        response_text: str,
        thread_ts: str,
        say
    ):
        """Send CSV data as a code snippet when file upload fails."""
        try:
            # Read first few rows of CSV to show as preview
            with open(csv_file["filepath"], 'r') as f:
                lines = f.readlines()
                preview = ''.join(lines[:10])  # First 10 lines
                total_lines = len(lines)
            
            snippet_text = f"```csv\n{preview}```"
            if total_lines > 10:
                snippet_text += f"\n\n_Showing first 10 rows of {total_lines} total rows_"
            
            await say(
                text=(f"<@{user_id}> {response_text}\n\n"
                     f"📊 **CSV Data Preview** (File: `{csv_file['filename']}`)\n"
                     f"{snippet_text}\n\n"
                     f"💡 The full CSV data is ready but couldn't be uploaded as a file. "
                     f"Please check bot permissions or contact your admin."),
                thread_ts=thread_ts,
            )
            
            logger.info("CSV sent as snippet fallback", 
                       filename=csv_file["filename"],
                       preview_lines=min(10, total_lines))
            
            # Clean up the local CSV file after sending as snippet
            try:
                os.remove(csv_file["filepath"])
                logger.info("CSV file deleted after sending as snippet", filepath=csv_file["filepath"])
            except Exception as cleanup_error:
                logger.warning("Failed to delete CSV file after sending as snippet", 
                              filepath=csv_file["filepath"], 
                              error=str(cleanup_error))
            
        except Exception as e:
            logger.error("Failed to send CSV as snippet", error=str(e))
            await say(
                text=(f"<@{user_id}> {response_text}\n\n"
                     "❌ Could not upload or display the CSV file. Please try again later."),
                thread_ts=thread_ts,
            )
            
            # Clean up the local CSV file even if snippet sending failed
            try:
                os.remove(csv_file["filepath"])
                logger.info("CSV file deleted after snippet failure", filepath=csv_file["filepath"])
            except Exception as cleanup_error:
                logger.warning("Failed to delete CSV file after snippet failure", 
                              filepath=csv_file["filepath"], 
                              error=str(cleanup_error))
    
    async def _send_error_message(
        self, 
        say, 
        user_id: str, 
        query: str, 
        error: str, 
        thread_ts: str = None
    ):
        """Send error message to Slack."""
        try:
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
                    "Please try rephrasing your question."
                )
            
            await say(
                text=f"❌ <@{user_id}> {user_error}",
                thread_ts=thread_ts,
            )
            
        except Exception as e:
            logger.error(f"Failed to send error message: {e}")
    
    def _extract_query_from_mention(self, text: str) -> str:
        """Extract query text from app mention, removing the bot mention."""
        # Remove @bot mentions using regex
        mention_pattern = r"<@[A-Z0-9]+>"
        clean_text = re.sub(mention_pattern, "", text).strip()
        return clean_text
    
    async def _send_processing_message(self, say, user_id: str, thread_ts: str = None):
        """Send processing acknowledgment message."""
        message = (
            f"🔍 <@{user_id}> I'm processing your query... "
            "This may take a moment while I search through the data."
        )
        
        try:
            await say(text=message, thread_ts=thread_ts)
        except Exception as e:
            logger.error(f"Failed to send processing message: {e}")
    
    async def _send_help_message(self, say, user_id: str, thread_ts: str = None):
        """Send help message to user."""
        help_text = f"""
👋 Hi <@{user_id}>! I'm **OptiBot**, your operations data assistant!

🎯 **I can help you with:**
📊 Performance metrics & KPIs
🚀 Campaign and conversion data  
⚙️ System health and uptime
📈 Operational trends and analytics

💡 **How to use me:**
• @ mention me with your question: `@OptiBot show me yesterday's metrics`
• Send me a direct message with your query
• Reply in threads to continue the conversation

📝 **Example queries:**
• "Show me last week's performance metrics"
• "What were the top converting campaigns yesterday?"
• "Get server uptime stats for the past month"
• "Pull customer engagement data for this quarter"

Just ask me anything about your operational data! ⚡
        """
        
        try:
            await say(text=help_text.strip(), thread_ts=thread_ts)
        except Exception as e:
            logger.error(f"Failed to send help message: {e}")


# Global service instance
_simple_slack_service: Optional[SimpleSlackSocketService] = None


async def get_simple_slack_service() -> SimpleSlackSocketService:
    """Get or create simple Slack Socket Mode service instance."""
    global _simple_slack_service
    
    if _simple_slack_service is None:
        _simple_slack_service = SimpleSlackSocketService()
        await _simple_slack_service.initialize()
    
    return _simple_slack_service