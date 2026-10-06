import os
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from litestar import Litestar, Request, get, post
from litestar.exceptions import HTTPException
from litestar.status_codes import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN
from passlib.context import CryptContext

from db import SCHEMA, connect
from rules import judge

SECRET = os.environ.get("JWT_SECRET", "pvivscan-dev-secret")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
USERS = {
    "scanner": {"role": "writer", "password_hash": pwd.hash("scan123456")},
    "watcher": {"role": "reader", "password_hash": pwd.hash("watch123456")},
}

BAND_NAMES = ("高温带", "低温带")
DEFAULT_BANDS = {"低温带": (0.65, 0.72), "高温带": (0.72, 0.85)}


def dump(row):
    out = dict(row)
    for key, val in list(out.items()):
        if hasattr(val, "isoformat"):
            out[key] = val.isoformat()
    return out


def seed():
    now = datetime.now(timezone.utc)
    with connect() as conn:
        conn.execute(SCHEMA)
        n = conn.execute("SELECT COUNT(*) AS n FROM temp_bands").fetchone()["n"]
        if n == 0:
            for band, (lo, hi) in DEFAULT_BANDS.items():
                conn.execute(
                    """INSERT INTO temp_bands (band, ff_min, ff_max, updated_by, updated_at)
                       VALUES (%s,%s,%s,'system',%s)""",
                    (band, lo, hi, now),
                )
                conn.execute(
                    """INSERT INTO band_history
                       (band, old_min, old_max, new_min, new_max, changed_by, changed_at)
                       VALUES (%s,NULL,NULL,%s,%s,'system',%s)""",
                    (band, lo, hi, now),
                )
        n = conn.execute("SELECT COUNT(*) AS n FROM iv_scans").fetchone()["n"]
        if n == 0:
            samples = [
                ("阵列A-串03", 41.2, 9.1, 0.78, "高温带", "合格"),
                ("阵列B-串11", 38.0, 8.4, 0.61, "低温带", "衰减"),
            ]
            for code, voc, isc, ff, band, expect in samples:
                lo, hi = DEFAULT_BANDS[band]
                verdict, reason = judge(ff, lo, hi)
                assert verdict == expect
                row = conn.execute(
                    """INSERT INTO iv_scans
                       (string_code, voc_v, isc_a, fill_factor, band, status, verdict, reason,
                        created_by, created_at, processed_at)
                       VALUES (%s,%s,%s,%s,%s,'done',%s,%s,'scanner',%s,%s)
                       RETURNING id""",
                    (code, voc, isc, ff, band, verdict, reason, now, now),
                ).fetchone()
                conn.execute(
                    """INSERT INTO claim_ledger
                       (scan_id, band, ff_min, ff_max, claimed_by, claimed_at)
                       VALUES (%s,%s,%s,%s,'seed',%s)""",
                    (row["id"], band, lo, hi, now),
                )
        conn.commit()


seed()


def user_from(request: Request):
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    try:
        payload = jwt.decode(auth.split(" ", 1)[1].strip(), SECRET, algorithms=["HS256"])
    except JWTError:
        return None
    sub = payload.get("sub")
    if sub not in USERS:
        return None
    return {"username": sub, "role": payload.get("role")}


def need_login(request: Request):
    user = user_from(request)
    if user is None:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="未登录")
    return user


def need_writer(request: Request):
    user = need_login(request)
    if user["role"] != "writer":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="仅扫描员可提交IV扫描")
    return user


@get("/api/health")
async def health() -> dict:
    return {"status": "ok", "service": "pv-string-iv-scan"}


@post("/api/auth/login")
async def login(request: Request) -> dict:
    data = await request.json()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    user = USERS.get(username)
    if not user or not pwd.verify(password, user["password_hash"]):
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    exp = datetime.now(timezone.utc) + timedelta(hours=8)
    token = jwt.encode(
        {"sub": username, "role": user["role"], "exp": exp}, SECRET, algorithm="HS256"
    )
    return {"access_token": token, "username": username, "role": user["role"]}


@get("/api/logs")
async def list_logs(request: Request) -> list:
    need_login(request)
    with connect() as conn:
        rows = conn.execute(
            """SELECT id, string_code, voc_v, isc_a, fill_factor, band, status, verdict, reason,
                      created_by, created_at, processed_at
               FROM iv_scans ORDER BY id DESC"""
        ).fetchall()
        return [dump(r) for r in rows]


@post("/api/logs", status_code=201)
async def create_log(request: Request) -> dict:
    user = need_writer(request)
    data = await request.json()
    code = (data.get("string_code") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="组串编号不能为空")
    band = (data.get("band") or "").strip()
    if not band:
        raise HTTPException(status_code=400, detail="必须点选温带，漏点整笔退回")
    try:
        voc = float(data.get("voc_v"))
        isc = float(data.get("isc_a"))
        ff = float(data.get("fill_factor"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="电压电流与填充因子必须是数字")
    now = datetime.now(timezone.utc)
    with connect() as conn:
        exists = conn.execute(
            "SELECT band FROM temp_bands WHERE band = %s", (band,)
        ).fetchone()
        if exists is None:
            raise HTTPException(status_code=400, detail=f"温带 {band} 不存在，整笔退回")
        row = conn.execute(
            """INSERT INTO iv_scans
               (string_code, voc_v, isc_a, fill_factor, band, status, created_by, created_at)
               VALUES (%s,%s,%s,%s,%s,'pending',%s,%s)
               RETURNING id, string_code, voc_v, isc_a, fill_factor, band, status, verdict, reason,
                         created_by, created_at, processed_at""",
            (code, voc, isc, ff, band, user["username"], now),
        ).fetchone()
        conn.commit()
        return dump(row)


@get("/api/bands")
async def list_bands(request: Request) -> list:
    need_login(request)
    with connect() as conn:
        rows = conn.execute(
            """SELECT band, ff_min, ff_max, updated_by, updated_at
               FROM temp_bands ORDER BY band"""
        ).fetchall()
        return [dump(r) for r in rows]


@post("/api/bands")
async def set_band(request: Request) -> dict:
    user = need_writer(request)
    data = await request.json()
    band = (data.get("band") or "").strip()
    if band not in BAND_NAMES:
        raise HTTPException(status_code=400, detail="未知温带，只能改高温带或低温带")
    try:
        ff_min = float(data.get("ff_min"))
        ff_max = float(data.get("ff_max"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="上下限必须是数字")
    if ff_min > ff_max:
        raise HTTPException(status_code=400, detail="下限不能高于上限")
    now = datetime.now(timezone.utc)
    with connect() as conn:
        old = conn.execute(
            "SELECT ff_min, ff_max FROM temp_bands WHERE band = %s", (band,)
        ).fetchone()
        conn.execute(
            """INSERT INTO temp_bands (band, ff_min, ff_max, updated_by, updated_at)
               VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (band) DO UPDATE
               SET ff_min = EXCLUDED.ff_min, ff_max = EXCLUDED.ff_max,
                   updated_by = EXCLUDED.updated_by, updated_at = EXCLUDED.updated_at""",
            (band, ff_min, ff_max, user["username"], now),
        )
        conn.execute(
            """INSERT INTO band_history
               (band, old_min, old_max, new_min, new_max, changed_by, changed_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (
                band,
                old["ff_min"] if old else None,
                old["ff_max"] if old else None,
                ff_min,
                ff_max,
                user["username"],
                now,
            ),
        )
        conn.commit()
    return {
        "band": band,
        "ff_min": ff_min,
        "ff_max": ff_max,
        "updated_by": user["username"],
        "updated_at": now.isoformat(),
    }


@get("/api/bands/history")
async def list_band_history(request: Request) -> list:
    need_login(request)
    with connect() as conn:
        rows = conn.execute(
            """SELECT id, band, old_min, old_max, new_min, new_max, changed_by, changed_at
               FROM band_history ORDER BY id DESC"""
        ).fetchall()
        return [dump(r) for r in rows]


@get("/api/claim-ledger")
async def list_claim_ledger(request: Request) -> list:
    need_login(request)
    with connect() as conn:
        rows = conn.execute(
            """SELECT id, scan_id, band, ff_min, ff_max, claimed_by, claimed_at
               FROM claim_ledger ORDER BY id DESC"""
        ).fetchall()
        return [dump(r) for r in rows]


app = Litestar(
    route_handlers=[
        health,
        login,
        list_logs,
        create_log,
        list_bands,
        set_band,
        list_band_history,
        list_claim_ledger,
    ]
)
