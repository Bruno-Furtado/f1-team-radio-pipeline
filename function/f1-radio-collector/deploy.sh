#!/bin/bash
set -e

PROJECT_ID="$(gcloud config get-value project 2>/dev/null)"
if [ -z "${PROJECT_ID}" ]; then
	echo "❌ No GCP project set. Run: gcloud config set project YOUR_PROJECT_ID"
	exit 1
fi
REGION="us-central1"
BUCKET="${PROJECT_ID}-files"

# Read overrides from local .env if present
if [ -f .env ]; then
	# shellcheck disable=SC2046
	export $(grep -v '^#' .env | grep -v '^$' | xargs)
fi

LOOKBACK_DAYS="${LOOKBACK_DAYS:-7}"
MAX_WORKERS="${MAX_WORKERS:-5}"
RATE_LIMIT_PER_MIN="${RATE_LIMIT_PER_MIN:-25}"
SEASON_YEAR="${SEASON_YEAR:-2025}"

echo "Deploying f1-radio-collector to ${PROJECT_ID} (${REGION})..."
gcloud functions deploy f1-radio-collector \
	--gen2 \
	--runtime=python313 \
	--region="${REGION}" \
	--source=. \
	--entry-point=collect \
	--trigger-http \
	--no-allow-unauthenticated \
	--timeout=1800s \
	--memory=1Gi \
	--cpu=1 \
	--concurrency=1 \
	--min-instances=0 \
	--max-instances=1 \
	--set-env-vars="PROJECT_ID=${PROJECT_ID},BUCKET_NAME=${BUCKET},RAW_DATASET=raw,LOOKBACK_DAYS=${LOOKBACK_DAYS},MAX_WORKERS=${MAX_WORKERS},RATE_LIMIT_PER_MIN=${RATE_LIMIT_PER_MIN},SEASON_YEAR=${SEASON_YEAR}"

echo "✅ Deployed."
