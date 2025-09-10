#!/bin/bash

set -e

# Configuration
CLUSTER_NAME="optibot-cluster"
SERVICE_NAME="optibot-task-service-hxwtet44"
REGION="us-east-1"

echo "🚀 Deploying OptiBot to AWS ECS..."

# Check AWS CLI configuration
if ! aws sts get-caller-identity &>/dev/null; then
    echo "❌ AWS CLI not configured. Please configure AWS credentials first."
    exit 1
fi

# Check if service exists
if ! aws ecs describe-services --cluster $CLUSTER_NAME --services $SERVICE_NAME --region $REGION &>/dev/null; then
    echo "⚠️  Service $SERVICE_NAME does not exist. Creating new service..."
    
    # Create the service
    aws ecs create-service \
        --cluster $CLUSTER_NAME \
        --service-name $SERVICE_NAME \
        --task-definition optibot-task \
        --desired-count 1 \
        --launch-type FARGATE \
        --network-configuration "awsvpcConfiguration={subnets=[subnet-XXXXX],securityGroups=[sg-XXXXX],assignPublicIp=ENABLED}" \
        --region $REGION

    echo "✅ Service created successfully!"
else
    echo "🔄 Updating existing service..."
    
    # Update the service
    aws ecs update-service \
        --cluster $CLUSTER_NAME \
        --service $SERVICE_NAME \
        --task-definition optibot-task \
        --force-new-deployment \
        --region $REGION

    echo "✅ Service updated successfully!"
fi

# Wait for service to stabilize
echo "⏳ Waiting for service to stabilize..."
aws ecs wait services-stable \
    --cluster $CLUSTER_NAME \
    --services $SERVICE_NAME \
    --region $REGION

echo "🎉 Deployment completed successfully!"
echo ""
echo "📋 To check service status:"
echo "   aws ecs describe-services --cluster $CLUSTER_NAME --services $SERVICE_NAME --region $REGION"
echo ""
echo "📋 To view logs:"
echo "   aws logs get-log-events --log-group-name /ecs/optibot --log-stream-name ecs/optibot/TASK_ID"
echo ""
echo "🔄 To update deployment:"
echo "   ./scripts/deploy-aws.sh"
