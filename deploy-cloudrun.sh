#!/bin/bash

# Configuration
PROJECT_ID="uat-env-888888"
PROJECT_NAME="p-uat"
SERVICE_NAME="agent-william-smith"
REGION="asia-east1"  # Change to your preferred region
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

# Set the project
gcloud config set project ${PROJECT_ID}

# Build and push the Docker image
echo "Building Docker image..."
gcloud builds submit --tag ${IMAGE_NAME}

# Deploy to Cloud Run
echo "Deploying to Cloud Run..."
gcloud run deploy ${SERVICE_NAME} \
  --image ${IMAGE_NAME} \
  --platform managed \
  --region ${REGION} \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --timeout 300 \
  --max-instances 10 \
  --min-instances 0 \
  --set-env-vars "GEMINI_MODEL=gemini-2.5-flash-lite" \
  --set-env-vars "ALLOWED_ORIGINS=https://aigc-mvp.mlytics.co" \
  --set-secrets "GEMINI_API_KEY=GEMINI_API_KEY:latest" \
  --set-secrets "API_BEARER_TOKEN=API_BEARER_TOKEN:latest" \
  --set-secrets "GOOGLE_SEARCH_KEY=GOOGLE_SEARCH_KEY:latest" \
  --set-secrets "GOOGLE_SEARCH_ENGINE_ID=GOOGLE_SEARCH_ENGINE_ID:latest"

echo "Deployment complete!"
echo "Service URL will be displayed above"
