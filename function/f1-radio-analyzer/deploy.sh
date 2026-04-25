#!/bin/bash
set -e

PROJECT_ID="$(gcloud config get-value project 2>/dev/null)"
if [ -z "${PROJECT_ID}" ]; then
	echo "❌ No GCP project set. Run: gcloud config set project YOUR_PROJECT_ID"
	exit 1
fi
REGION="us-central1"

if [ -f .env ]; then
	# shellcheck disable=SC2046
	export $(grep -v '^#' .env | grep -v '^$' | xargs)
fi

GEMINI_MODEL="${GEMINI_MODEL:-gemini-2.5-flash}"
GEMINI_LOCATION="${GEMINI_LOCATION:-us-central1}"
FALLBACK_MODEL="${FALLBACK_MODEL:-gemini-3.1-pro-preview}"
FALLBACK_LOCATION="${FALLBACK_LOCATION:-global}"
FILE_LIMIT="${FILE_LIMIT:-200}"
CONCURRENCY_LIMIT="${CONCURRENCY_LIMIT:-10}"
PRIMARY_RPM="${PRIMARY_RPM:-150}"
FALLBACK_RPM="${FALLBACK_RPM:-30}"
MAX_RETRIES_429="${MAX_RETRIES_429:-3}"

echo "Deploying f1-radio-analyzer to ${PROJECT_ID} (${REGION})..."
gcloud functions deploy f1-radio-analyzer \
	--gen2 \
	--runtime=python313 \
	--region="${REGION}" \
	--source=. \
	--entry-point=analyze \
	--trigger-http \
	--no-allow-unauthenticated \
	--timeout=1800s \
	--memory=1Gi \
	--cpu=1 \
	--concurrency=1 \
	--min-instances=0 \
	--max-instances=1 \
	--set-env-vars="PROJECT_ID=${PROJECT_ID},RAW_DATASET=raw,GEMINI_MODEL=${GEMINI_MODEL},GEMINI_LOCATION=${GEMINI_LOCATION},FALLBACK_MODEL=${FALLBACK_MODEL},FALLBACK_LOCATION=${FALLBACK_LOCATION},FILE_LIMIT=${FILE_LIMIT},CONCURRENCY_LIMIT=${CONCURRENCY_LIMIT},PRIMARY_RPM=${PRIMARY_RPM},FALLBACK_RPM=${FALLBACK_RPM},MAX_RETRIES_429=${MAX_RETRIES_429}"

echo "✅ Deployed."
