#!/bin/bash
set -e

TARGET="${1:-}"
if [ "${TARGET}" != 'collector' ] && [ "${TARGET}" != 'analyzer' ]; then
	echo 'Usage: bash invoke.sh [collector|analyzer]' >&2
	exit 2
fi

NAME="f1-radio-${TARGET}"
REGION="us-central1"

URL="$(gcloud functions describe "${NAME}" --gen2 --region="${REGION}" --format='value(serviceConfig.uri)')"
if [ -z "${URL}" ]; then
	echo "❌ Could not resolve URL for ${NAME}. Is it deployed?" >&2
	exit 1
fi

echo "▶ Invoking ${NAME} at ${URL}"
curl --fail-with-body -sS -X POST \
	-H "Authorization: Bearer $(gcloud auth print-identity-token)" \
	-H 'Content-Type: application/json' \
	"${URL}"
echo
