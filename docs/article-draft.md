# Post outline — "Transcribing and analyzing F1 team radio with GCP for under $X/month"

Article outline. Each section has 3-5 bullets describing what needs to be written.

## 1. Hook (1-2 paragraphs)

- Every time I watch an F1 race and hear Verstappen complaining about the car on the radio, I think: could you collect all of that, transcribe it, classify sentiment, and rank "who complains the most" automatically?
- Spoiler: you can. And it costs less than $X/month on GCP.
- In this post I walk through the end-to-end pipeline — code, infra, prompt, real measured cost — and link the repo.

## 2. The dataset nobody told you existed

- [openf1.org](https://openf1.org) freely exposes F1 team radios (with a direct URL to the MP3 hosted by F1 itself).
- Endpoints: `/meetings`, `/sessions`, `/drivers`, `/team_radio`.
- Honest limitations: 30 req/min rate limit (free tier), not every radio shows up (only the ones broadcast).
- Volume: ~7000 audios in the 2025 season, ~1.5MB each.

## 3. Architecture in 5 boxes

- Cloud Function `f1-radio-collector`: downloads metadata + audios → GCS + BigQuery.
- Cloud Function `f1-radio-analyzer`: pulls audio from GCS → Vertex AI Gemini 2.5-flash → BigQuery.
- The `mart.f1_radio_enriched` view consolidates everything for Looker Studio.
- Why **not** use Pub/Sub here (low volume, simplicity > purity).

## 4. The heart: the prompt

- Show the full `prompt.txt`.
- Explain the structured output via `responseSchema` (JSON Schema validated by Vertex).
- Why ask for transcription in English even when the audio is in another language (consistency for downstream analysis).
- How I solved "who is speaking?" without paid speaker diarization (heuristic + prompt context).

## 5. The idempotent watermark trick

- `LEFT JOIN raw.gemini_radio_analysis WHERE rhs IS NULL`.
- Why this beats timestamps/queues: re-running is safe, no duplicates, no external state needed.
- Same technique used by the collector to discover new audios.

## 6. Show me the data — real examples

- 3-4 BigQuery screenshots: `SELECT * FROM mart.f1_radio_enriched WHERE driver_acronym='VER' ORDER BY sentiment_score LIMIT 5`.
- Top 5 most positive radios of the season.
- Top 5 complaints about `tyres`.
- Topic distribution by session type.

## 7. Real cost (1 month running)

- Cloud Functions: $X
- Vertex AI Gemini (calls + tokens): $Y
- GCS storage: $Z
- BigQuery (storage + queries): $W
- **Total: ~$N/month** to process the entire season.

## 8. How to run it yourself

- Link to the GitHub repo.
- "In 4 commands: `bash infra/setup.sh`, `bash function/*/deploy.sh`, `bash invoke.sh collector`, `bash invoke.sh analyzer`."
- Honest prerequisites (GCP project with billing, ~5 minutes).

## 9. Next steps / what didn't make the cut

- Real diarization (Speech API) to identify the engineer by name.
- Temporal analysis: driver mood evolving throughout a race.
- Compare engineers: who's the most didactic? who yells the most?
- Apply the same architecture to other public audio datasets (call centers, podcasts).

## 10. Closing

- "The recipe is the same for any public audio: GCS + Vertex + BigQuery. I use this in production at Billor to analyze driver support calls; now you see it running on F1."
- Link to the repo + my blog/socials.
