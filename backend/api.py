import os
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from litestar import Litestar, Request, get, post, put
from litestar.exceptions import HTTPException
from passlib.context import CryptContext

from db import SCHEMA, connect
from rules import judge

SECRET = os.environ.get("JWT_SECRET", "pvivscan-dev-secret")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
USERS = {
    "scanner": {"role": "writer", "password_hash": pwd.hash("scan123456")},
    "watcher": {"role": "reader", "password_hash": pwd.hash("watch123456")},
}

# 温带唯一来源：key 入库，label 上画面，两套温带各守一条闭区间、不共线
BANDS = [
    {"key": "high", "label": "高温带"},
    {"key": "low", "label": "低温带"},
]
BAND_BY_KEY = {b["key"]: b for b in BANDS}


def dump(row):
    out = dict(row)
    for key, val in list(out.items()):
        if hasattr(val, "isoformat"):
            out[key] = val.isoformat()
    return out


def seed():
    with connect() as conn:
        conn.execute(SCHEMA)
        n = conn.execute("SELECT COUNT(*) AS n FROM iv_scans").fetchone()["n"]
        if n == 0:
            now = datetime.now(timezone.utc)
            # 已完成的种子单自带认领瞬间抄本，即使现行温带尚未设置也不受影响
            samples = [
                ("阵列A-串03", 41.2, 9.1, 0.78, "high", "高温带", 0.72, 0.85, "合格"),
                ("阵列B-串11", 38.0, 8.4, 0.61, "low", "低温带", 0.65, 0.72, "衰减"),
            ]
            for code, voc, isc, ff, bkey, blabel, low, high, expect in samples:
                verdict, reason = judge(ff, low, high, blabel)
                assert verdict == expect
                conn.execute(
                    """INSERT INTO iv_scans
                       (string_code, voc_v, isc_a, fill_factor,
                        band_key, band_label, ff_low_snap, ff_high_snap, claimed_at,
                        status, verdict, reason, created_by, created_at, processed_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'done',%s,%s,'scanner',%s,%s)""",
                    (code, voc, isc, ff, bkey, blabel, low, high, now,
                     verdict, reason, now, now),
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
        raise HTTPException(status_code=401, detail="未登录")
    return user


def need_writer(request: Request, action: str = "提交IV扫描"):
    user = need_login(request)
    if user["role"] != "writer":
        raise HTTPException(status_code=403, detail=f"仅扫描员可{action}")
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
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    exp = datetime.now(timezone.utc) + timedelta(hours=8)
    token = jwt.encode(
        {"sub": username, "role": user["role"], "exp": exp}, SECRET, algorithm="HS256"
    )
    return {"access_token": token, "username": username, "role": user["role"]}


def band_to_dto(row_or_none, band: dict) -> dict:
    if row_or_none is None or row_or_none["ff_low"] is None:
        return {
            "band_key": band["key"],
            "label": band["label"],
            "configured": False,
            "ff_low": None,
            "ff_high": None,
            "updated_by": None,
            "updated_at": None,
        }
    return {
        "band_key": band["key"],
        "label": row_or_none["label"],
        "configured": True,
        "ff_low": row_or_none["ff_low"],
        "ff_high": row_or_none["ff_high"],
        "updated_by": row_or_none["updated_by"],
        "updated_at": row_or_none["updated_at"].isoformat()
        if row_or_none["updated_at"]
        else None,
    }


@get("/api/bands")
async def list_bands(request: Request) -> list:
    """现行温带。观察员可翻，未设过的温带 configured=false，画面写还没设温带。"""
    need_login(request)
    with connect() as conn:
        rows = {r["band_key"]: r for r in conn.execute("SELECT * FROM ff_bands").fetchall()}
        return [band_to_dto(rows.get(b["key"]), b) for b in BANDS]


@put("/api/bands/{band_key:str}")
async def set_band(request: Request, band_key: str) -> dict:
    """改带：只允许扫描员；每次改动落一条履历。观察员调用得 403。"""
    user = need_writer(request, action="改温带")
    band = BAND_BY_KEY.get(band_key)
    if band is None:
        raise HTTPException(status_code=404, detail="没有这条温带")
    data = await request.json()
    try:
        low = float(data.get("ff_low"))
        high = float(data.get("ff_high"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="上下限必须是数字")
    if not (0 <= low <= high <= 1):
        raise HTTPException(status_code=400, detail="需满足 0 ≤ 下限 ≤ 上限 ≤ 1")
    now = datetime.now(timezone.utc)
    with connect() as conn:
        with conn.transaction():
            old = conn.execute(
                "SELECT * FROM ff_bands WHERE band_key=%s FOR UPDATE",
                (band_key,),
            ).fetchone()
            old_low = old["ff_low"] if old else None
            old_high = old["ff_high"] if old else None
            conn.execute(
                """INSERT INTO ff_bands (band_key, label, ff_low, ff_high, updated_by, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (band_key) DO UPDATE SET
                     label=EXCLUDED.label, ff_low=EXCLUDED.ff_low,
                     ff_high=EXCLUDED.ff_high, updated_by=EXCLUDED.updated_by,
                     updated_at=EXCLUDED.updated_at""",
                (band_key, band["label"], low, high, user["username"], now),
            )
            conn.execute(
                """INSERT INTO ff_band_history
                   (band_key, label, low_before, high_before, low_after, high_after,
                    changed_by, changed_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (band_key, band["label"], old_low, old_high, low, high,
                 user["username"], now),
            )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM ff_bands WHERE band_key=%s", (band_key,)
        ).fetchone()
    return band_to_dto(row, band)


@get("/api/band-history")
async def list_band_history(request: Request) -> list:
    """改带履历：观察员可翻，不可改。"""
    need_login(request)
    with connect() as conn:
        rows = conn.execute(
            """SELECT id, band_key, label, low_before, high_before, low_after, high_after,
                      changed_by, changed_at
               FROM ff_band_history ORDER BY id DESC"""
        ).fetchall()
        return [dump(r) for r in rows]


@get("/api/transcripts")
async def list_transcripts(request: Request) -> list:
    """认领抄本：工人认领那一瞬抄进单子的上下限，之后改带与这张单无关。"""
    need_login(request)
    with connect() as conn:
        rows = conn.execute(
            """SELECT id, string_code, fill_factor, band_key, band_label,
                      ff_low_snap, ff_high_snap, claimed_at, status, verdict
               FROM iv_scans
               WHERE claimed_at IS NOT NULL
               ORDER BY claimed_at DESC, id DESC"""
        ).fetchall()
        return [dump(r) for r in rows]


@get("/api/logs")
async def list_logs(request: Request) -> list:
    need_login(request)
    with connect() as conn:
        rows = conn.execute(
            """SELECT id, string_code, voc_v, isc_a, fill_factor,
                      band_key, band_label, ff_low_snap, ff_high_snap,
                      status, verdict, reason, created_by, created_at, claimed_at, processed_at
               FROM iv_scans ORDER BY id DESC"""
        ).fetchall()
        return [dump(r) for r in rows]


@post("/api/logs", status_code=201)
async def create_log(request: Request) -> dict:
    user = need_writer(request)
    data = await request.json()
    # 录入必须点温带，漏点整笔退：任何落库动作之前先拦
    band_key = (data.get("band_key") or "").strip()
    band = BAND_BY_KEY.get(band_key)
    if band is None:
        raise HTTPException(status_code=400, detail="必须点选温带（高温带/低温带），漏点整笔拒收")
    code = (data.get("string_code") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="组串编号不能为空")
    try:
        voc = float(data.get("voc_v"))
        isc = float(data.get("isc_a"))
        ff = float(data.get("fill_factor"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="电压电流与填充因子必须是数字")
    now = datetime.now(timezone.utc)
    with connect() as conn:
        row = conn.execute(
            """INSERT INTO iv_scans
               (string_code, voc_v, isc_a, fill_factor,
                band_key, band_label, status, created_by, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,'pending',%s,%s)
               RETURNING id, string_code, voc_v, isc_a, fill_factor,
                         band_key, band_label, ff_low_snap, ff_high_snap,
                         status, verdict, reason, created_by, created_at,
                         claimed_at, processed_at""",
            (code, voc, isc, ff, band["key"], band["label"], user["username"], now),
        ).fetchone()
        conn.commit()
        return dump(row)


app = Litestar(route_handlers=[
    health, login, list_bands, set_band, list_band_history,
    list_transcripts, list_logs, create_log,
])
