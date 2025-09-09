"""Slack webhook endpoints."""

import json
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from src.config import settings
from src.services.queue import get_task_queue
from src.utils.logging import get_logger
from src.utils.slack_validator import validate_slack_request

logger = get_logger(__name__)

router = APIRouter()


@router.post("/events")
async def handle_slack_events(request: Request):
    """Handle Slack event subscriptions."""
    
    # Validate request signature
    body = await request.body()
    
    if not await validate_slack_request(
        body=body,
        timestamp=request.headers.get("X-Slack-Request-Timestamp", ""),
        signature=request.headers.get("X-Slack-Signature", ""),
        signing_secret=settings.slack_signing_secret,
    ):
        logger.warning(
            "Invalid Slack request signature",
            headers=dict(request.headers),
        )
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    try:
        payload = json.loads(body.decode())
    except json.JSONDecodeError:
        logger.error("Invalid JSON in Slack event payload")
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    event_type = payload.get("type")
    
    logger.info(
        "Slack event received",
        event_type=event_type,
        team_id=payload.get("team_id"),
        event_id=payload.get("event_id"),
    )
    
    # Handle URL verification challenge
    if event_type == "url_verification":
        challenge = payload.get("challenge")
        logger.info("URL verification challenge received", challenge=challenge)
        return JSONResponse(content={"challenge": challenge})
    
    # Handle event callbacks
    if event_type == "event_callback":
        event_data = payload.get("event", {})
        event_subtype = event_data.get("type")
        
        # Ignore bot messages and messages from ourselves
        if event_data.get("bot_id") or event_data.get("subtype") == "bot_message":
            return JSONResponse(content={"status": "ignored"})
        
        # Only handle relevant events
        if event_subtype in ["app_mention", "message"]:
            # Queue for async processing
            queue = await get_task_queue()
            
            task_id = await queue.enqueue(
                task_type="process_slack_event",
                payload=payload,
                priority=2,  # High priority for user interactions
            )
            
            logger.info(
                "Slack event queued",
                task_id=task_id,
                event_subtype=event_subtype,
                channel=event_data.get("channel"),
                user=event_data.get("user"),
            )
        
        return JSONResponse(content={"status": "ok"})
    
    # Handle other event types
    logger.info(f"Unhandled Slack event type: {event_type}")
    return JSONResponse(content={"status": "ignored"})


@router.post("/commands")
async def handle_slack_commands(request: Request):
    """Handle Slack slash commands."""
    
    # Validate request signature
    body = await request.body()
    
    if not await validate_slack_request(
        body=body,
        timestamp=request.headers.get("X-Slack-Request-Timestamp", ""),
        signature=request.headers.get("X-Slack-Signature", ""),
        signing_secret=settings.slack_signing_secret,
    ):
        logger.warning("Invalid Slack command signature")
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    # Parse form data
    form_data = {}
    try:
        form_str = body.decode()
        for pair in form_str.split("&"):
            if "=" in pair:
                key, value = pair.split("=", 1)
                form_data[key] = value.replace("+", " ")
        
        # URL decode values
        import urllib.parse
        for key, value in form_data.items():
            form_data[key] = urllib.parse.unquote(value)
    
    except Exception as e:
        logger.error(f"Failed to parse command form data: {e}")
        raise HTTPException(status_code=400, detail="Invalid form data")
    
    command = form_data.get("command")
    text = form_data.get("text", "").strip()
    user_id = form_data.get("user_id")
    channel_id = form_data.get("channel_id")
    
    logger.info(
        "Slack command received",
        command=command,
        text=text[:100] + "..." if len(text) > 100 else text,
        user_id=user_id,
        channel_id=channel_id,
    )
    
    # Handle supported commands
    if command == "/query-data":
        if not text:
            return JSONResponse(content={
                "response_type": "ephemeral",
                "text": (
                    "👋 Hi! I'm your data query assistant.\n\n"
                    "Usage: `/query-data <your question>`\n\n"
                    "Examples:\n"
                    "• `/query-data show me last week's performance metrics`\n"
                    "• `/query-data what were the top campaigns yesterday?`\n"
                    "• `/query-data get user engagement data for the past month`\n\n"
                    "I'll process your query and send you the results as a CSV file!"
                )
            })
        
        # Queue command for processing
        queue = await get_task_queue()
        
        task_id = await queue.enqueue(
            task_type="process_slack_command",
            payload=form_data,
            priority=2,
        )
        
        logger.info(
            "Slack command queued",
            task_id=task_id,
            command=command,
            user_id=user_id,
        )
        
        return JSONResponse(content={
            "response_type": "ephemeral",
            "text": "🔍 Processing your query... I'll send you the results shortly!"
        })
    
    else:
        logger.warning(f"Unknown command: {command}")
        return JSONResponse(content={
            "response_type": "ephemeral",
            "text": f"Unknown command: {command}"
        })


@router.post("/interactive")
async def handle_slack_interactive(request: Request):
    """Handle Slack interactive components (buttons, menus, etc.)."""
    
    # Validate request signature
    body = await request.body()
    
    if not await validate_slack_request(
        body=body,
        timestamp=request.headers.get("X-Slack-Request-Timestamp", ""),
        signature=request.headers.get("X-Slack-Signature", ""),
        signing_secret=settings.slack_signing_secret,
    ):
        logger.warning("Invalid Slack interactive signature")
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    # Parse payload from form data
    try:
        form_str = body.decode()
        payload_str = None
        
        for pair in form_str.split("&"):
            if pair.startswith("payload="):
                import urllib.parse
                payload_str = urllib.parse.unquote(pair[8:])
                break
        
        if not payload_str:
            raise ValueError("No payload found")
        
        payload = json.loads(payload_str)
    
    except Exception as e:
        logger.error(f"Failed to parse interactive payload: {e}")
        raise HTTPException(status_code=400, detail="Invalid payload")
    
    interaction_type = payload.get("type")
    user_id = payload.get("user", {}).get("id")
    
    logger.info(
        "Slack interactive component",
        type=interaction_type,
        user_id=user_id,
        actions=len(payload.get("actions", [])),
    )
    
    # Handle different interaction types
    if interaction_type == "block_actions":
        # Handle button clicks, menu selections, etc.
        actions = payload.get("actions", [])
        
        for action in actions:
            action_id = action.get("action_id")
            
            if action_id == "download_csv":
                # Handle CSV download request
                return JSONResponse(content={
                    "text": "📥 Your CSV file should have been uploaded above. Click on it to download!"
                })
    
    return JSONResponse(content={"status": "ok"})


@router.get("/oauth/callback")
async def slack_oauth_callback(request: Request):
    """Handle Slack OAuth callback (for app installation)."""
    
    code = request.query_params.get("code")
    error = request.query_params.get("error")
    
    if error:
        logger.error(f"Slack OAuth error: {error}")
        return JSONResponse(
            content={"error": f"OAuth failed: {error}"},
            status_code=400
        )
    
    if not code:
        logger.error("No code provided in OAuth callback")
        return JSONResponse(
            content={"error": "No authorization code provided"},
            status_code=400
        )
    
    logger.info("Slack OAuth callback received", code=code[:10] + "...")
    
    # In a full implementation, you would:
    # 1. Exchange the code for access tokens
    # 2. Store the tokens securely
    # 3. Install the app for the workspace
    
    return JSONResponse(content={
        "message": "App installation initiated. Please complete the setup process."
    })