# OptiBot Deployment Guide

This guide covers deploying OptiBot to AWS ECS using CI/CD with GitHub Actions.

## Prerequisites

1. **AWS Account** with appropriate permissions
2. **ECR Repository** named `optibot`
3. **ECS Cluster** named `optibot-cluster`
4. **ECS Service** named `optibot-task-service-hxwtet44`
5. **ECS Task Definition** named `optibot-task`
6. **GitHub Repository** with Actions enabled

## Setup Instructions

### 1. AWS Resources Setup

#### ECR Repository
```bash
aws ecr create-repository --repository-name optibot --region us-east-1
```

#### ECS Cluster
```bash
aws ecs create-cluster --cluster-name optibot-cluster --region us-east-1
```

#### IAM Roles
Create the following IAM roles:
- `ecsTaskExecutionRole` - for ECS task execution
- `ecsTaskRole` - for ECS task runtime permissions

#### CloudWatch Logs Group
```bash
aws logs create-log-group --log-group-name /ecs/optibot --region us-east-1
```

### 2. GitHub Secrets Setup

Add the following secrets to your GitHub repository:

1. Go to your repository → Settings → Secrets and variables → Actions
2. Add these repository secrets:

```
AWS_ACCESS_KEY_ID=your-aws-access-key
AWS_SECRET_ACCESS_KEY=your-aws-secret-key
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token
SLACK_SIGNING_SECRET=your-signing-secret
MCP_SERVER_URL=http://your-mcp-server:3000
OPENAI_API_KEY=sk-your-openai-api-key
```

**Note**: All sensitive configuration is now stored in GitHub Secrets and automatically injected into the ECS task during deployment.

### 3. ECS Service Creation

Create the ECS service (if not already created):

```bash
aws ecs create-service \
  --cluster optibot-cluster \
  --service-name optibot-task-service-hxwtet44 \
  --task-definition optibot-task \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-12345],securityGroups=[sg-12345],assignPublicIp=ENABLED}" \
  --region us-east-1
```

## Deployment

### Automatic Deployment (CI/CD)

1. Push to the `main` branch
2. GitHub Actions will automatically:
   - Build the Docker image
   - Push to ECR
   - Update the ECS service
   - Deploy the new version

### Manual Deployment

Run the deployment script:

```bash
./scripts/deploy.sh
```

## Monitoring

### CloudWatch Logs
- Logs are available in `/ecs/optibot` log group
- Stream prefix: `ecs`

### Health Checks
- Application health endpoint: `http://your-service-url/health`
- ECS health checks are configured in the task definition

### Service Status
```bash
aws ecs describe-services \
  --cluster optibot-cluster \
  --services optibot-task-service-hxwtet44 \
  --region us-east-1
```

## Troubleshooting

### Common Issues

1. **Task fails to start**
   - Check CloudWatch logs
   - Verify environment variables and secrets
   - Check IAM permissions

2. **Image pull errors**
   - Verify ECR repository exists
   - Check ECR permissions
   - Ensure image was pushed successfully

3. **Service update fails**
   - Check task definition validity
   - Verify ECS service exists
   - Check network configuration

### Useful Commands

```bash
# Check service status
aws ecs describe-services --cluster optibot-cluster --services optibot-service

# View task logs
aws logs get-log-events --log-group-name /ecs/optibot --log-stream-name ecs/optibot/task-id

# List running tasks
aws ecs list-tasks --cluster optibot-cluster --service-name optibot-task-service-hxwtet44
```

## Security Considerations

1. **Secrets Management**: All sensitive data is stored in GitHub Secrets and automatically injected during deployment
2. **IAM Permissions**: Use least privilege principle for IAM roles
3. **Network Security**: Configure security groups appropriately
4. **Container Security**: Regularly update base images and dependencies
5. **GitHub Secrets**: Ensure only authorized team members have access to repository secrets

## Cost Optimization

1. **Fargate Spot**: Consider using Fargate Spot for non-critical workloads
2. **Auto Scaling**: Implement auto scaling based on CPU/memory usage
3. **Log Retention**: Set appropriate log retention periods
4. **Resource Sizing**: Monitor and adjust CPU/memory allocation
