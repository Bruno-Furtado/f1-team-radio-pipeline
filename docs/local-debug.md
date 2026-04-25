# Local debug

Run the Cloud Functions on your machine via [`functions-framework`](https://github.com/GoogleCloudPlatform/functions-framework-python), useful for iterating without redeploying. Both functions already include `functions-framework` in `requirements.txt`.

## Prerequisites

```bash
gcloud auth application-default login # ADC for BigQuery / Storage / Vertex clients
gcloud config set project YOUR_PROJECT_ID
gcloud auth application-default set-quota-project YOUR_PROJECT_ID # silences the "no quota project" warning
python --version # 3.13.x
```

The function will use your ADC credentials, so your user needs the same roles the deployed service account has (`storage.objectAdmin`, `bigquery.dataEditor`, `bigquery.jobUser`, `aiplatform.user`).

## Environment variables

`deploy.sh` injects a few vars at deploy time that are **not** in `.env.example` (`PROJECT_ID`, `BUCKET_NAME`, `RAW_DATASET`). Both functions load `.env` via `python-dotenv`, so the simplest path is to copy `.env.example` and append the missing ones — see the snippets below per function.

## Run the collector locally

```bash
cd function/f1-radio-collector

cp .env.example .env
PROJECT_ID="$(gcloud config get-value project)"
cat >> .env <<EOF
PROJECT_ID=${PROJECT_ID}
BUCKET_NAME=${PROJECT_ID}-files
RAW_DATASET=raw
EOF

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

functions-framework --target=collect --debug --port=8080
```

In another terminal:

```bash
curl -X POST http://localhost:8080
```

## Run the analyzer locally

```bash
cd function/f1-radio-analyzer
cp .env.example .env

cat >> .env <<EOF
PROJECT_ID=$(gcloud config get-value project)
RAW_DATASET=raw
EOF

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

functions-framework --target=analyze --debug --port=8081
```

In another terminal:

```bash
curl -X POST http://localhost:8081
```

## Tips

- `--debug` reloads on save.
- Logs go to stdout via `logging.basicConfig` (the Cloud Logging client falls back to it when running outside GCP).
- Lower `FILE_LIMIT` / `LOOKBACK_DAYS` while iterating to keep iterations short.
- The function still writes to the **real** GCS bucket and BigQuery datasets — there is no local emulator. Use a separate dev project if you don't want to pollute production data.
