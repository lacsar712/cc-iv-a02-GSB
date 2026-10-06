"""LISTEN 叫醒为主，另有短间隔兜底认领，避免通知丢失。

认领那一刻在同一事务里把现行温带的上下限抄进这张单（抄本），
判定只吃抄本；之后再改带，已经领走的单结论不变。
温带还没设的 pending 单 JOIN 不上，先放着，设带后由兜底轮询领走。
"""
import threading
import time
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

from db import DSN, SCHEMA, connect
from rules import judge

CLAIM_SELECT_TAIL = """
           FROM iv_scans s
           JOIN ff_bands b
             ON b.band_key = s.band_key
            AND b.ff_low IS NOT NULL
            AND b.ff_high IS NOT NULL
           WHERE s.status = 'pending'
           FOR UPDATE OF s SKIP LOCKED LIMIT 1"""


def claim_id(conn, scan_id: int | None) -> bool:
    with conn.transaction():
        if scan_id is not None:
            row = conn.execute(
                """SELECT s.id, s.fill_factor, s.band_label,
                          b.ff_low AS ff_low, b.ff_high AS ff_high
                   FROM iv_scans s
                   JOIN ff_bands b
                     ON b.band_key = s.band_key
                    AND b.ff_low IS NOT NULL
                    AND b.ff_high IS NOT NULL
                   WHERE s.status = 'pending' AND s.id = %s
                   FOR UPDATE OF s SKIP LOCKED LIMIT 1""",
                (scan_id,),
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT s.id, s.fill_factor, s.band_label,
                          b.ff_low AS ff_low, b.ff_high AS ff_high"""
                + CLAIM_SELECT_TAIL
            ).fetchone()
        if row is None:
            return False
        now = datetime.now(timezone.utc)
        ff_low = float(row["ff_low"])
        ff_high = float(row["ff_high"])
        # 上下限此刻抄进抄本，判定只认抄本，不认后来的现行带
        verdict, reason = judge(float(row["fill_factor"]), ff_low, ff_high,
                                row["band_label"])
        conn.execute(
            """UPDATE iv_scans
                  SET status='done', verdict=%s, reason=%s,
                      ff_low_snap=%s, ff_high_snap=%s,
                      claimed_at=%s, processed_at=%s
                WHERE id=%s""",
            (verdict, reason, ff_low, ff_high, now, now, row["id"]),
        )
    return True


def drain(conn) -> bool:
    any_row = False
    while claim_id(conn, None):
        any_row = True
    return any_row


def poll_loop():
    while True:
        try:
            with connect() as conn:
                conn.execute(SCHEMA)
                drain(conn)
                conn.commit()
        except Exception as exc:
            print(f"poll error: {exc}", flush=True)
        time.sleep(0.6)


def listen_loop():
    while True:
        try:
            with psycopg.connect(DSN, row_factory=dict_row, autocommit=True) as conn:
                conn.execute("LISTEN iv_scan_new")
                for note in conn.notifies():
                    with connect() as work:
                        if note is not None:
                            claim_id(work, int(note.payload))
                        drain(work)
                        work.commit()
        except Exception as exc:
            print(f"listen error: {exc}", flush=True)
            time.sleep(1.5)


def main():
    print("pv iv-scan notify worker started", flush=True)
    threading.Thread(target=listen_loop, name="iv-listen", daemon=True).start()
    poll_loop()


if __name__ == "__main__":
    main()
