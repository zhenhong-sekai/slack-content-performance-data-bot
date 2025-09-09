#!/bin/bash

# Production deployment script

set -e

echo "🚀 Deploying OptiBot (Slack Data Query Bot) to production..."

# Check if .env.production exists
if [ ! -f .env.production ]; then
    echo "❌ .env.production file not found. Please create it with production configuration."
    exit 1
fi

# Build and deploy
echo "🏗️  Building production images..."
docker-compose -f docker-compose.prod.yml build

echo "📦 Deploying services..."
docker-compose -f docker-compose.prod.yml up -d

echo "⏳ Waiting for services to be ready..."
sleep 30

# Health check
echo "🔍 Performing health check..."
for i in {1..5}; do
    if curl -f http://localhost/health; then
        echo "✅ Health check passed!"
        break
    else
        echo "⏳ Health check failed, retrying in 10 seconds... ($i/5)"
        sleep 10
        if [ $i -eq 5 ]; then
            echo "❌ Health check failed after 5 attempts. Checking logs..."
            docker-compose -f docker-compose.prod.yml logs --tail=50 slack-bot
            exit 1
        fi
    fi
done

echo "🎉 Production deployment successful!"
echo ""
echo "📱 OptiBot: http://localhost"
echo "🔗 Socket Mode: Connected via WebSocket"
echo "📊 Prometheus: http://localhost:9090"
echo "📈 Grafana: http://localhost:3000"
echo ""
echo "📋 To view logs:"
echo "   docker-compose -f docker-compose.prod.yml logs -f slack-bot"
echo ""
echo "🔄 To update deployment:"
echo "   ./scripts/deploy-prod.sh"
echo ""
echo "🛑 To stop production services:"
echo "   docker-compose -f docker-compose.prod.yml down"