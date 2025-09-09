#!/bin/bash

# Development startup script

set -e

echo "🚀 Starting OptiBot (Slack Data Query Bot) in development mode..."

# Check if .env exists
if [ ! -f .env ]; then
    echo "❌ .env file not found. Please copy .env.example to .env and configure it."
    exit 1
fi

# Create necessary directories
mkdir -p logs temp_files

# Start services
echo "📦 Starting Docker services..."
docker-compose up --build -d

echo "⏳ Waiting for services to be ready..."
sleep 10

# Check health
echo "🔍 Checking service health..."
curl -f http://localhost:8000/health || {
    echo "❌ Health check failed. Checking logs..."
    docker-compose logs slack-bot
    exit 1
}

echo "✅ All services are running!"
echo ""
echo "📱 OptiBot API: http://localhost:8000"
echo "🔗 Socket Mode: Connected via WebSocket (no public endpoints needed)"
echo "📊 Prometheus: http://localhost:9090"
echo "📈 Grafana: http://localhost:3000 (admin/admin)"
echo "🔍 Redis: localhost:6379"
echo "🗄️  PostgreSQL: localhost:5432"
echo ""
echo "📋 To view logs:"
echo "   docker-compose logs -f slack-bot"
echo "   docker-compose logs -f socket-mode-worker"
echo "   docker-compose logs -f agent-processor"
echo ""
echo "🛑 To stop services:"
echo "   docker-compose down"