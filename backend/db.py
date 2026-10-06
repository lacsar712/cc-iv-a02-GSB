import os
import psycopg
from psycopg.rows import dict_row

DSN = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:54402/pvivscan")


def connect():
    return psycopg.connect(DSN, row_factory=dict_row)


SCHEMA = """
CREATE TABLE IF NOT EXISTS ff_bands (
    band_key text PRIMARY KEY,
    label text NOT NULL,
    ff_low double precision,
    ff_high double precision,
    updated_by text,
    updated_at timestamptz
);

CREATE TABLE IF NOT EXISTS ff_band_history (
    id serial PRIMARY KEY,
    band_key text NOT NULL,
    label text NOT NULL,
    low_before double precision,
    high_before double precision,
    low_after double precision,
    high_after double precision,
    changed_by text NOT NULL,
    changed_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ff_band_history_band ON ff_band_history(band_key, id);

CREATE TABLE IF NOT EXISTS iv_scans (
    id serial PRIMARY KEY,
    string_code text NOT NULL,
    voc_v double precision NOT NULL,
    isc_a double precision NOT NULL,
    fill_factor  double precision NOT NULL,
    band_key     text NOT NULL,
    band_label   text NOT NULL,
    ff_low_snap  double precision,
    ff_high_snap double precision,
    claimed_at   timestamptz,
    status text NOT NULL DEFAULT 'pending',
    verdict text,
    reason text,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    processed_at timestamptz
);
CREATE INDEX IF NOT EXISTS iv_scans_status_id ON iv_scans(status, id);

CREATE OR REPLACE FUNCTION notify_iv_scan() RETURNS trigger AS $$
BEGIN
  PERFORM pg_notify('iv_scan_new', NEW.id::text);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_iv_scan_notify ON iv_scans;
CREATE TRIGGER trg_iv_scan_notify
AFTER INSERT ON iv_scans
FOR EACH ROW EXECUTE FUNCTION notify_iv_scan();
"""
