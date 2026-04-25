"""Export f1_radio_enriched view to a normalized JSON for the dashboard.

Reads `mart.f1_radio_enriched`, splits the result into reference dicts
(drivers, meetings, sessions) and a flat list of radio events, plus a
transcripts dict keyed by radio id. Output is consumed by the dashboard
page in the personal-page repo.

Usage:
	export PROJECT_ID=f1-team-radio
	python tools/export_dashboard_data.py

Output: tools/output/f1-radio.json
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('PROJECT_ID') or os.environ.get('GOOGLE_CLOUD_PROJECT')
if not PROJECT_ID:
	raise SystemExit('Set PROJECT_ID (or GOOGLE_CLOUD_PROJECT) in env or .env')

OUTPUT_PATH = Path(__file__).parent / 'output' / 'f1-radio.json'

QUERY = f"""
SELECT *
FROM `{PROJECT_ID}.mart.f1_radio_enriched`
WHERE summary IS NOT NULL
ORDER BY event_time DESC
"""


def normalize_colour(colour):
	if not colour:
		return None
	return colour if colour.startswith('#') else f'#{colour}'


def to_iso(value):
	if value is None:
		return None
	if isinstance(value, datetime):
		return value.isoformat()
	return str(value)


def parse_transcription(raw):
	if not raw:
		return None
	if isinstance(raw, (list, dict)):
		return raw
	try:
		parsed = json.loads(raw)
	except (TypeError, ValueError):
		return None
	if isinstance(parsed, dict) and 'transcription' in parsed:
		return parsed['transcription']
	return parsed


def make_radio_id(gcs_uri):
	return hashlib.sha1(gcs_uri.encode('utf-8')).hexdigest()[:12]


def driver_ref(driver_number, session_key):
	return f'{driver_number}:{session_key}'


def export():
	client = bigquery.Client(project=PROJECT_ID)
	logger.info('Running query against %s.mart.f1_radio_enriched', PROJECT_ID)
	rows = list(client.query(QUERY).result())
	logger.info('Fetched %d rows', len(rows))

	drivers = {}
	meetings = {}
	sessions = {}
	radios = []
	transcripts = {}

	for row in rows:
		dr_key = driver_ref(row['driver_number'], row['session_key'])
		if dr_key not in drivers:
			drivers[dr_key] = {
				'driver_number': row['driver_number'],
				'full_name': row['driver_name'],
				'name_acronym': row['driver_acronym'],
				'team_name': row['team_name'],
				'team_colour': normalize_colour(row['team_colour']),
				'headshot_url': row['headshot_url'],
				'country_code': row['driver_country_code'],
			}

		mk = row['meeting_key']
		if mk not in meetings:
			meetings[mk] = {
				'meeting_key': mk,
				'meeting_name': row['meeting_name'],
				'meeting_official_name': row['meeting_official_name'],
				'country_name': row['country_name'],
				'country_code': row['country_code'],
				'country_flag': row['country_flag'],
				'circuit_short_name': row['circuit_name'],
				'circuit_image': row['circuit_image'],
				'circuit_info_url': row['circuit_info_url'],
				'circuit_type': row['circuit_type'],
				'circuit_key': row['circuit_key'],
				'location': row['location'],
				'gmt_offset': row['meeting_gmt_offset'],
				'date_start': to_iso(row['meeting_date_start']),
				'date_end': to_iso(row['meeting_date_end']),
				'year': row['year'],
			}

		sk = row['session_key']
		if sk not in sessions:
			sessions[sk] = {
				'session_key': sk,
				'session_name': row['session_name'],
				'session_type': row['session_type'],
				'meeting_key': mk,
				'date_start': to_iso(row['session_date_start']),
				'date_end': to_iso(row['session_date_end']),
			}

		rid = make_radio_id(row['gcs_uri'])
		radios.append({
			'id': rid,
			'event_time': to_iso(row['event_time']),
			'recording_url': row['recording_url'],
			'driver_ref': dr_key,
			'session_ref': sk,
			'meeting_ref': mk,
			'sentiment_score': row['sentiment_score'],
			'sentiment_label': row['sentiment_label'],
			'emotion': row['emotion'],
			'is_complaint': row['is_complaint'],
			'complaint_target': row['complaint_target'],
			'is_positive_outcome': row['is_positive_outcome'],
			'topic': row['topic'],
			'summary': row['summary'],
			'language_detected': row['language_detected'],
		})

		parsed = parse_transcription(row['transcription'])
		if parsed:
			transcripts[rid] = parsed

	payload = {
		'meta': {
			'generated_at': datetime.now(timezone.utc).isoformat(),
			'source': f'{PROJECT_ID}.mart.f1_radio_enriched',
			'record_count': len(radios),
		},
		'drivers': drivers,
		'meetings': meetings,
		'sessions': sessions,
		'radios': radios,
		'transcripts': transcripts,
	}

	OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
	with OUTPUT_PATH.open('w', encoding='utf-8') as fp:
		json.dump(payload, fp, ensure_ascii=False, separators=(',', ':'))

	size_kb = OUTPUT_PATH.stat().st_size / 1024
	logger.info(
		'Wrote %s (%d radios, %d drivers, %d meetings, %d sessions, %.1f KB)',
		OUTPUT_PATH,
		len(radios),
		len(drivers),
		len(meetings),
		len(sessions),
		size_kb,
	)


if __name__ == '__main__':
	export()
