# CLAUDE.md

Conventions for this repository.

## Stack

- Python 3.13 (Cloud Functions Gen2, runtime `python313`)
- Libraries: `functions-framework`, `google-cloud-bigquery`, `google-cloud-storage`, `google-genai`, `requests`, `python-dotenv`
- Linting: `ruff` — single quotes, tab indent, line length 150, target Python 3.11

## BigQuery datasets

- `raw` — raw data per source, no transformation
  - `raw.openf1_meetings`, `raw.openf1_sessions`, `raw.openf1_drivers` (snapshot, `WRITE_TRUNCATE`)
  - `raw.openf1_team_radios` (fact, `WRITE_APPEND`)
  - `raw.gemini_radio_analysis` (fact, `WRITE_APPEND`)
- `mart` — consumption
  - `mart.f1_radio_enriched` (view with full JOIN)

## Code conventions

- **Watermark pattern:** discover work via `LEFT JOIN ... WHERE rhs IS NULL`. Never timestamps or queues.
- **Function writes directly to BigQuery** — no Pub/Sub in this project.
- **Lazy singletons** for GCP clients (module with global `_client = None` and a `get_*()` function).
- **Logging:** `google.cloud.logging.Client().setup_logging()` with fallback to `logging.basicConfig`.
- **OpenF1 client:** honor `Retry-After` on 429; rate limit 25 req/min (margin under the free tier's 30/min).

## GCS

- Bucket: `gs://${PROJECT_ID}-files` (private: `--uniform-bucket-level-access --public-access-prevention=enforced`)
- Path: `gs://${PROJECT_ID}-files/f1/year=2025/meeting={mk}/session={sk}/driver={dn}/{date_iso}_{dn}.mp3`

## Gemini model

- Primary: `gemini-2.5-flash` in `us-central1`
- Fallback: `gemini-3.1-pro-preview` in `global`

## Deploy order

1. `bash infra/setup.sh`
2. `cd function/f1-radio-collector && bash deploy.sh`
3. `cd function/f1-radio-analyzer && bash deploy.sh`
4. `bash invoke.sh collector` (manual; or create a Cloud Scheduler — optional, see README)
5. `bash invoke.sh analyzer`
