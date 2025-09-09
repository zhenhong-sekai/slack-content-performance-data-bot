# 🚀 Slack Data Query Bot - Deployment Guide

## Quick Start

### Prerequisites
- Docker & Docker Compose installed
- Your custom MCP server running and accessible
- Slack app created with proper permissions

### 1. Clone and Setup
```bash
git clone <repository-url>
cd slack_content_performance_data_bot
```

### 2. Configure Environment
```bash
# Copy environment template
cp .env.example .env

# Edit with your actual configuration
vim .env
```

Required environment variables:
```bash
# Slack Configuration
SLACK_BOT_TOKEN=xoxb-your-bot-token-here
SLACK_SIGNING_SECRET=your-signing-secret-here

# OpenAI Configuration
OPENAI_API_KEY=sk-your-openai-api-key-here

# MCP Server Configuration
MCP_SERVER_URL=http://localhost:3000
```

### 3. Development Deployment
```bash
# Start all services
./scripts/start-dev.sh

# Or manually:
docker-compose up --build -d
```

Services will be available at:
- **Slack Bot API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health
- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3000 (admin/admin)

### 4. Production Deployment
```bash
# Create production environment file
cp .env.example .env.production
# Edit with production values

# Deploy to production
./scripts/deploy-prod.sh
```

## Architecture Overview

```mermaid
graph TB
    subgraph "External"
        S[Slack Platform]
        M[Custom MCP Server]
    end
    
    subgraph "Load Balancer"
        N[Nginx]
    end
    
    subgraph "Application Layer"
        A1[FastAPI App 1]
        A2[FastAPI App 2]
        A3[FastAPI App 3]
    end
    
    subgraph "Workers"
        W1[Slack Processor]
        W2[Agent Processor 1]
        W3[Agent Processor 2]
    end
    
    subgraph "Data Layer"
        R[Redis Queue]
        P[PostgreSQL]
        F[File Storage]
    end
    
    subgraph "Monitoring"
        PR[Prometheus]
        G[Grafana]
    end
    
    S --> N
    N --> A1
    N --> A2
    N --> A3
    
    A1 --> R
    A2 --> R
    A3 --> R
    
    R --> W1
    R --> W2
    R --> W3
    
    W2 --> M
    W3 --> M
    
    W2 --> F
    W3 --> F
    
    A1 --> P
    W1 --> S
    W2 --> S
    W3 --> S
    
    A1 --> PR
    PR --> G
```

## Component Details

### FastAPI Application
- **Purpose**: Main web server handling Slack webhooks
- **Scaling**: 3 replicas in production
- **Resources**: 1 CPU, 1GB RAM per instance
- **Endpoints**:
  - `POST /slack/events` - Slack event subscriptions
  - `POST /slack/commands` - Slash commands
  - `GET /health` - Health checks

### Background Workers

#### Slack Processor
- **Purpose**: Process Slack events and commands
- **Scaling**: 2 replicas
- **Resources**: 0.5 CPU, 512MB RAM per instance

#### Agent Processor  
- **Purpose**: Execute LangGraph workflows and data queries
- **Scaling**: 3 replicas  
- **Resources**: 1 CPU, 1GB RAM per instance

### Data Layer

#### Redis
- **Purpose**: Task queue and caching
- **Configuration**: Persistence enabled, 256MB memory limit
- **Backup**: Daily snapshots

#### PostgreSQL (Optional)
- **Purpose**: Conversation state and history
- **Configuration**: 15GB storage, connection pooling
- **Backup**: Daily automated backups

#### File Storage
- **Purpose**: Temporary CSV file storage
- **Cleanup**: Automatic cleanup after 1 hour
- **Limits**: 50MB max file size

## Configuration

### Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `SLACK_BOT_TOKEN` | Slack bot OAuth token | Yes | - |
| `SLACK_APP_TOKEN` | Slack app-level token | Yes | - |
| `SLACK_SIGNING_SECRET` | Slack app signing secret | Yes | - |
| `OPENAI_API_KEY` | OpenAI API key | Yes | - |
| `MCP_SERVER_URL` | Your MCP server URL | Yes | http://localhost:3000 |
| `REDIS_URL` | Redis connection URL | No | redis://localhost:6379/0 |
| `DATABASE_URL` | PostgreSQL URL (optional) | No | - |
| `MAX_FILE_SIZE_MB` | Max CSV file size | No | 50 |
| `QUERY_TIMEOUT_SECONDS` | Max query processing time | No | 60 |

### Slack App Setup

1. **Create Slack App** at https://api.slack.com/apps

2. **OAuth & Permissions** - Add these scopes:
   - `app_mentions:read`
   - `chat:write` 
   - `files:write`
   - `commands`

3. **Event Subscriptions**:
   - Request URL: `https://yourdomain.com/slack/events`
   - Subscribe to: `app_mention`, `message.im`

4. **Slash Commands**:
   - Command: `/query-data`
   - Request URL: `https://yourdomain.com/slack/commands`

5. **Install App** to your workspace

## Monitoring & Observability

### Health Checks
```bash
# Application health
curl http://localhost:8000/health

# Component health
curl http://localhost:8000/health | jq '.checks'
```

### Metrics (Prometheus)
- Request count and latency
- Queue depth and processing time  
- MCP server response times
- File generation metrics
- Error rates

### Logs
```bash
# View application logs
docker-compose logs -f slack-bot

# View worker logs  
docker-compose logs -f agent-processor

# View all logs
docker-compose logs -f
```

### Dashboards (Grafana)
- Application Performance
- Queue Monitoring  
- Error Tracking
- Resource Usage

## Security

### Network Security
- Nginx rate limiting (10 req/s API, 30 req/s webhooks)
- Request signature validation
- HTTPS termination at load balancer

### Application Security
- Input validation and sanitization
- No secrets in logs or responses
- Automatic file cleanup
- Resource limits enforced

### Secrets Management
```bash
# Use environment variables for secrets
export SLACK_BOT_TOKEN="xoxb-..."
export OPENAI_API_KEY="sk-..."

# Or use Docker secrets in production
docker secret create slack_bot_token /path/to/token
```

## Troubleshooting

### Common Issues

#### 1. Health Check Failing
```bash
# Check service status
docker-compose ps

# Check application logs
docker-compose logs slack-bot

# Check dependencies
curl http://localhost:6379  # Redis
curl http://localhost:5432  # PostgreSQL
```

#### 2. Slack Events Not Processing
```bash
# Check webhook validation
curl -X POST http://localhost:8000/slack/events \
  -H "Content-Type: application/json" \
  -d '{"type":"url_verification","challenge":"test"}'

# Check queue status
docker-compose logs slack-processor
```

#### 3. MCP Server Connection Issues
```bash
# Test MCP connectivity
curl http://your-mcp-server:3000/health

# Check firewall/network
docker-compose exec slack-bot ping your-mcp-server
```

#### 4. File Upload Failures
```bash
# Check file permissions
ls -la temp_files/

# Check disk space
df -h

# Check file limits
grep MAX_FILE_SIZE .env
```

### Performance Tuning

#### Scale Workers
```yaml
# docker-compose.prod.yml
agent-processor:
  deploy:
    replicas: 5  # Increase for more concurrent queries
```

#### Optimize Redis
```yaml
redis:
  command: >
    redis-server
    --maxmemory 512mb  # Increase memory
    --maxmemory-policy allkeys-lru
```

#### Database Optimization
```yaml
postgres:
  environment:
    POSTGRES_SHARED_BUFFERS: 256MB
    POSTGRES_EFFECTIVE_CACHE_SIZE: 1GB
```

## Maintenance

### Updates
```bash
# Pull latest changes
git pull origin main

# Rebuild and redeploy
docker-compose build --no-cache
docker-compose up -d
```

### Backups
```bash
# Backup Redis data
docker-compose exec redis redis-cli BGSAVE

# Backup PostgreSQL
docker-compose exec postgres pg_dump -U postgres slack_bot > backup.sql
```

### Cleanup
```bash
# Clean up old images
docker system prune -f

# Clean up temp files
docker-compose exec slack-bot python -c "
from src.services.csv_service import get_csv_service
import asyncio
asyncio.run(get_csv_service().cleanup_expired_files())
"
```

## Production Checklist

- [ ] Environment variables configured
- [ ] Slack app installed and configured  
- [ ] MCP server accessible
- [ ] SSL certificates installed
- [ ] Monitoring configured
- [ ] Backup strategy implemented
- [ ] Log aggregation configured
- [ ] Resource limits set
- [ ] Security headers configured
- [ ] Rate limiting enabled

## Support

For issues and questions:
1. Check the logs first
2. Review this deployment guide
3. Check health endpoints
4. Contact the development team

---

Built with ❤️ using FastAPI, LangGraph, and MCP