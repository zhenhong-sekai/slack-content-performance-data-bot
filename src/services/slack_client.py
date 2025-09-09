"""Slack client service for API interactions."""

import asyncio
from typing import Any, Dict, List, Optional

from slack_bolt.async_app import AsyncApp
from slack_bolt.error import BoltError
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

from src.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class SlackService:
    """Service for Slack API interactions."""
    
    def __init__(self):
        self.app = AsyncApp(
            token=settings.slack_bot_token,
            signing_secret=settings.slack_signing_secret,
        )
        self.client: AsyncWebClient = self.app.client
        self._bot_user_id: Optional[str] = None
    
    async def initialize(self):
        """Initialize Slack service and get bot info."""
        try:
            # Get bot user ID
            auth_response = await self.client.auth_test()
            self._bot_user_id = auth_response["user_id"]
            
            logger.info(
                "Slack service initialized",
                bot_user_id=self._bot_user_id,
                team_id=auth_response.get("team_id"),
            )
        
        except SlackApiError as e:
            logger.error(f"Failed to initialize Slack service: {e}")
            raise
    
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
            response = await self.client.chat_postMessage(
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
            # Use files_upload_v2 for better file handling
            with open(file_path, 'rb') as file_content:
                response = await self.client.files_upload_v2(
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
    
    async def send_typing_indicator(self, channel_id: str) -> None:
        """Send typing indicator to show bot is working."""
        
        try:
            # Slack doesn't have a direct typing indicator for bots,
            # but we can use a temporary message approach
            temp_response = await self.client.chat_postMessage(
                channel=channel_id,
                text="🔍 Processing your query...",
            )
            
            # Delete the temporary message after a short delay
            await asyncio.sleep(1)
            
            await self.client.chat_delete(
                channel=channel_id,
                ts=temp_response["ts"],
            )
        
        except SlackApiError as e:
            logger.warning(f"Failed to send typing indicator: {e}")
            # Don't raise - this is not critical
    
    async def update_message(
        self,
        channel_id: str,
        message_ts: str,
        text: str,
        blocks: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """Update an existing message."""
        
        try:
            response = await self.client.chat_update(
                channel=channel_id,
                ts=message_ts,
                text=text,
                blocks=blocks,
            )
            
            logger.info(
                "Message updated successfully",
                channel_id=channel_id,
                message_ts=message_ts,
            )
            
            return response.data
        
        except SlackApiError as e:
            logger.error(
                "Failed to update message",
                channel_id=channel_id,
                message_ts=message_ts,
                error=str(e),
            )
            raise
    
    async def add_reaction(
        self,
        channel_id: str,
        message_ts: str,
        reaction: str,
    ) -> Dict[str, Any]:
        """Add a reaction to a message."""
        
        try:
            response = await self.client.reactions_add(
                channel=channel_id,
                timestamp=message_ts,
                name=reaction,
            )
            
            logger.debug(
                "Reaction added",
                channel_id=channel_id,
                message_ts=message_ts,
                reaction=reaction,
            )
            
            return response.data
        
        except SlackApiError as e:
            logger.warning(
                "Failed to add reaction",
                channel_id=channel_id,
                message_ts=message_ts,
                reaction=reaction,
                error=str(e),
            )
            # Don't raise - reactions are not critical
            return {}
    
    async def get_user_info(self, user_id: str) -> Dict[str, Any]:
        """Get user information."""
        
        try:
            response = await self.client.users_info(user=user_id)
            return response.data["user"]
        
        except SlackApiError as e:
            logger.error(f"Failed to get user info for {user_id}: {e}")
            return {"id": user_id, "name": "Unknown User"}
    
    async def get_channel_info(self, channel_id: str) -> Dict[str, Any]:
        """Get channel information."""
        
        try:
            response = await self.client.conversations_info(channel=channel_id)
            return response.data["channel"]
        
        except SlackApiError as e:
            logger.error(f"Failed to get channel info for {channel_id}: {e}")
            return {"id": channel_id, "name": "Unknown Channel"}
    
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
        
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "📥 Download CSV"
                    },
                    "style": "primary",
                    "url": f"attachment://{csv_path.split('/')[-1]}"
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
                    "text": "💡 *Tips:*\n• Try being more specific about what data you need\n• Check your date ranges and filters\n• Ask for help with `/query-data help`"
                }
            }
        ]


# Global service instance
_slack_service: Optional[SlackService] = None


async def get_slack_service() -> SlackService:
    """Get or create Slack service instance."""
    global _slack_service
    
    if _slack_service is None:
        _slack_service = SlackService()
        await _slack_service.initialize()
    
    return _slack_service


def get_slack_service_sync() -> SlackService:
    """Get Slack service instance synchronously (for use in handlers)."""
    global _slack_service
    
    if _slack_service is None:
        _slack_service = SlackService()
        # Note: initialization should happen elsewhere in async context
    
    return _slack_service