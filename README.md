# Slack Content Performance Data Bot

A modern Slack bot that queries BigQuery data using LangGraph ReAct agents and returns results as downloadable CSV files.

## 🚀 Features

- 🤖 **LangGraph ReAct Agent**: Modern AI-powered query processing with direct reasoning
- 📊 **BigQuery Integration**: Connects to BigQuery via MCP (Model Context Protocol) server
- 📋 **Smart CSV Generation**: Automatically creates downloadable CSV files from query results
- 💬 **Slack Socket Mode**: Real-time interaction via @ mentions, DMs, and thread replies
- 🔄 **Error Recovery**: Automatic datetime casting and robust error handling
- 🧹 **File Management**: Auto-cleanup of generated files after upload
- ⚡ **Direct Query Processing**: No unnecessary analysis steps - agent decides actions directly

## Quick Start

### Prerequisites

- Python 3.8+
- Slack app with Socket Mode enabled
- BigQuery MCP server running
- OpenAI-compatible API access

### Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd slack_content_performance_data_bot
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your actual configuration
```

4. Configure environment variables:
```bash
# Create .env file with your configuration
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_SIGNING_SECRET=your-signing-secret  
SLACK_APP_TOKEN=xapp-your-app-token
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-4o
MCP_SERVER_URL=http://localhost:3000
TEMP_FILE_PATH=/tmp/slack_bot_files
```

5. Run the application:
```bash
python -m src.main
```

### Slack App Setup

1. Create a new Slack app at https://api.slack.com/apps
2. Configure bot permissions:
   - `app_mentions:read`
   - `chat:write`
   - `files:write`
   - `im:read`
   - `im:write`
3. Enable Socket Mode and generate app-level token
4. Install the app to your workspace
5. Copy bot token, signing secret, and app token to your `.env` file

## Usage

OptiBot works entirely through **@ mentions** and supports **threaded conversations**:

### @ Mentions in Channels
```
@OptiBot show me last week's performance metrics
@OptiBot what were the top performing campaigns yesterday?
@OptiBot get server uptime stats for the past month
```

### Direct Messages
```
show me customer engagement data for this quarter
what's our conversion rate by channel?
pull yesterday's system performance metrics
```

### Threaded Conversations
OptiBot supports follow-up questions in threads:
```
@OptiBot show me last week's metrics
  ↳ can you break that down by channel?
  ↳ what about compared to the previous week?
  ↳ show me the top 5 performing campaigns
```

## 🏗 Architecture

```
User Query → LangGraph ReAct Agent → MCP BigQuery Server → CSV Generation → Slack Upload
```

### Core Components

- **LangGraph ReAct Agent** (`src/agents/langgraph_react_agent.py`)
  - Direct query-to-action reasoning (no analysis overhead)
  - Tool calling: `list_tables` → `describe_table` → `execute_query` → `save_as_csv`
  - Automatic datetime serialization fixes
  
- **Slack Socket Service** (`src/services/slack_socket_simple.py`)
  - Handle @ mentions, DMs, and thread replies
  - File upload with fallback mechanisms
  - Real-time processing feedback

- **MCP Integration**
  - BigQuery tools via Model Context Protocol
  - Streaming HTTP transport for performance
  - Auto-reconnection on every query

### Agent Flow

1. **Agent Node**: Direct reasoning from user query
2. **Tools Node**: Execute BigQuery operations
3. **Process Results**: Handle CSV creation and file management

**Tool Sequence:**
```python
list_tables()        # Discover available tables
↓
describe_table()     # Understand table structure
↓  
execute_query()      # Run SQL query with auto-fixes
↓
save_as_csv()        # Create downloadable file (only if data exists)
```

## Development

### Setup Development Environment

```bash
pip install -r requirements-dev.txt
pre-commit install
```

### Run Tests

```bash
pytest
```

### Code Quality

```bash
black src tests
ruff check src tests
mypy src
```

### Docker Development

```bash
docker-compose up -d
```

## Configuration

Key environment variables:

| Variable | Description | Required |
|----------|-------------|----------|
| `SLACK_BOT_TOKEN` | Slack bot token | Yes |
| `SLACK_SIGNING_SECRET` | Slack signing secret | Yes |
| `OPENAI_API_KEY` | OpenAI API key | Yes |
| `MCP_SERVER_URL` | MCP server endpoint | Yes |
| `REDIS_URL` | Redis connection URL | Yes |

See `.env.example` for full configuration options.

## API Documentation

When running locally, visit:
- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

## Deployment

### Docker

```bash
docker build -t slack-data-bot .
docker run -d --env-file .env slack-data-bot
```

### Production

See `docs/deployment-guide.md` for production deployment instructions.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## License

MIT License - see LICENSE file for details.

## Support

- 📖 [User Guide](docs/user-guide.md)
- 🔧 [API Reference](docs/api-reference.md)
- 🚨 [Troubleshooting](docs/troubleshooting.md)
- 🐛 [Issues](https://github.com/company/slack-data-query-bot/issues)