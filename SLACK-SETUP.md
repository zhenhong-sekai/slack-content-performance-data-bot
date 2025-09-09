# 🤖 OptiBot - Slack Socket Mode Setup Guide

## Overview

OptiBot uses **Slack Socket Mode** for real-time communication, which provides several advantages:
- ✅ **Threaded Conversations**: Full support for multi-turn conversations
- ✅ **No Public Endpoints**: No need to expose webhooks to the internet
- ✅ **Real-time**: Instant message processing via WebSocket connection
- ✅ **Firewall Friendly**: Works behind corporate firewalls

## Quick Setup with App Manifest

### Step 1: Create Slack App with Manifest

1. Go to https://api.slack.com/apps
2. Click **"Create New App"**
3. Choose **"From an app manifest"**
4. Select your workspace
5. Copy and paste the contents of `slack-app-manifest.json` from this repository
6. Click **"Create"**

The manifest will automatically configure:
- ✅ Socket Mode enabled
- ✅ Required OAuth scopes
- ✅ Event subscriptions
- ✅ Bot user settings

### Step 2: Get Your Tokens

After creating the app, get these tokens:

#### Bot Token (OAuth & Permissions)
1. Go to **"OAuth & Permissions"** in the left sidebar
2. Copy the **"Bot User OAuth Token"** (starts with `xoxb-`)

#### App-Level Token (Socket Mode)
1. Go to **"Basic Information"** in the left sidebar  
2. Scroll down to **"App-Level Tokens"**
3. Click **"Generate Token and Scopes"**
4. Token Name: `socket-mode-token`
5. Add Scope: `connections:write`
6. Click **"Generate"**
7. Copy the token (starts with `xapp-`)

### Step 3: Install App to Workspace

1. Go to **"Install App"** in the left sidebar
2. Click **"Install to Workspace"**
3. Review permissions and click **"Allow"**

### Step 4: Configure Environment

Update your `.env` file:

```bash
# Slack Configuration (Socket Mode)
SLACK_BOT_TOKEN=xoxb-your-bot-token-here
SLACK_SIGNING_SECRET=your-signing-secret-here  
SLACK_APP_TOKEN=xapp-your-app-token-here

# Other required settings...
OPENAI_API_KEY=sk-your-openai-api-key-here
MCP_SERVER_URL=http://localhost:3000
SECRET_KEY=your-secret-key-here
JWT_SECRET_KEY=your-jwt-secret-key-here
```

---

## Manual Setup (Alternative)

If you prefer manual setup instead of using the app manifest:

### Step 1: Create Basic App

1. Go to https://api.slack.com/apps
2. Click **"Create New App"** → **"From scratch"**
3. App Name: **OptiBot**
4. Pick your workspace

### Step 2: Enable Socket Mode

1. Go to **"Socket Mode"** in the left sidebar
2. Toggle **"Enable Socket Mode"** to **ON**
3. Generate an App-Level Token:
   - Token Name: `socket-mode-token`
   - Scope: `connections:write`
   - Copy the token (starts with `xapp-`)

### Step 3: Configure OAuth Scopes

1. Go to **"OAuth & Permissions"**
2. Add these **Bot Token Scopes**:
   - `app_mentions:read` - See @ mentions
   - `channels:history` - Read channel messages  
   - `groups:history` - Read private channel messages
   - `im:history` - Read direct messages
   - `mpim:history` - Read group DMs
   - `chat:write` - Send messages
   - `chat:write.public` - Send messages to channels bot isn't in
   - `files:write` - Upload files
   - `users:read` - Get user information

### Step 4: Configure Event Subscriptions

1. Go to **"Event Subscriptions"**
2. Toggle **"Enable Events"** to **ON**
3. Subscribe to these **Bot Events**:
   - `app_mention` - Bot is @ mentioned
   - `message.channels` - Messages in channels
   - `message.groups` - Messages in private channels  
   - `message.im` - Direct messages
   - `message.mpim` - Group direct messages

### Step 5: Configure App Home

1. Go to **"App Home"**
2. Enable **"Messages Tab"**
3. Allow users to send DMs: **ON**

### Step 6: Install App

1. Go to **"Install App"**
2. Click **"Install to Workspace"**
3. Copy the **Bot User OAuth Token** (starts with `xoxb-`)

---

## Testing Your Setup

### Step 1: Start the Bot

```bash
# Development mode
./scripts/start-dev.sh

# Or manually
docker-compose up --build -d
```

### Step 2: Test in Slack

#### @ Mention Test
In any channel where OptiBot is added:
```
@OptiBot hello
```

Expected response: Help message with usage instructions

#### Direct Message Test
Send a DM to OptiBot:
```
show me some test data
```

Expected response: Processing message, then help or error response

#### Thread Test
1. @ mention OptiBot in a channel
2. Reply in the thread with another query
3. OptiBot should respond in the same thread

### Step 3: Check Logs

```bash
# Check Socket Mode worker
docker-compose logs socket-mode-worker

# Check agent processor
docker-compose logs agent-processor

# Check main app
docker-compose logs slack-bot
```

---

## Troubleshooting

### Common Issues

#### 1. "Invalid token" or authentication errors
- ✅ Verify `SLACK_BOT_TOKEN` starts with `xoxb-`
- ✅ Verify `SLACK_APP_TOKEN` starts with `xapp-`
- ✅ Check tokens are copied correctly (no extra spaces)

#### 2. Bot doesn't respond to @ mentions
- ✅ Ensure bot is added to the channel: `/invite @OptiBot`
- ✅ Check `app_mention` event is subscribed
- ✅ Verify Socket Mode worker is running

#### 3. No direct message responses
- ✅ Check `message.im` event is subscribed
- ✅ Verify "Messages Tab" is enabled in App Home
- ✅ Ensure `im:history` scope is granted

#### 4. Socket connection issues
- ✅ Check `connections:write` scope on App-Level Token
- ✅ Verify network allows WebSocket connections
- ✅ Check Socket Mode worker logs for connection errors

#### 5. Threaded conversations not working
- ✅ Ensure all message event types are subscribed
- ✅ Check that `thread_ts` is being processed correctly
- ✅ Verify bot has `channels:history` scope

### Debug Commands

```bash
# Test Socket Mode connection
docker-compose exec socket-mode-worker python -c "
import asyncio
from src.services.slack_socket_client import get_slack_socket_service
async def test():
    service = await get_slack_socket_service()
    print(f'Bot User ID: {service.bot_user_id}')
asyncio.run(test())
"

# Check environment variables
docker-compose exec slack-bot env | grep SLACK

# Test MCP connection  
docker-compose exec agent-processor python -c "
import asyncio
from src.agents.nodes.data_retrieval import test_mcp_connectivity
print(asyncio.run(test_mcp_connectivity()))
"
```

---

## Production Considerations

### Security
- 🔒 Store tokens in secure environment variables
- 🔒 Use app-level tokens with minimal scopes
- 🔒 Rotate tokens regularly
- 🔒 Monitor for suspicious activity

### Scaling
- 📈 Socket Mode supports one connection per app
- 📈 Scale agent processors, not Socket Mode workers
- 📈 Use Redis for distributed task processing
- 📈 Monitor connection health and reconnect logic

### Monitoring
- 📊 Track Socket Mode connection status
- 📊 Monitor message processing latency
- 📊 Alert on connection failures
- 📊 Log all user interactions for debugging

---

## Usage Examples

### Basic Queries
```
@OptiBot show me yesterday's metrics
@OptiBot what were the top campaigns last week?  
@OptiBot get server performance data for today
```

### Threaded Conversations
```
User: @OptiBot show me Q4 revenue data
OptiBot: [Uploads Q4_revenue.csv] Here's your Q4 revenue data with 1,234 records...

User: (in thread) Can you break that down by product line?
OptiBot: [Uploads Q4_revenue_by_product.csv] Here's the breakdown by product line...

User: (in thread) What about compared to Q3?
OptiBot: [Uploads Q3_vs_Q4_comparison.csv] Here's the Q3 vs Q4 comparison...
```

### Direct Messages
```
User: (DM) show me today's conversion rates
OptiBot: [Uploads conversion_rates.csv] Here are today's conversion rates...

User: (DM) what about by traffic source?  
OptiBot: [Uploads conversion_by_source.csv] Here's the breakdown by traffic source...
```

---

## Support

If you encounter issues:

1. 📋 Check the logs first: `docker-compose logs`
2. 🔍 Review this setup guide
3. 🧪 Test with simple queries first
4. 📞 Contact the development team with specific error messages

**Happy querying with OptiBot!** 🚀