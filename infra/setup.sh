#!/bin/bash
set -e

# Idempotent setup for the f1-team-radio-pipeline project.
# Enables APIs, creates a private GCS bucket, grants IAM roles, creates BigQuery datasets/tables/view.

PROJECT_ID="$(gcloud config get-value project 2>/dev/null)"
if [ -z "${PROJECT_ID}" ]; then
	echo "❌ No GCP project set. Run: gcloud config set project YOUR_PROJECT_ID"
	exit 1
fi
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
REGION="us-central1"
BUCKET="${PROJECT_ID}-files"
COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==="
echo "Project:        ${PROJECT_ID}"
echo "Project number: ${PROJECT_NUMBER}"
echo "Region:         ${REGION}"
echo "Bucket:         gs://${BUCKET}"
echo "Service acct:   ${COMPUTE_SA}"
echo "==="

echo "🔧 Enabling required APIs..."
gcloud services enable \
	cloudfunctions.googleapis.com \
	cloudbuild.googleapis.com \
	bigquery.googleapis.com \
	aiplatform.googleapis.com \
	storage.googleapis.com \
	run.googleapis.com \
	--project="${PROJECT_ID}"

echo "🪣 Creating private GCS bucket (skip if exists)..."
if ! gcloud storage buckets describe "gs://${BUCKET}" >/dev/null 2>&1; then
	gcloud storage buckets create "gs://${BUCKET}" \
		--project="${PROJECT_ID}" \
		--location="${REGION}" \
		--uniform-bucket-level-access \
		--public-access-prevention
else
	echo "   bucket already exists"
fi

echo "🔐 Granting IAM roles to ${COMPUTE_SA}..."
for ROLE in \
	roles/storage.objectAdmin \
	roles/bigquery.dataEditor \
	roles/bigquery.jobUser \
	roles/aiplatform.user
do
	gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
		--member="serviceAccount:${COMPUTE_SA}" \
		--role="${ROLE}" \
		--condition=None \
		--quiet >/dev/null
	echo "   ${ROLE} ✔"
done

echo "🗂️  Creating BigQuery datasets..."
for DS in raw mart; do
	if ! bq --project_id="${PROJECT_ID}" show --dataset "${PROJECT_ID}:${DS}" >/dev/null 2>&1; then
		bq --location="${REGION}" mk --dataset \
			--description "${DS} layer for f1-team-radio-pipeline" \
			"${PROJECT_ID}:${DS}"
	else
		echo "   dataset ${DS} already exists"
	fi
done

echo "📊 Creating BigQuery tables in raw..."
declare -a TABLES=(
	"openf1_meetings"
	"openf1_sessions"
	"openf1_drivers"
	"openf1_team_radios"
	"gemini_radio_analysis"
)
for T in "${TABLES[@]}"; do
	if ! bq --project_id="${PROJECT_ID}" show "${PROJECT_ID}:raw.${T}" >/dev/null 2>&1; then
		bq mk --table \
			--project_id="${PROJECT_ID}" \
			"${PROJECT_ID}:raw.${T}" \
			"${SCRIPT_DIR}/schema/${T}.json"
	else
		echo "   table raw.${T} already exists"
	fi
done

echo "👁️  Creating view mart.f1_radio_enriched..."
sed "s/\${PROJECT_ID}/${PROJECT_ID}/g" "${SCRIPT_DIR}/schema/f1_radio_enriched.sql" \
	| bq --project_id="${PROJECT_ID}" query --use_legacy_sql=false --quiet

echo "✅ Setup completed."
echo ""
echo "Next steps:"
echo "  1. cd function/f1-radio-collector && bash deploy.sh"
echo "  2. cd function/f1-radio-analyzer  && bash deploy.sh"
echo "  3. bash invoke.sh collector"
echo "  4. bash invoke.sh analyzer"
