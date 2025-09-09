"""Slack request signature validation."""

import hashlib
import hmac
import time
from typing import Optional

from src.utils.logging import get_logger

logger = get_logger(__name__)


async def validate_slack_request(
    body: bytes,
    timestamp: str,
    signature: str,
    signing_secret: str,
    max_age_seconds: int = 300,  # 5 minutes
) -> bool:
    """Validate Slack request signature."""
    
    try:
        # Check timestamp to prevent replay attacks
        if not timestamp:
            logger.warning("Missing timestamp header")
            return False
        
        request_timestamp = int(timestamp)
        current_timestamp = int(time.time())
        
        if abs(current_timestamp - request_timestamp) > max_age_seconds:
            logger.warning(
                "Request timestamp too old",
                request_timestamp=request_timestamp,
                current_timestamp=current_timestamp,
                age=abs(current_timestamp - request_timestamp),
            )
            return False
        
        # Check signature
        if not signature:
            logger.warning("Missing signature header")
            return False
        
        if not signature.startswith("v0="):
            logger.warning("Invalid signature format")
            return False
        
        # Create signature
        sig_basestring = f"v0:{timestamp}:".encode() + body
        expected_signature = "v0=" + hmac.new(
            signing_secret.encode(),
            sig_basestring,
            hashlib.sha256
        ).hexdigest()
        
        # Compare signatures
        if not hmac.compare_digest(signature, expected_signature):
            logger.warning("Signature mismatch")
            return False
        
        return True
    
    except Exception as e:
        logger.error(f"Signature validation error: {e}")
        return False


def extract_bot_mention(text: str, bot_user_id: Optional[str] = None) -> tuple[bool, str]:
    """Extract bot mention from message text and return cleaned text."""
    
    import re
    
    # Look for @bot mentions
    mention_pattern = r"<@([A-Z0-9]+)>"
    mentions = re.findall(mention_pattern, text)
    
    # Check if bot is mentioned
    is_mentioned = bot_user_id in mentions if bot_user_id else len(mentions) > 0
    
    # Remove all mentions from text
    clean_text = re.sub(mention_pattern, "", text).strip()
    
    return is_mentioned, clean_text