# OptiBot - Simplified Version

This is a simplified version of OptiBot that runs without Redis or PostgreSQL dependencies. It processes all queries directly in the Socket Mode handler.

## Quick Start

### Option 1: Docker (Recommended)
```bash
# Build and run with Docker Compose
docker-compose -f docker-compose-simple.yml up --build
```

### Option 2: Local Python
```bash
# Install dependencies
pip install -r requirements-simple.txt

# Run the bot
python run-simple.py
```

## Environment Variables

Create a `.env` file with:

```bash
# Slack Configuration (Required)
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token  # For Socket Mode
SLACK_SIGNING_SECRET=your-signing-secret

# OpenAI Configuration (Required)
OPENAI_API_KEY=your-openai-api-key

# MCP Configuration (Required)
MCP_SERVER_URL=http://your-mcp-server:3000

# Optional Settings
LOG_LEVEL=INFO
ENVIRONMENT=development
DEBUG=true
```

## What's Different in the Simplified Version

### Removed Components:
- ❌ Redis task queuing
- ❌ PostgreSQL query storage  
- ❌ Background workers
- ❌ FastAPI web server
- ❌ Complex health checks

### Simplified Architecture:
- ✅ Direct query processing in Socket Mode handler
- ✅ Synchronous workflow execution
- ✅ File-based temporary storage only
- ✅ Single container deployment

## Architecture

```
User @ mentions bot in Slack
         ↓
   Socket Mode Handler
         ↓
  Direct Query Processing
         ↓
   LangGraph Workflow
         ↓
    MCP Data Retrieval
         ↓
   CSV Generation & Upload
```

## Files Structure

- `run-simple.py` - Main entry point
- `src/workers/simple_socket_worker.py` - Simple worker
- `src/services/slack_socket_simple.py` - Direct processing service
- `requirements-simple.txt` - Minimal dependencies
- `Dockerfile.simple` - Lightweight Docker image
- `docker-compose-simple.yml` - Single container setup

## Usage

1. **@ Mention in channels**: `@OptiBot show me yesterday's metrics`
2. **Direct messages**: Send queries directly to the bot
3. **Thread replies**: Continue conversations in threads

## Limitations

- Processes one query at a time (no concurrency)
- No query history storage
- No advanced error recovery
- No background processing

Perfect for: Development, testing, small teams, simple deployments