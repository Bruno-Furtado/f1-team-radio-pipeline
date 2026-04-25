<div align="center">

  ![cover](./docs/cover.png)

![Cloud Storage](https://img.shields.io/badge/data-Cloud_Storage-3B82F6?style=flat) ![BigQuery](https://img.shields.io/badge/data-BigQuery-3B82F6?style=flat) ![Cloud Functions](https://img.shields.io/badge/compute-Cloud_Functions-8B5CF6?style=flat) ![Vertex AI](https://img.shields.io/badge/ai-Vertex_AI-EC4899?style=flat) ![Gemini](https://img.shields.io/badge/ai-Gemini-EC4899?style=flat) ![Cloud Logging](https://img.shields.io/badge/observability-Cloud_Logging-F97316?style=flat) ![Python](https://img.shields.io/badge/lang-Python-EAB308?style=flat) ![SQL](https://img.shields.io/badge/lang-SQL-EAB308?style=flat) ![Bash](https://img.shields.io/badge/lang-Bash-EAB308?style=flat)
</div>

<br/>

Repository demonstrating how to use GCP to transcribe F1 team radio calls and extract sentiment from them.

> Team radio are sourced from the public [**OpenF1**](https://openf1.org) API, a community-maintained, real-time Formula 1 data project.

---

## 1. Prerequisites

- Google Cloud account with billing enabled
- `gcloud` CLI installed (`gcloud --version`)
- `bq` CLI (ships with `gcloud`)
- Project permissions: `roles/owner` or (IAM Admin + CF Admin + BQ Admin + Storage Admin + Service Usage Admin)
- Python 3.13

## 2. Initial setup (one-time, ~5 minutes)

```bash
git clone https://github.com/<user>/f1-team-radio-pipeline.git
cd f1-team-radio-pipeline
gcloud auth login
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
bash infra/setup.sh
```

What `infra/setup.sh` does (idempotent):

- Enables APIs: Cloud Functions, Cloud Build, BigQuery, Vertex AI, Storage, Cloud Run
- Creates the private bucket `gs://${PROJECT_ID}-files` (uniform access + public access prevention)
- Grants the default SA the roles `storage.objectAdmin`, `bigquery.dataEditor`, `bigquery.jobUser`, `aiplatform.user`
- Creates the `raw` and `mart` datasets
- Creates 5 tables in `raw` from the schemas in `infra/schema/`
- Creates the `mart.f1_radio_enriched` view

## 3. Deploy both Cloud Functions

```bash
cd function/f1-radio-collector
cp .env.example .env # optional: tweak values like LOOKBACK_DAYS, MAX_WORKERS
bash deploy.sh

cd ../f1-radio-analyzer
cp .env.example .env # optional: tweak GEMINI_MODEL, FILE_LIMIT
bash deploy.sh
```

## 4. Run the collector

Downloads metadata for meetings/sessions/drivers, discovers new team radios from sessions, and uploads the MP3s to GCS.

Prerequisites (one-time per shell):

```bash
gcloud auth login                          # only if not already authenticated
gcloud config set project YOUR_PROJECT_ID  # only if no project is set
```

Invoke the deployed function:

```bash
bash invoke.sh collector
```

Expect a JSON response within a few minutes:

```json
{
  "status": "ok",
  "season": 2025,
  "active_sessions": 4,
  "fetched_radios": 87,
  "new_radios": 87,
  "inserted": 87,
  "errors": 0,
  "elapsed_seconds": 42.3
}
```

> To iterate without redeploying, see [local-debug.md](docs/local-debug.md) instructions for running the functions locally.

## 5. Run the analyzer

Reads pending audios, sends each MP3 to Vertex AI Gemini with enriched context, and writes the structured analysis to BigQuery.

```bash
bash invoke.sh analyzer
```

> To iterate without redeploying, see [local-debug.md](docs/local-debug.md) instructions for running the functions locally.

## 6. Tools

Auxiliary scripts that run on top of the processed data live in [`tools/`](tools/), outside of the Cloud Functions. Currently the only one is `export_dashboard_data.py`, which reads `mart.f1_radio_enriched` and emits a normalized JSON consumed by the dashboard at https://brunofurtado.dev/projects/f1-team-radio.

```bash
export PROJECT_ID=f1-team-radio
python tools/export_dashboard_data.py
# -> tools/output/f1-radio.json
```

## 7. Repository layout

```
f1-team-radio-pipeline/
├── README.md
├── CLAUDE.md
├── docs/
│   └── article-draft.md           # blog post outline
├── infra/
│   ├── setup.sh
│   └── schema/                    # JSON schemas + view DDL
├── function/
│   ├── f1-radio-collector/        # downloads OpenF1 → GCS + raw.openf1_*
│   └── f1-radio-analyzer/         # GCS + Vertex → raw.gemini_radio_analysis
├── tools/                         # off-pipeline utilities (e.g. dashboard export)
└── invoke.sh                      # invokes functions via curl + OIDC
```

## 8. License

This project is licensed under the [MIT License](./LICENSE).

---

<div align="center">
  <sub>Made with ♥ in Curitiba 🌲 ☔️</sub>
</div>
