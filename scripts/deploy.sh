#!/bin/bash

# Deploy script for OptiBot to ECS
set -e

# Configuration
AWS_REGION="us-east-1"
ECR_REPOSITORY="optibot"
ECS_CLUSTER="optibot-cluster"
ECS_SERVICE="optibot-service"
ECS_TASK_DEFINITION="optibot-task"
CONTAINER_NAME="optibot"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 Starting OptiBot deployment...${NC}"

# Check if AWS CLI is installed
if ! command -v aws &> /dev/null; then
    echo -e "${RED}❌ AWS CLI is not installed. Please install it first.${NC}"
    exit 1
fi

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker is not installed. Please install it first.${NC}"
    exit 1
fi

# Get AWS account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
if [ -z "$AWS_ACCOUNT_ID" ]; then
    echo -e "${RED}❌ Failed to get AWS account ID. Please check your AWS credentials.${NC}"
    exit 1
fi

echo -e "${YELLOW}📋 AWS Account ID: $AWS_ACCOUNT_ID${NC}"

# Login to ECR
echo -e "${YELLOW}🔐 Logging in to Amazon ECR...${NC}"
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

# Build and push Docker image
echo -e "${YELLOW}🏗️  Building Docker image...${NC}"
docker build -f Dockerfile.prod -t $ECR_REPOSITORY:latest .

# Tag and push to ECR
ECR_URI="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPOSITORY"
docker tag $ECR_REPOSITORY:latest $ECR_URI:latest
docker tag $ECR_REPOSITORY:latest $ECR_URI:$(git rev-parse --short HEAD)

echo -e "${YELLOW}📤 Pushing image to ECR...${NC}"
docker push $ECR_URI:latest
docker push $ECR_URI:$(git rev-parse --short HEAD)

# Update task definition with new image
echo -e "${YELLOW}📝 Updating task definition...${NC}"
TASK_DEFINITION=$(aws ecs describe-task-definition --task-definition $ECS_TASK_DEFINITION --query taskDefinition)
NEW_TASK_DEFINITION=$(echo $TASK_DEFINITION | jq --arg IMAGE "$ECR_URI:latest" '.containerDefinitions[0].image = $IMAGE | del(.taskDefinitionArn) | del(.revision) | del(.status) | del(.requiresAttributes) | del(.placementConstraints) | del(.compatibilities) | del(.registeredAt) | del(.registeredBy)')

# Register new task definition
NEW_TASK_DEFINITION_ARN=$(echo $NEW_TASK_DEFINITION | aws ecs register-task-definition --cli-input-json file:///dev/stdin --query taskDefinition.taskDefinitionArn --output text)

# Update ECS service
echo -e "${YELLOW}🔄 Updating ECS service...${NC}"
aws ecs update-service \
    --cluster $ECS_CLUSTER \
    --service $ECS_SERVICE \
    --task-definition $NEW_TASK_DEFINITION_ARN \
    --force-new-deployment

# Wait for deployment to complete
echo -e "${YELLOW}⏳ Waiting for deployment to complete...${NC}"
aws ecs wait services-stable --cluster $ECS_CLUSTER --services $ECS_SERVICE

echo -e "${GREEN}✅ Deployment completed successfully!${NC}"
echo -e "${GREEN}🎉 OptiBot is now running with the latest image.${NC}"

# Show service status
echo -e "${YELLOW}📊 Service Status:${NC}"
aws ecs describe-services --cluster $ECS_CLUSTER --services $ECS_SERVICE --query 'services[0].{Status:status,RunningCount:runningCount,PendingCount:pendingCount,DesiredCount:desiredCount}' --output table
