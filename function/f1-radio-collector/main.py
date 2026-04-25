import logging
import os
import re
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import functions_framework
import requests
from dotenv import load_dotenv
from flask import jsonify
from google.cloud import bigquery, storage

load_dotenv()

if os.getenv('K_SERVICE'):
	import google.cloud.logging as gcl

	gcl.Client().setup_logging()
else:
	logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

logger = logging.getLogger(__name__)

PROJECT_ID = os.environ['PROJECT_ID']
BUCKET_NAME = os.environ['BUCKET_NAME']
RAW_DATASET = os.getenv('RAW_DATASET', 'raw')
LOOKBACK_DAYS = int(os.getenv('LOOKBACK_DAYS', '7'))
MAX_WORKERS = int(os.getenv('MAX_WORKERS', '5'))
RATE_LIMIT_PER_MIN = int(os.getenv('RATE_LIMIT_PER_MIN', '25'))
SEASON_YEAR = int(os.getenv('SEASON_YEAR', '2025'))

OPENF1_BASE = 'https://api.openf1.org/v1'

_bq_client = None
_storage_client = None
_session = None


def get_bq():
	global _bq_client
	if _bq_client is None:
		_bq_client = bigquery.Client(project=PROJECT_ID)
	return _bq_client


def get_bucket():
	global _storage_client
	if _storage_client is None:
		_storage_client = storage.Client(project=PROJECT_ID)
	return _storage_client.bucket(BUCKET_NAME)


def get_session():
	global _session
	if _session is None:
		_session = requests.Session()
		_session.headers.update({'User-Agent': 'f1-team-radio-pipeline/0.1'})
	return _session


class RateLimiter:
	def __init__(self, max_calls: int, period_seconds: float):
		self.max_calls = max_calls
		self.period = period_seconds
		self.calls: deque[float] = deque()
		self.lock = threading.Lock()

	def acquire(self) -> None:
		while True:
			with self.lock:
				now = time.monotonic()
				while self.calls and now - self.calls[0] >= self.period:
					self.calls.popleft()
				if len(self.calls) < self.max_calls:
					self.calls.append(now)
					return
				wait = self.period - (now - self.calls[0])
			time.sleep(max(wait, 0.05))


_openf1_limiter = RateLimiter(max_calls=RATE_LIMIT_PER_MIN, period_seconds=60.0)


def openf1_get(path: str, params: dict | None = None, max_attempts: int = 5):
	url = f'{OPENF1_BASE}{path}'
	for attempt in range(1, max_attempts + 1):
		_openf1_limiter.acquire()
		try:
			resp = get_session().get(url, params=params, timeout=30)
		except requests.RequestException as exc:
			wait = min(2 ** attempt, 30)
			logger.warning('openf1_get network error path=%s attempt=%d err=%s; sleeping %ds', path, attempt, exc, wait)
			time.sleep(wait)
			continue
		if resp.status_code == 200:
			return resp.json()
		if resp.status_code == 404:
			logger.warning('openf1_get 404 path=%s params=%s', path, params)
			return []
		if resp.status_code == 429:
			retry_after = int(resp.headers.get('Retry-After', '60'))
			logger.warning('openf1_get 429 path=%s; sleeping Retry-After=%ds', path, retry_after)
			time.sleep(retry_after)
			continue
		if 500 <= resp.status_code < 600:
			wait = min(2 ** attempt, 30)
			logger.warning('openf1_get %d path=%s attempt=%d; sleeping %ds', resp.status_code, path, attempt, wait)
			time.sleep(wait)
			continue
		resp.raise_for_status()
	raise RuntimeError(f'openf1_get exhausted retries for {path} {params}')


def download_audio(url: str) -> bytes:
	for attempt in range(1, 5):
		try:
			resp = get_session().get(url, timeout=60)
		except requests.RequestException as exc:
			wait = min(2 ** attempt, 30)
			logger.warning('download_audio network error url=%s attempt=%d err=%s', url, attempt, exc)
			time.sleep(wait)
			continue
		if resp.status_code == 200:
			return resp.content
		if resp.status_code == 404:
			raise FileNotFoundError(url)
		if resp.status_code == 429:
			retry_after = int(resp.headers.get('Retry-After', '30'))
			time.sleep(retry_after)
			continue
		if 500 <= resp.status_code < 600:
			time.sleep(min(2 ** attempt, 30))
			continue
		resp.raise_for_status()
	raise RuntimeError(f'download_audio exhausted retries for {url}')


def refresh_dim(table: str, rows: list[dict]) -> int:
	if not rows:
		logger.info('refresh_dim %s skipped: empty payload', table)
		return 0
	table_id = f'{PROJECT_ID}.{RAW_DATASET}.{table}'
	job_config = bigquery.LoadJobConfig(
		write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
		source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
		schema_update_options=[],
	)
	job = get_bq().load_table_from_json(rows, table_id, job_config=job_config)
	job.result()
	logger.info('refresh_dim %s loaded=%d', table, len(rows))
	return len(rows)


def dedupe_drivers(rows: list[dict]) -> list[dict]:
	seen: set[tuple[int, int]] = set()
	out: list[dict] = []
	for r in rows:
		key = (r['session_key'], r['driver_number'])
		if key in seen:
			continue
		seen.add(key)
		out.append(r)
	return out


def get_active_sessions(now_utc: datetime) -> list[dict]:
	cutoff = now_utc - timedelta(days=LOOKBACK_DAYS)
	query = f"""
		SELECT session_key, meeting_key, date_end
		FROM `{PROJECT_ID}.{RAW_DATASET}.openf1_sessions`
		WHERE date_end >= TIMESTAMP('{cutoff.isoformat()}')
		  AND date_end <= TIMESTAMP('{now_utc.isoformat()}')
		  AND IFNULL(is_cancelled, FALSE) = FALSE
	"""
	return [dict(row) for row in get_bq().query(query).result()]


def get_existing_gcs_uris(session_keys: list[int]) -> set[str]:
	if not session_keys:
		return set()
	keys_csv = ','.join(str(k) for k in session_keys)
	query = f"""
		SELECT DISTINCT gcs_uri
		FROM `{PROJECT_ID}.{RAW_DATASET}.openf1_team_radios`
		WHERE session_key IN ({keys_csv})
	"""
	return {row['gcs_uri'] for row in get_bq().query(query).result()}


def slugify_iso(date_str: str) -> str:
	return re.sub(r'[^0-9A-Za-z]+', '-', date_str).strip('-')


def gcs_object_name(radio: dict) -> str:
	parts = urlparse(radio['recording_url']).path.split('/')
	original = parts[-1] if parts else f'{radio["driver_number"]}.mp3'
	return (
		f'f1/year={SEASON_YEAR}'
		f'/meeting={radio["meeting_key"]}'
		f'/session={radio["session_key"]}'
		f'/driver={radio["driver_number"]}'
		f'/{slugify_iso(radio["date"])}_{original}'
	)


def download_and_upload(radio: dict) -> dict:
	object_name = gcs_object_name(radio)
	blob = get_bucket().blob(object_name)
	gcs_uri = f'gs://{BUCKET_NAME}/{object_name}'
	if not blob.exists(get_bucket().client):
		audio = download_audio(radio['recording_url'])
		blob.upload_from_string(audio, content_type='audio/mpeg')
		logger.info('uploaded %s (%d bytes)', gcs_uri, len(audio))
	else:
		logger.info('blob already exists, reusing %s', gcs_uri)
	return {
		'date': radio['date'],
		'driver_number': radio['driver_number'],
		'meeting_key': radio['meeting_key'],
		'session_key': radio['session_key'],
		'recording_url': radio['recording_url'],
		'gcs_uri': gcs_uri,
		'inserted_at': datetime.now(tz=timezone.utc).isoformat(),
	}


def insert_team_radios(rows: list[dict]) -> int:
	if not rows:
		return 0
	table_id = f'{PROJECT_ID}.{RAW_DATASET}.openf1_team_radios'
	job_config = bigquery.LoadJobConfig(
		write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
		source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
	)
	job = get_bq().load_table_from_json(rows, table_id, job_config=job_config)
	job.result()
	return len(rows)


@functions_framework.http
def collect(request):
	t0 = time.time()
	now_utc = datetime.now(tz=timezone.utc)
	logger.info('collect started; season=%d lookback_days=%d', SEASON_YEAR, LOOKBACK_DAYS)

	meetings = openf1_get('/meetings', {'year': SEASON_YEAR})
	sessions = openf1_get('/sessions', {'year': SEASON_YEAR})
	refresh_dim('openf1_meetings', meetings)
	refresh_dim('openf1_sessions', sessions)

	if not meetings:
		logger.warning('no meetings found for season=%d', SEASON_YEAR)
		all_drivers: list[dict] = []
	else:
		all_drivers = []
		for m in meetings:
			mk = m.get('meeting_key')
			if mk is None:
				continue
			all_drivers.extend(openf1_get('/drivers', {'meeting_key': mk}))
		logger.info('drivers fetched across %d meetings: %d rows', len(meetings), len(all_drivers))
	refresh_dim('openf1_drivers', dedupe_drivers(all_drivers))

	active = get_active_sessions(now_utc)
	logger.info('active sessions in last %d days: %d', LOOKBACK_DAYS, len(active))

	all_radios: list[dict] = []
	for s in active:
		radios = openf1_get('/team_radio', {'session_key': s['session_key']})
		all_radios.extend(radios)
	logger.info('team radios fetched from openf1: %d', len(all_radios))

	existing = get_existing_gcs_uris([s['session_key'] for s in active])
	logger.info('existing gcs_uri rows in BQ: %d', len(existing))

	new_radios = [r for r in all_radios if f'gs://{BUCKET_NAME}/{gcs_object_name(r)}' not in existing]
	logger.info('new radios to download: %d', len(new_radios))

	rows: list[dict] = []
	errors = 0
	with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
		futures = {pool.submit(download_and_upload, r): r for r in new_radios}
		for fut in as_completed(futures):
			try:
				rows.append(fut.result())
			except Exception as exc:
				errors += 1
				radio = futures[fut]
				logger.error('failed to process radio %s: %s', radio.get('recording_url'), exc, exc_info=True)

	inserted = insert_team_radios(rows)
	elapsed = time.time() - t0
	logger.info('collect finished; inserted=%d errors=%d elapsed=%.1fs', inserted, errors, elapsed)
	return (
		jsonify(
			{
				'status': 'ok',
				'season': SEASON_YEAR,
				'active_sessions': len(active),
				'fetched_radios': len(all_radios),
				'new_radios': len(new_radios),
				'inserted': inserted,
				'errors': errors,
				'elapsed_seconds': round(elapsed, 1),
			}
		),
		200,
	)
