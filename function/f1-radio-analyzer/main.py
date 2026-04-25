import json
import logging
import os
import random
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import functions_framework
from dotenv import load_dotenv
from flask import jsonify
from google import genai
from google.cloud import bigquery
from google.genai import types as genai_types

load_dotenv()

if os.getenv('K_SERVICE'):
	import google.cloud.logging as gcl

	gcl.Client().setup_logging()
else:
	logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

logger = logging.getLogger(__name__)

PROJECT_ID = os.environ['PROJECT_ID']
RAW_DATASET = os.getenv('RAW_DATASET', 'raw')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')
GEMINI_LOCATION = os.getenv('GEMINI_LOCATION', 'us-central1')
FALLBACK_MODEL = os.getenv('FALLBACK_MODEL', 'gemini-3.1-pro-preview')
FALLBACK_LOCATION = os.getenv('FALLBACK_LOCATION', 'global')
FILE_LIMIT = int(os.getenv('FILE_LIMIT', '200'))
CONCURRENCY_LIMIT = int(os.getenv('CONCURRENCY_LIMIT', '10'))
PRIMARY_RPM = int(os.getenv('PRIMARY_RPM', '150'))
FALLBACK_RPM = int(os.getenv('FALLBACK_RPM', '30'))
MAX_RETRIES_429 = int(os.getenv('MAX_RETRIES_429', '3'))

PROMPT = (Path(__file__).parent / 'prompt.txt').read_text(encoding='utf-8')

RESPONSE_SCHEMA = {
	'type': 'object',
	'properties': {
		'transcription': {
			'type': 'array',
			'items': {
				'type': 'object',
				'properties': {
					'start_time': {'type': 'string'},
					'start_time_seconds': {'type': 'number'},
					'speaker': {'type': 'string', 'enum': ['driver', 'engineer', 'unknown']},
					'text': {'type': 'string'},
				},
				'required': ['start_time', 'start_time_seconds', 'speaker', 'text'],
			},
		},
		'sentiment_score': {'type': 'number'},
		'sentiment_label': {'type': 'string', 'enum': ['positive', 'neutral', 'negative']},
		'emotion': {'type': 'string', 'enum': ['calm', 'focused', 'frustrated', 'angry', 'excited', 'disappointed']},
		'is_complaint': {'type': 'boolean'},
		'complaint_target': {'type': 'string', 'enum': ['car', 'tyres', 'strategy', 'weather', 'other_driver', 'team', 'none']},
		'is_positive_outcome': {'type': 'boolean'},
		'topic': {'type': 'string', 'enum': ['pace', 'tyres', 'strategy', 'weather', 'incident', 'position', 'fuel', 'brakes', 'engine', 'communication', 'other']},
		'summary': {'type': 'string'},
		'language_detected': {'type': 'string'},
	},
	'required': [
		'transcription',
		'sentiment_score',
		'sentiment_label',
		'emotion',
		'is_complaint',
		'complaint_target',
		'is_positive_outcome',
		'topic',
		'summary',
		'language_detected',
	],
}

WATERMARK_QUERY = f"""
SELECT
	t.gcs_uri,
	t.driver_number,
	t.date AS event_time,
	d.full_name AS driver_name,
	d.name_acronym AS driver_acronym,
	d.team_name,
	s.session_type,
	s.session_name,
	m.meeting_name,
	m.country_name,
	m.year
FROM `{PROJECT_ID}.{RAW_DATASET}.openf1_team_radios` t
LEFT JOIN `{PROJECT_ID}.{RAW_DATASET}.openf1_drivers` d
	ON t.driver_number = d.driver_number AND t.session_key = d.session_key
LEFT JOIN `{PROJECT_ID}.{RAW_DATASET}.openf1_sessions` s
	ON t.session_key = s.session_key
LEFT JOIN `{PROJECT_ID}.{RAW_DATASET}.openf1_meetings` m
	ON t.meeting_key = m.meeting_key
LEFT JOIN `{PROJECT_ID}.{RAW_DATASET}.gemini_radio_analysis` a
	USING (gcs_uri)
WHERE a.gcs_uri IS NULL
ORDER BY t.date DESC
LIMIT @file_limit
"""

_bq_client = None
_genai_clients: dict[str, genai.Client] = {}


class RateLimiter:
	def __init__(self, rpm: int):
		self.rpm = rpm
		self.window = 60.0
		self.timestamps: deque[float] = deque()
		self.lock = threading.Lock()

	def acquire(self) -> None:
		while True:
			with self.lock:
				now = time.monotonic()
				while self.timestamps and now - self.timestamps[0] >= self.window:
					self.timestamps.popleft()
				if len(self.timestamps) < self.rpm:
					self.timestamps.append(now)
					return
				wait = self.window - (now - self.timestamps[0])
			time.sleep(wait)


_limiters: dict[str, RateLimiter] = {
	GEMINI_MODEL: RateLimiter(PRIMARY_RPM),
	FALLBACK_MODEL: RateLimiter(FALLBACK_RPM),
}


def is_rate_limit_error(exc: Exception) -> bool:
	msg = str(exc)
	return '429' in msg or 'RESOURCE_EXHAUSTED' in msg


def get_bq():
	global _bq_client
	if _bq_client is None:
		_bq_client = bigquery.Client(project=PROJECT_ID)
	return _bq_client


def get_genai(location: str) -> genai.Client:
	if location not in _genai_clients:
		_genai_clients[location] = genai.Client(vertexai=True, project=PROJECT_ID, location=location)
	return _genai_clients[location]


def fetch_pending(file_limit: int) -> list[dict]:
	job_config = bigquery.QueryJobConfig(
		query_parameters=[bigquery.ScalarQueryParameter('file_limit', 'INT64', file_limit)],
	)
	rows = get_bq().query(WATERMARK_QUERY, job_config=job_config).result()
	return [dict(r) for r in rows]


def build_metadata(row: dict) -> dict:
	return {
		'driver_name': row.get('driver_name'),
		'driver_acronym': row.get('driver_acronym'),
		'driver_number': row.get('driver_number'),
		'team_name': row.get('team_name'),
		'session_type': row.get('session_type'),
		'session_name': row.get('session_name'),
		'meeting_name': row.get('meeting_name'),
		'country_name': row.get('country_name'),
		'year': row.get('year'),
		'event_time': row['event_time'].isoformat() if row.get('event_time') else None,
	}


def call_gemini(row: dict, model: str, location: str) -> dict:
	client = get_genai(location)
	metadata_json = json.dumps(build_metadata(row), ensure_ascii=False, default=str)
	contents = [
		genai_types.Content(
			role='user',
			parts=[
				genai_types.Part.from_uri(file_uri=row['gcs_uri'], mime_type='audio/mpeg'),
				genai_types.Part.from_text(text=f'Context metadata:\n{metadata_json}'),
			],
		)
	]
	config = genai_types.GenerateContentConfig(
		system_instruction=PROMPT,
		response_mime_type='application/json',
		response_schema=RESPONSE_SCHEMA,
		audio_timestamp=True,
	)
	_limiters[model].acquire()
	response = client.models.generate_content(model=model, contents=contents, config=config)
	return json.loads(response.text)


def call_gemini_with_retry(row: dict, model: str, location: str, max_retries: int) -> dict:
	for attempt in range(max_retries):
		try:
			return call_gemini(row, model, location)
		except Exception as exc:
			if is_rate_limit_error(exc) and attempt < max_retries - 1:
				wait = (2**attempt) + random.random()
				logger.info('429 retry attempt=%d wait=%.1fs gcs_uri=%s model=%s', attempt + 1, wait, row['gcs_uri'], model)
				time.sleep(wait)
				continue
			raise
	raise RuntimeError('unreachable')


def analyze_one(row: dict) -> dict:
	gcs_uri = row['gcs_uri']
	model_used = GEMINI_MODEL
	try:
		result = call_gemini_with_retry(row, GEMINI_MODEL, GEMINI_LOCATION, MAX_RETRIES_429)
	except Exception as exc:
		logger.warning('primary model failed gcs_uri=%s err=%s; trying fallback', gcs_uri, exc)
		result = call_gemini(row, FALLBACK_MODEL, FALLBACK_LOCATION)
		model_used = FALLBACK_MODEL
	return {
		'gcs_uri': gcs_uri,
		'model': model_used,
		'processed_at': datetime.now(tz=timezone.utc).isoformat(),
		**result,
	}


def insert_analysis(row: dict) -> bool:
	table_id = f'{PROJECT_ID}.{RAW_DATASET}.gemini_radio_analysis'
	errors = get_bq().insert_rows_json(table_id, [row])
	if errors:
		logger.error('insert_rows_json failed gcs_uri=%s errors=%s', row.get('gcs_uri'), errors)
		return False
	return True


@functions_framework.http
def analyze(request):
	t0 = time.time()
	logger.info(
		'analyze started; model=%s location=%s file_limit=%d concurrency=%d primary_rpm=%d fallback_rpm=%d',
		GEMINI_MODEL,
		GEMINI_LOCATION,
		FILE_LIMIT,
		CONCURRENCY_LIMIT,
		PRIMARY_RPM,
		FALLBACK_RPM,
	)

	pending = fetch_pending(FILE_LIMIT)
	logger.info('pending radios for analysis: %d', len(pending))

	inserted = 0
	errors = 0
	done = 0
	with ThreadPoolExecutor(max_workers=CONCURRENCY_LIMIT) as pool:
		futures = {pool.submit(analyze_one, row): row for row in pending}
		for fut in as_completed(futures):
			row = futures[fut]
			done += 1
			gcs_uri = row.get('gcs_uri')
			try:
				result = fut.result()
			except Exception as exc:
				errors += 1
				logger.error('analyze_one failed gcs_uri=%s err=%s', gcs_uri, exc, exc_info=True)
				logger.info('analyzed %d/%d gcs_uri=%s', done, len(pending), gcs_uri)
				continue
			if insert_analysis(result):
				inserted += 1
				logger.info('analyzed %d/%d inserted gcs_uri=%s', done, len(pending), gcs_uri)
			else:
				errors += 1
				logger.info('analyzed %d/%d insert_failed gcs_uri=%s', done, len(pending), gcs_uri)

	elapsed = time.time() - t0
	logger.info('analyze finished; inserted=%d errors=%d elapsed=%.1fs', inserted, errors, elapsed)
	return (
		jsonify(
			{
				'status': 'ok',
				'pending': len(pending),
				'inserted': inserted,
				'errors': errors,
				'elapsed_seconds': round(elapsed, 1),
			}
		),
		200,
	)
