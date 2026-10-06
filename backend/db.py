import os
import psycopg
from psycopg.rows import dict_row

DSN = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:54402/pvivscan")


def connect():
    return psycopg.connect(DSN, row_factory=dict_row)


SCHEMA = """
CREATE TABLE IF NOT EXISTS iv_scans (
    id serial PRIMARY KEY,
    string_code text NOT NULL,
    voc_v double precision NOT NULL,
    isc_a double precision NOT NULL,
    fill_factor double precision NOT NULL,
    band text,
    status text NOT NULL DEFAULT 'pending',
    verdict text,
    reason text,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    processed_at timestamptz
);
ALTER TABLE iv_scans ADD COLUMN IF NOT EXISTS band text;
CREATE TABLE IF NOT EXISTS temp_bands (
    band text PRIMARY KEY,
    ff_min double precision NOT NULL,
    ff_max double precision NOT NULL,
    updated_by text,
    updated_at timestamptz
);
CREATE TABLE IF NOT EXISTS band_history (
    id serial PRIMARY KEY,
    band text NOT NULL,
    old_min double precision,
    old_max double precision,
    new_min double precision NOT NULL,
    new_max double precision NOT NULL,
    changed_by text NOT NULL,
    changed_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS claim_ledger (
    id serial PRIMARY KEY,
    scan_id integer NOT NULL,
    band text NOT NULL,
    ff_min double precision NOT NULL,
    ff_max double precision NOT NULL,
    claimed_by text NOT NULL,
    claimed_at timestamptz NOT NULL
);
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
