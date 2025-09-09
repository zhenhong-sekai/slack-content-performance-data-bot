"""Slack Socket Mode client service."""

import asyncio
import re
from typing import Any, Dict, List, Optional

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_sdk.errors import SlackApiError

from src.config import settings
from src.services.queue import get_task_queue
from src.utils.logging import get_logger

logger = get_logger(__name__)


class SlackSocketService:
    """Slack Socket Mode service for handling real-time events."""
    
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
            
            logger.info(
                "Slack Socket Mode service initialized",
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
        
        logger.info("Starting Slack Socket Mode handler...")
        await self._handler.start_async()
    
    async def stop(self):
        """Stop the Socket Mode handler."""
        if self._handler:
            await self._handler.close_async()
            logger.info("Slack Socket Mode handler stopped")
    
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
        
        # Send processing acknowledgment
        await self._send_processing_message(say, user_id, thread_ts)
        
        # Queue the query for processing
        await self._queue_query(
            query=clean_text,
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=thread_ts or message_ts,  # Use thread_ts if available, otherwise message_ts
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
        
        # Queue the query for processing
        await self._queue_query(
            query=text,
            user_id=user_id,
            channel_id=channel_id,
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
        
        # Check if the original thread message involved our bot
        # We'll process any message in a thread where bot was previously active
        
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
        
        # Queue the query for processing
        await self._queue_query(
            query=text,
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
        )
    
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
            "This may take a moment while I search through the data. "
            "I'll send you the results as a CSV file when ready!"
        )
        
        try:
            await say(
                text=message,
                thread_ts=thread_ts,
            )
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

Just ask me anything about your operational data and I'll get you a CSV file with the results! ⚡
        """
        
        try:
            await say(
                text=help_text.strip(),
                thread_ts=thread_ts,
            )
        except Exception as e:
            logger.error(f"Failed to send help message: {e}")
    
    async def _queue_query(
        self, 
        query: str, 
        user_id: str, 
        channel_id: str, 
        thread_ts: str = None
    ):
        """Queue a query for agent processing."""
        try:
            queue = await get_task_queue()
            
            task_id = await queue.enqueue(
                task_type="process_agent_query",
                payload={
                    "query": query,
                    "user_id": user_id,
                    "channel_id": channel_id,
                    "thread_ts": thread_ts,
                },
                priority=1,  # High priority for user queries
            )
            
            logger.info(
                "Query queued for agent processing",
                task_id=task_id,
                query=query[:100] + "..." if len(query) > 100 else query,
                user_id=user_id,
                channel_id=channel_id,
                thread_ts=thread_ts,
            )
            
        except Exception as e:
            logger.error(f"Failed to queue query: {e}")
    
    @property
    def bot_user_id(self) -> Optional[str]:
        """Get bot user ID."""
        return self._bot_user_id
    
    async def send_message(
        self,
        channel_id: str,
        text: str,
        thread_ts: Optional[str] = None,
        blocks: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """Send a message to a Slack channel."""
        try:
            response = await self.app.client.chat_postMessage(
                channel=channel_id,
                text=text,
                blocks=blocks,
                thread_ts=thread_ts,
                unfurl_links=False,
                unfurl_media=False,
            )
            
            logger.info(
                "Message sent successfully",
                channel_id=channel_id,
                thread_ts=thread_ts,
                message_ts=response.get("ts"),
            )
            
            return response.data
            
        except SlackApiError as e:
            logger.error(
                "Failed to send message",
                channel_id=channel_id,
                error=str(e),
                error_code=e.response.get("error"),
            )
            raise
    
    async def upload_file(
        self,
        file_path: str,
        channel_id: str,
        thread_ts: Optional[str] = None,
        title: Optional[str] = None,
        initial_comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upload a file to Slack."""
        try:
            with open(file_path, 'rb') as file_content:
                response = await self.app.client.files_upload_v2(
                    channel=channel_id,
                    file=file_content,
                    filename=file_path.split('/')[-1],
                    title=title,
                    initial_comment=initial_comment,
                    thread_ts=thread_ts,
                )
            
            logger.info(
                "File uploaded successfully",
                file_path=file_path,
                channel_id=channel_id,
                file_id=response.get("file", {}).get("id"),
                thread_ts=thread_ts,
            )
            
            return response.data
            
        except SlackApiError as e:
            logger.error(
                "Failed to upload file",
                file_path=file_path,
                channel_id=channel_id,
                error=str(e),
                error_code=e.response.get("error"),
            )
            raise
        except FileNotFoundError:
            logger.error(f"File not found: {file_path}")
            raise
    
    def create_blocks_for_results(
        self,
        summary: str,
        csv_path: str,
        query: str,
        row_count: int = None,
    ) -> List[Dict]:
        """Create Slack blocks for query results."""
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"✅ *Query Results Ready*\n{summary}"
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"📊 Query: _{query[:100]}{'...' if len(query) > 100 else ''}_"
                    }
                ]
            }
        ]
        
        if row_count is not None:
            blocks.append({
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"📈 Found {row_count:,} records"
                    }
                ]
            })
        
        return blocks
    
    def create_error_blocks(self, error_message: str, query: str) -> List[Dict]:
        """Create Slack blocks for error messages."""
        return [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"❌ *Query Failed*\n{error_message}"
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"📊 Query: _{query[:100]}{'...' if len(query) > 100 else ''}_"
                    }
                ]
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "💡 *Tips:*\n• Try being more specific about what data you need\n• Check your date ranges and filters\n• Continue the conversation in this thread for clarification"
                }
            }
        ]


# Global service instance
_slack_socket_service: Optional[SlackSocketService] = None


async def get_slack_socket_service() -> SlackSocketService:
    """Get or create Slack Socket Mode service instance."""
    global _slack_socket_service
    
    if _slack_socket_service is None:
        _slack_socket_service = SlackSocketService()
        await _slack_socket_service.initialize()
    
    return _slack_socket_service