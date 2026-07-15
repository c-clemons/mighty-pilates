#!/usr/bin/env bash
# Build + deploy the Mighty Pilates portal to Google Cloud Run.
#   PROJECT=<your-gcp-project> ./deploy.sh
# Optional env: REGION (default us-central1).
set -euo pipefail

: "${PROJECT:?set PROJECT=<your-gcp-project>}"
REGION="${REGION:-us-central1}"
SERVICE="mighty-portal"
AR_REPO="portals"
TAG="$(git rev-parse --short HEAD 2>/dev/null || echo latest)"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${AR_REPO}/${SERVICE}:${TAG}"
SECRET="${SERVICE%-portal}-secrets"   # -> mighty-secrets

echo ">> Building ${IMAGE}"
gcloud builds submit --project "$PROJECT" --tag "$IMAGE"

echo ">> Deploying ${SERVICE}"
gcloud run deploy "$SERVICE" \
  --project "$PROJECT" --region "$REGION" --image "$IMAGE" \
  --no-allow-unauthenticated \
  --port 8080 --session-affinity \
  --cpu 1 --memory 512Mi --min-instances 0 --max-instances 2 \
  --set-secrets "/home/appuser/.streamlit/secrets.toml=${SECRET}:latest"

echo ">> Deployed. Service URL:"
gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
  --format='value(status.url)'
