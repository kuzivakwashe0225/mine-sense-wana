"""MineSense Wana API (FastAPI).

Who may do what (enforced here, never only in the browser):
  * anyone         - the miner map: ranking in 1 km blocks, target cards, validation, data sources
  * signed in      - send field records
  * geologist      - exact locations, occurrences, photos, review, retrain
  * admin          - manage accounts and roles
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import numpy as np
from fastapi import Depends, FastAPI, File, Form, Header, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import accounts, cache, db, obs, storage
from .auth import Principal, admin, current, geologist, signed_in
from .cards import build_card
from .config import ROOT, STACK, load_config
from .model import _grid_from, latest_version, run_dir
from .obs import BusinessError, PlatformError, UserError
from .settings import settings
from .stack import load_occurrences, load_stack

obs.setup_logging()


@asynccontextmanager
async def lifespan(_app):
    stop = threading.Event()
    threading.Thread(target=accounts.bootstrap_admin, args=(stop,), daemon=True, name="admin-bootstrap").start()
    yield
    stop.set()


app = FastAPI(title="MineSense Wana API", version="0.2.0", lifespan=lifespan)
obs.install(app)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors, allow_methods=["GET", "POST", "PUT"],
                   allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "If-None-Match", "X-Request-ID"],
                   expose_headers=["ETag", "X-Request-ID", "Retry-After"])

_lock = threading.Lock()
_state: dict = {}


def state():
    v = latest_version()
    if v < 0:
        raise PlatformError("No model has been trained yet. Run `python -m wana all-sample` or `python -m wana train`.",
                            "no_model")
    if _state.get("v") != v:
        with _lock:
            model = json.loads((run_dir(v) / "model.json").read_text())
            grids = dict(np.load(run_dir(v) / "grids.npz"))
            z, meta = load_stack()
            g = _grid_from(meta)
            occ = load_occurrences(g)
            _state.clear()
            _state.update(v=v, model=model, grids=grids, X=z["X"], slope=z["slope"], grid=g, occ=occ,
                          occ_rc=[(o["row"], o["col"]) for o in occ], meta=meta)
            obs.MODEL_VERSION.set(v)
    return _state


def cached_json(request: Request, data, private=False):
    """JSON with an ETag. Pollers send If-None-Match and get an empty 304 when nothing changed."""
    body = json.dumps(data, separators=(",", ":"), default=float).encode()
    tag = '"' + hashlib.blake2s(body, digest_size=12).hexdigest() + '"'
    # Vary on Authorization: a geologist's answer must never be served to a miner from a shared cache
    headers = {"ETag": tag, "Cache-Control": "private, no-cache" if private else "no-cache", "Vary": "Authorization"}
    if request.headers.get("if-none-match") == tag:
        return Response(status_code=304, headers=headers)
    return Response(body, media_type="application/json", headers=headers)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# ---------- platform ----------
@app.get("/api/health")
def health():
    """Liveness: the process answers."""
    return {"status": "ok"}


@app.get("/api/ready")
def ready():
    """Readiness: every dependency answers. Used by the container health check and Prometheus."""
    checks = {"model": latest_version() >= 0, "redis": cache.ping(), "storage": storage.ping()}
    if settings.auth_enabled:
        checks["keycloak"] = accounts.kc.ping()
    ok = all(checks.values())
    return JSONResponse({"status": "ok" if ok else "degraded", "checks": checks}, status_code=200 if ok else 503)


@app.get("/api/config")
def config():
    """What the browser needs to sign in and how strict the session policy is."""
    return {"auth": {"enabled": settings.auth_enabled, "url": settings.kc_issuer_base, "realm": settings.kc_realm,
                     "client_id": settings.kc_web_client},
            "session": {"idle_seconds": settings.idle_seconds, "warn_seconds": settings.warn_seconds,
                        "reading_seconds": settings.reading_seconds}}


@app.get("/api/me")
def me(p: Principal = Depends(current)):
    return {"signed_in": p.signed_in, "sub": p.sub, "email": p.email, "name": p.name,
            "roles": sorted(p.roles & set(accounts.ROLES)), "view": p.view}


@app.get("/api/me/profile")
def my_profile(p: Principal = Depends(signed_in)):
    return {**accounts.profile(p.sub), "roles": sorted(p.roles & set(accounts.ROLES))}


class ProfileIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    organisation: str = Field("", max_length=120)


@app.put("/api/me/profile")
def update_my_profile(body: ProfileIn, p: Principal = Depends(signed_in)):
    cache.rate_limit(f"profile:{p.sub}", 20, 3600, "profile changes")
    accounts.update_profile(p.sub, body.name, body.organisation)
    return {**accounts.profile(p.sub), "roles": sorted(p.roles & set(accounts.ROLES))}


@app.get("/api/me/records")
def my_records(request: Request, p: Principal = Depends(signed_in)):
    """The signed-in person's own field records and what the geologist decided (exact points are theirs)."""
    with db.conn() as c:
        rows = [db.row_to_dict(r) for r in c.execute(
            "SELECT id, sample_no, target_id, lon, lat, checks, notes, status, lab_cr2o3, review_note, created_at,"
            " reviewed_at, used_in_version FROM records WHERE user_sub=? ORDER BY id DESC LIMIT 200", (p.sub,))]
    return cached_json(request, rows, private=True)


class ClientError(BaseModel):
    kind: str = Field(pattern="^(user|business|platform|network)$")
    message: str = Field(max_length=500)
    code: str = Field("", max_length=60)
    where: str = Field("", max_length=200)
    request_id: str = Field("", max_length=64)
    stack: str = Field("", max_length=2000)


@app.post("/api/client-errors", status_code=204)
def client_errors(body: ClientError, request: Request, p: Principal = Depends(current)):
    """Errors seen in browsers and phones, so platform problems are visible even when users don't report them."""
    cache.rate_limit(f"cerr:{client_ip(request)}", 30, 60, "error reports")
    obs.CLIENT_ERRORS.labels(body.kind).inc()
    import logging
    logging.getLogger("wana.client").warning("client %s error %s at %s: %s (server request %s)", body.kind, body.code,
                                             body.where, body.message, body.request_id or "-",
                                             extra={"kind": body.kind})
    return Response(status_code=204)


# ---------- accounts ----------
class Signup(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    name: str = Field(min_length=2, max_length=80)
    organisation: str = Field("", max_length=120)
    accept: bool = Field(description="Accepts that Wana shows places worth checking and gives no mining rights")


@app.post("/api/auth/signup", status_code=202)
def signup(body: Signup, request: Request):
    if not settings.auth_enabled:
        raise PlatformError("Accounts are not set up on this server.", "auth_disabled")
    if not body.accept:
        raise UserError("Please confirm you understand that Wana gives no mining rights.", "terms_required", 422)
    cache.rate_limit(f"signup:ip:{client_ip(request)}", 5, 3600, "sign-up attempts from this network")
    cache.rate_limit(f"signup:email:{body.email.strip().lower()}", 3, 86400, "sign-up emails to this address")
    accounts.signup(body.email, body.name, body.organisation)
    return {"status": "sent", "message": "If this address can receive email, a link to set your password is on its way. "
                                         "It works for 24 hours."}


@app.get("/api/admin/users")
def admin_users(_: Principal = Depends(admin)):
    return accounts.kc.list_users()


class RoleChange(BaseModel):
    role: str
    grant: bool


@app.post("/api/admin/users/{uid}/roles")
def admin_role(uid: str, body: RoleChange, p: Principal = Depends(admin)):
    accounts.set_role(p.sub, uid, body.role, body.grant)
    return {"id": uid, "role": body.role, "grant": body.grant}


@app.post("/api/admin/users/{uid}/invite", status_code=202)
def admin_invite(uid: str, p: Principal = Depends(admin)):
    cache.rate_limit(f"invite:{uid}", 3, 3600, "invites for this account")
    accounts.resend_invite(uid)
    return {"status": "sent"}


# ---------- map ----------
@app.get("/api/meta")
def meta(request: Request, p: Principal = Depends(current)):
    s = state()
    m = s["model"]
    cfg = load_config()
    return cached_json(request, {"name": cfg.name, "bbox": cfg.bbox, "role": p.view, "version": m["version"],
                                 "sample_data": m["any_sample"], "provenance": m["provenance"], "features": m["features"],
                                 "feature_labels": m["feature_labels"], "coef_mean": m["coef_mean"], "created": m["created"]})


@app.get("/api/overlays")
def overlays(request: Request, p: Principal = Depends(current)):
    s = state()
    m = s["model"]
    v = m["version"]
    rank = m["overlays"]["rank" if p.is_geologist else "rank_coarse"]
    out = {"rank": {"url": f"/api/files/run/{v}/{rank['file']}", "coords": rank["coords"]},
           "uncertainty": {"url": f"/api/files/run/{v}/{m['overlays']['uncertainty']['file']}",
                           "coords": m["overlays"]["uncertainty"]["coords"]}}
    ev_path = STACK / "evidence.json"
    if ev_path.exists():
        out["evidence"] = {k: {"url": f"/api/files/stack/{e['file']}", "coords": e["coords"], "label": e["label"]}
                           for k, e in json.loads(ev_path.read_text()).items()}
    return cached_json(request, out)


@app.get("/api/files/run/{v}/{name}")
def run_file(v: int, name: str, p: Principal = Depends(current)):
    if name not in ("rank.png", "rank_coarse.png", "unc.png"):
        raise UserError("Not found", "not_found", 404)
    if name == "rank.png" and not p.is_geologist:
        raise UserError("Full-resolution ranking is for geologist accounts.", "forbidden", 403)
    f = run_dir(v) / name
    if not f.exists():
        raise UserError("Not found", "not_found", 404)
    cc = "private, max-age=86400" if name == "rank.png" else "public, max-age=86400"
    return FileResponse(f, media_type="image/png", headers={"Cache-Control": cc})


@app.get("/api/files/stack/{name}")
def stack_file(name: str):
    f = STACK / name
    if not (name.startswith("ev_") and name.endswith(".png") and f.exists()):
        raise UserError("Not found", "not_found", 404)
    return FileResponse(f, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


def _public_target(t, s, p: Principal):
    g = s["grids"]
    rr, cc = t["row"], t["col"]
    base = {"id": t["id"], "rank": t["rank"], "score": round(float(g["wscore"][rr, cc]), 1),
            "confidence": ["Low", "Medium", "High"][int(g["conf"][rr, cc])]}
    if p.is_geologist:
        base.update(lon=t["lon"], lat=t["lat"], precision_m=s["grid"].res)
    else:
        base.update(lon=t["miner_lon"], lat=t["miner_lat"], precision_m=load_config().miner_grid_m, block=t["miner_block"])
    return base


@app.get("/api/targets")
def targets(request: Request, p: Principal = Depends(current)):
    s = state()
    return cached_json(request, [_public_target(t, s, p) for t in s["model"]["targets"]], private=p.is_geologist)


def _block_best(s, rr, cc):
    from .model import _block_ids
    g = s["grid"]
    if "blocks" not in s:
        s["blocks"] = _block_ids(g, load_config().miner_grid_m)
    bx, by = s["blocks"]
    rows = np.where(by == by[rr])[0]
    cols = np.where(bx == bx[cc])[0]
    sub = s["grids"]["wscore"][rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]
    i, j = np.unravel_index(np.argmax(sub), sub.shape)
    return int(rows[0] + i), int(cols[0] + j)


@app.get("/api/card")
def card(request: Request, target: Optional[str] = None, lon: Optional[float] = None, lat: Optional[float] = None,
         lang: str = "en", p: Principal = Depends(current)):
    s = state()
    g = s["grid"]
    t = None
    if target:
        t = next((x for x in s["model"]["targets"] if x["id"] == target), None)
        if not t:
            raise UserError("Unknown target", "unknown_target", 404)
        rr, cc = t["row"], t["col"]
    elif lon is not None and lat is not None:
        a, b = g.from_lonlat([lon], [lat])
        if not g.inside(a, b)[0]:
            raise UserError("Point is outside the pilot area", "outside_area", 400)
        rr, cc = int(a[0]), int(b[0])
        if not p.is_geologist:   # miners get the 1 km block's best cell, so clicking can't pinpoint hot cells
            rr, cc = _block_best(s, rr, cc)
    else:
        raise UserError("Give a target id or lon and lat", "bad_request", 400)
    if t:
        pt = _public_target(t, s, p)
        loc = {"lon": pt["lon"], "lat": pt["lat"], "precision_m": pt["precision_m"]}
    elif p.is_geologist:
        lo, la = g.to_lonlat([rr], [cc])
        loc = {"lon": round(float(lo[0]), 5), "lat": round(float(la[0]), 5), "precision_m": g.res}
    else:
        from .model import miner_block
        bl, ba, ring = miner_block(g, rr, cc, load_config().miner_grid_m)
        loc = {"lon": round(bl, 4), "lat": round(ba, 4), "precision_m": load_config().miner_grid_m, "block": ring}
    out = build_card(s["model"], s["grids"], s["X"], s["slope"], rr, cc, s["occ_rc"], lang=lang,
                     target=t and {"id": t["id"], "rank": t["rank"], "of": len(s["model"]["targets"])}, role=p.view, loc=loc)
    return cached_json(request, out, private=p.is_geologist)


@app.get("/api/occurrences")
def occurrences(request: Request, _: Principal = Depends(geologist)):
    s = state()
    test = set(s["model"]["test_ids"])
    return cached_json(request, [{"id": o["id"], "lon": o["lon"], "lat": o["lat"], "source": o["source"],
                                  "set": "holdout" if o["id"] in test else "train"} for o in s["occ"]], private=True)


@app.get("/api/validation")
def validation(request: Request):
    s = state()
    m = s["model"]
    return cached_json(request, {"version": m["version"], "metrics": m["metrics"], "sample_data": m["any_sample"],
                                 "holdout_rule": load_config().holdout_rule})


@app.get("/api/model/versions")
def versions(request: Request):
    out = []
    for v in range(latest_version() + 1):
        f = run_dir(v) / "model.json"
        if f.exists():
            m = json.loads(f.read_text())
            out.append({"version": v, "created": m["created"], "note": m["note"],
                        "metrics": {k: x for k, x in m["metrics"].items() if k != "curve"}})
    return cached_json(request, out)


# ---------- field records ----------
CHECK_KEYS = ("black_grains", "heavy", "brown_streak", "green_host", "old_pits")
_IMAGE_TYPES = {b"\xff\xd8\xff": ("image/jpeg", ".jpg"), b"\x89PNG\r\n\x1a\n": ("image/png", ".png")}


def _image_type(data: bytes):
    for magic, t in _IMAGE_TYPES.items():
        if data.startswith(magic):
            return t
    if data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None


@app.post("/api/records")
async def create_record(client_id: str = Form(...), sample_no: str = Form(..., max_length=60),
                        lon: float = Form(..., ge=-180, le=180), lat: float = Form(..., ge=-90, le=90),
                        accuracy_m: float = Form(None), checks: str = Form("{}", max_length=500),
                        notes: str = Form("", max_length=2000), target_id: str = Form("", max_length=20),
                        observer: str = Form("", max_length=120), created_at: str = Form(..., max_length=40),
                        photo: UploadFile | None = File(None), p: Principal = Depends(signed_in)):
    try:
        uuid.UUID(client_id)
    except ValueError:
        raise UserError("client_id must be a UUID", "invalid_client_id", 400)
    try:
        ck = {k: bool(json.loads(checks).get(k, False)) for k in CHECK_KEYS}
    except (ValueError, AttributeError):
        raise UserError("checks must be a JSON object", "invalid_checks", 400)
    with db.conn() as c:
        ex = c.execute("SELECT id, status FROM records WHERE client_id=?", (client_id,)).fetchone()
        if ex:   # idempotent re-sync from an offline phone: not an error, the record is already safe
            obs.EVENTS.labels("field_record", "duplicate").inc()
            return {"id": ex["id"], "status": ex["status"], "duplicate": True}
    cache.rate_limit(f"records:{p.sub}", 120, 3600, "records in an hour")
    photo_name = None
    if photo is not None and photo.filename:
        data = await photo.read(8_000_001)
        if len(data) > 8_000_000:
            raise UserError("Photo is larger than 8 MB", "too_large", 413)
        kind = _image_type(data)
        if not kind:
            raise UserError("Photo must be JPEG, PNG or WebP", "unsupported_media", 415)
        photo_name = f"{client_id}{kind[1]}"   # extension from the content, never from the client's filename
        storage.put(photo_name, data, kind[0])
    with db.conn() as c:
        cur = c.execute(
            "INSERT INTO records (client_id, sample_no, target_id, lon, lat, accuracy_m, checks, notes, photo, observer,"
            " created_at, received_at, user_sub, user_email) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (client_id, sample_no, target_id or None, lon, lat, accuracy_m, json.dumps(ck), notes, photo_name,
             observer or p.name, created_at, db.now(), p.sub, p.email))
        obs.EVENTS.labels("field_record", "created").inc()
        return {"id": cur.lastrowid, "status": "pending", "duplicate": False}


@app.get("/api/records")
def list_records(request: Request, _: Principal = Depends(geologist)):
    with db.conn() as c:
        rows = [db.row_to_dict(r) for r in c.execute("SELECT * FROM records ORDER BY id DESC")]
    return cached_json(request, rows, private=True)


@app.get("/api/photos/{name}")
def photo(name: str, _: Principal = Depends(geologist)):
    if "/" in name or "\\" in name or name.startswith("."):
        raise UserError("Not found", "not_found", 404)
    data = storage.get(name)
    if data is None:
        raise UserError("Not found", "not_found", 404)
    kind = _image_type(data) or ("application/octet-stream", "")
    return Response(data, media_type=kind[0], headers={"Cache-Control": "private, max-age=3600"})


class Review(BaseModel):
    status: str = Field(pattern="^(endorsed|rejected|pending)$")
    lab_cr2o3: Optional[float] = Field(None, ge=0, le=70)
    note: str = Field("", max_length=1000)


@app.post("/api/records/{rid}/review")
def review(rid: int, body: Review, p: Principal = Depends(geologist),
           idempotency_key: Optional[str] = Header(None, max_length=80)):
    if idempotency_key and (hit := cache.idempotent_get(f"review:{p.sub}", idempotency_key)):
        return hit
    with db.conn() as c:
        row = c.execute("SELECT used_in_version FROM records WHERE id=?", (rid,)).fetchone()
        if not row:
            raise UserError("No such record", "not_found", 404)
        if row["used_in_version"] is not None:
            raise BusinessError("Record already used in a model version; it is part of the audit trail.", "record_locked")
        c.execute("UPDATE records SET status=?, lab_cr2o3=?, review_note=?, reviewer=?, reviewed_at=? WHERE id=?",
                  (body.status, body.lab_cr2o3, body.note, p.email or p.name, db.now(), rid))
    out = {"id": rid, "status": body.status, "lab_cr2o3": body.lab_cr2o3}
    if idempotency_key:
        cache.idempotent_put(f"review:{p.sub}", idempotency_key, out)
    obs.EVENTS.labels("review", body.status).inc()
    return out


def _pending_reviews() -> int:
    with db.conn() as c:
        return c.execute("SELECT COUNT(*) FROM records WHERE status IN ('endorsed','rejected') AND used_in_version IS NULL").fetchone()[0]


def _retrain(n, progress=None):
    before = {t["id"]: t["rank"] for t in state()["model"]["targets"]}
    t0 = time.perf_counter()
    with _lock:
        m = db.retrain_from_db(note=f"{n} reviewed field record(s) added", progress=progress)
    obs.RETRAIN_SECONDS.observe(time.perf_counter() - t0)
    obs.EVENTS.labels("retrain", "done").inc()
    changes = []
    for t in m["targets"]:
        b = before.get(t["id"])
        if b is None:
            changes.append({"id": t["id"], "change": "new"})
        elif b != t["rank"]:
            changes.append({"id": t["id"], "change": b - t["rank"]})
    dropped = [k for k in before if k not in {t["id"] for t in m["targets"]}]
    return {"version": m["version"], "metrics": {k: x for k, x in m["metrics"].items() if k != "curve"},
            "changes": changes, "dropped": dropped}


def _check_retrain():
    n = _pending_reviews()
    if n == 0:
        raise BusinessError("No newly reviewed records to add.", "nothing_to_retrain", 400)
    return n


@app.post("/api/model/retrain")
def retrain(_: Principal = Depends(geologist)):
    n = _check_retrain()
    with cache.Lock("retrain", busy_message="The map is already being updated. Wait for it to finish."):
        return _retrain(n)


@app.post("/api/model/retrain/stream")
def retrain_stream(_: Principal = Depends(geologist)):
    """Same as /retrain, but streams progress as newline-delimited JSON so the page can show each stage live."""
    n = _check_retrain()
    lock = cache.Lock("retrain", busy_message="The map is already being updated. Wait for it to finish.")
    lock.__enter__()   # refuse a second run up front, before the 200 status is sent
    q: queue.Queue = queue.Queue()

    def work():
        try:
            q.put({"done": _retrain(n, progress=lambda stage, f: q.put({"stage": stage, "progress": round(f, 3)}))})
        except Exception as e:  # noqa: BLE001
            import logging
            logging.getLogger("wana.errors").error("platform error: retrain failed", exc_info=e)
            obs.ERRORS.labels("platform", "retrain_failed").inc()
            q.put({"error": {"kind": "platform", "code": "retrain_failed",
                             "message": "Updating the map failed. It has been logged; the previous version is still in use."}})
        finally:
            lock.__exit__()
            q.put(None)

    threading.Thread(target=work, daemon=True, name="retrain").start()

    def events():
        yield json.dumps({"stage": f"Adding {n} reviewed record(s)", "progress": 0.0}) + "\n"
        while (item := q.get()) is not None:
            yield json.dumps(item, default=float) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


dist = Path(os.environ.get("WANA_WEB_DIST", ROOT / "frontend" / "dist"))
if dist.exists():
    app.mount("/", StaticFiles(directory=dist, html=True), name="web")
