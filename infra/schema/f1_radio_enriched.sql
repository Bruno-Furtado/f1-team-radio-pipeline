CREATE OR REPLACE VIEW `${PROJECT_ID}.mart.f1_radio_enriched` AS
SELECT
	t.date AS event_time,
	t.gcs_uri,
	t.recording_url,
	t.driver_number,
	d.full_name AS driver_name,
	d.name_acronym AS driver_acronym,
	d.headshot_url,
	d.country_code AS driver_country_code,
	d.team_name,
	d.team_colour,
	s.session_key,
	s.session_type,
	s.session_name,
	s.date_start AS session_date_start,
	s.date_end AS session_date_end,
	m.meeting_key,
	m.meeting_name,
	m.meeting_official_name,
	m.country_name,
	m.country_code,
	m.country_flag,
	m.circuit_short_name AS circuit_name,
	m.circuit_image,
	m.circuit_info_url,
	m.circuit_type,
	m.circuit_key,
	m.location,
	m.gmt_offset AS meeting_gmt_offset,
	m.date_start AS meeting_date_start,
	m.date_end AS meeting_date_end,
	m.year,
	a.sentiment_score,
	a.sentiment_label,
	a.emotion,
	a.is_complaint,
	a.complaint_target,
	a.is_positive_outcome,
	a.topic,
	a.summary,
	a.language_detected,
	a.transcription,
	a.model,
	a.processed_at
FROM `${PROJECT_ID}.raw.openf1_team_radios` t
LEFT JOIN `${PROJECT_ID}.raw.openf1_drivers` d
	ON t.driver_number = d.driver_number AND t.session_key = d.session_key
LEFT JOIN `${PROJECT_ID}.raw.openf1_sessions` s
	ON t.session_key = s.session_key
LEFT JOIN `${PROJECT_ID}.raw.openf1_meetings` m
	ON t.meeting_key = m.meeting_key
LEFT JOIN `${PROJECT_ID}.raw.gemini_radio_analysis` a
	USING (gcs_uri);
