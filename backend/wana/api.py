"""MineSense Wana API (FastAPI).

Roles: requests without a key are treated as a *miner*; requests with
`Authorization: Bearer <WANA_GEOLOGIST_KEY>` are the *geologist*. Location precision is
enforced here on the server, not in the browser.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import uuid
from pathlib import Path
from typing import Optional

import numpy as np
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db
from .cards import build_card
from .config import PHOTOS, ROOT, STACK, load_config
from .model import _grid_from, latest_version, run_dir
from .stack import load_occurrences, load_stack

GEO_KEY = os.environ.get("WANA_GEOLOGIST_KEY", "")
if not GEO_KEY:
    GEO_KEY = "dev-geologist-key"
    print("WARNING: WANA_GEOLOGIST_KEY not set; using the development key 'dev-geologist-key'.")

app = FastAPI(title="MineSense Wana API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("WANA_CORS", "http://localhost:5173").split(","),
                   allow_methods=["*"], allow_headers=["*"])

_lock = threading.Lock()
_state: dict = {}


def state():
    v = latest_version()
    if v < 0:
        raise HTTPException(503, "No model has been trained yet. Run `python -m wana all-sample` or `python -m wana train`.")
    if _state.get("v") != v:
        with _lock:
            model = json.loads((run_dir(v) / "model.json").read_text())
            grids = dict(np.load(run_dir(v) / "grids.npz"))
            z, meta = load_stack()
            g = _grid_from(meta)
            occ = load_occurrences(g)
            _state.update(v=v, model=model, grids=grids, X=z["X"], slope=z["slope"], grid=g, occ=occ,
                          occ_rc=[(o["row"], o["col"]) for o in occ], meta=meta)
    return _state


def role(authorization: Optional[str] = Header(None)) -> str:
    if authorization and authorization.startswith("Bearer ") and secrets.compare_digest(authorization[7:], GEO_KEY):
        return "geologist"
    return "miner"


def geologist_only(r: str = Depends(role)):
    if r != "geologist":
        raise HTTPException(403, "Geologist key required.")
    return r


@app.get("/api/meta")
def meta(r: str = Depends(role)):
    s = state()
    m = s["model"]
    cfg = load_config()
    return {"name": cfg.name, "bbox": cfg.bbox, "role": r, "version": m["version"], "sample_data": m["any_sample"],
            "provenance": m["provenance"], "features": m["features"], "feature_labels": m["feature_labels"],
            "coef_mean": m["coef_mean"], "created": m["created"]}


@app.get("/api/overlays")
def overlays(r: str = Depends(role)):
    s = state()
    m = s["model"]
    v = m["version"]
    rank = m["overlays"]["rank" if r == "geologist" else "rank_coarse"]
    out = {"rank": {"url": f"/api/files/run/{v}/{rank['file']}", "coords": rank["coords"]},
           "uncertainty": {"url": f"/api/files/run/{v}/{m['overlays']['uncertainty']['file']}",
                           "coords": m["overlays"]["uncertainty"]["coords"]}}
    ev_path = STACK / "evidence.json"
    if ev_path.exists():
        out["evidence"] = {k: {"url": f"/api/files/stack/{e['file']}", "coords": e["coords"], "label": e["label"]}
                           for k, e in json.loads(ev_path.read_text()).items()}
    return out


@app.get("/api/files/run/{v}/{name}")
def run_file(v: int, name: str, r: str = Depends(role)):
    if name not in ("rank.png", "rank_coarse.png", "unc.png"):
        raise HTTPException(404)
    if name == "rank.png" and r != "geologist":
        raise HTTPException(403, "Full-resolution ranking is for registered users.")
    p = run_dir(v) / name
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/files/stack/{name}")
def stack_file(name: str):
    p = STACK / name
    if not (name.startswith("ev_") and name.endswith(".png") and p.exists()):
        raise HTTPException(404)
    return FileResponse(p, media_type="image/png")


def _public_target(t, s, r):
    g = s["grids"]
    rr, cc = t["row"], t["col"]
    base = {"id": t["id"], "rank": t["rank"], "score": round(float(g["wscore"][rr, cc]), 1),
            "confidence": ["Low", "Medium", "High"][int(g["conf"][rr, cc])]}
    if r == "geologist":
        base.update(lon=t["lon"], lat=t["lat"], precision_m=s["grid"].res)
    else:
        base.update(lon=t["miner_lon"], lat=t["miner_lat"], precision_m=load_config().miner_grid_m, block=t["miner_block"])
    return base


@app.get("/api/targets")
def targets(r: str = Depends(role)):
    s = state()
    return [_public_target(t, s, r) for t in s["model"]["targets"]]


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
def card(target: Optional[str] = None, lon: Optional[float] = None, lat: Optional[float] = None,
         lang: str = "en", r: str = Depends(role)):
    s = state()
    g = s["grid"]
    t = None
    if target:
        t = next((x for x in s["model"]["targets"] if x["id"] == target), None)
        if not t:
            raise HTTPException(404, "Unknown target")
        rr, cc = t["row"], t["col"]
    elif lon is not None and lat is not None:
        a, b = g.from_lonlat([lon], [lat])
        if not g.inside(a, b)[0]:
            raise HTTPException(400, "Point is outside the pilot area")
        rr, cc = int(a[0]), int(b[0])
        if r != "geologist":   # miners get the 1 km block's best cell, so clicking can't pinpoint hot cells
            rr, cc = _block_best(s, rr, cc)
    else:
        raise HTTPException(400, "Give a target id or lon and lat")
    if t:
        pt = _public_target(t, s, r)
        loc = {"lon": pt["lon"], "lat": pt["lat"], "precision_m": pt["precision_m"]}
    elif r == "geologist":
        lo, la = g.to_lonlat([rr], [cc])
        loc = {"lon": round(float(lo[0]), 5), "lat": round(float(la[0]), 5), "precision_m": g.res}
    else:
        from .model import miner_block
        bl, ba, ring = miner_block(g, rr, cc, load_config().miner_grid_m)
        loc = {"lon": round(bl, 4), "lat": round(ba, 4), "precision_m": load_config().miner_grid_m, "block": ring}
    return build_card(s["model"], s["grids"], s["X"], s["slope"], rr, cc, s["occ_rc"], lang=lang,
                      target=t and {"id": t["id"], "rank": t["rank"], "of": len(s["model"]["targets"])}, role=r, loc=loc)


@app.get("/api/occurrences")
def occurrences(_: str = Depends(geologist_only)):
    s = state()
    test = set(s["model"]["test_ids"])
    return [{"id": o["id"], "lon": o["lon"], "lat": o["lat"], "source": o["source"],
             "set": "holdout" if o["id"] in test else "train"} for o in s["occ"]]


@app.get("/api/validation")
def validation():
    s = state()
    m = s["model"]
    return {"version": m["version"], "metrics": m["metrics"], "sample_data": m["any_sample"],
            "holdout_rule": load_config().holdout_rule}


@app.get("/api/model/versions")
def versions():
    out = []
    for v in range(latest_version() + 1):
        p = run_dir(v) / "model.json"
        if p.exists():
            m = json.loads(p.read_text())
            out.append({"version": v, "created": m["created"], "note": m["note"],
                        "metrics": {k: x for k, x in m["metrics"].items() if k != "curve"}})
    return out


# ---------- field records ----------
CHECK_KEYS = ("black_grains", "heavy", "brown_streak", "green_host", "old_pits")


@app.post("/api/records")
async def create_record(client_id: str = Form(...), sample_no: str = Form(...), lon: float = Form(...),
                        lat: float = Form(...), accuracy_m: float = Form(None), checks: str = Form("{}"),
                        notes: str = Form(""), target_id: str = Form(""), observer: str = Form(""),
                        created_at: str = Form(...), photo: UploadFile | None = File(None)):
    try:
        uuid.UUID(client_id)
    except ValueError:
        raise HTTPException(400, "client_id must be a UUID")
    ck = {k: bool(json.loads(checks).get(k, False)) for k in CHECK_KEYS}
    with db.conn() as c:
        ex = c.execute("SELECT id, status FROM records WHERE client_id=?", (client_id,)).fetchone()
        if ex:   # idempotent re-sync from an offline phone
            return {"id": ex["id"], "status": ex["status"], "duplicate": True}
    photo_name = None
    if photo is not None and photo.filename:
        data = await photo.read()
        if len(data) > 8_000_000:
            raise HTTPException(413, "Photo is larger than 8 MB")
        if not (data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n" or data[8:12] == b"WEBP"):
            raise HTTPException(415, "Photo must be JPEG, PNG or WebP")
        photo_name = f"{client_id}{Path(photo.filename).suffix.lower()[:5] or '.jpg'}"
        (PHOTOS / photo_name).write_bytes(data)
    with db.conn() as c:
        cur = c.execute(
            "INSERT INTO records (client_id, sample_no, target_id, lon, lat, accuracy_m, checks, notes, photo, observer,"
            " created_at, received_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (client_id, sample_no, target_id or None, lon, lat, accuracy_m, json.dumps(ck), notes, photo_name,
             observer, created_at, db.now()))
        return {"id": cur.lastrowid, "status": "pending", "duplicate": False}


@app.get("/api/records")
def list_records(_: str = Depends(geologist_only)):
    with db.conn() as c:
        return [db.row_to_dict(r) for r in c.execute("SELECT * FROM records ORDER BY id DESC")]


@app.get("/api/photos/{name}")
def photo(name: str, _: str = Depends(geologist_only)):
    p = (PHOTOS / name).resolve()
    if p.parent != PHOTOS.resolve() or not p.exists():
        raise HTTPException(404)
    return FileResponse(p)


class Review(BaseModel):
    status: str = Field(pattern="^(endorsed|rejected|pending)$")
    lab_cr2o3: Optional[float] = Field(None, ge=0, le=70)
    note: str = ""
    reviewer: str = "geologist"


@app.post("/api/records/{rid}/review")
def review(rid: int, body: Review, _: str = Depends(geologist_only)):
    with db.conn() as c:
        row = c.execute("SELECT used_in_version FROM records WHERE id=?", (rid,)).fetchone()
        if not row:
            raise HTTPException(404)
        if row["used_in_version"] is not None:
            raise HTTPException(409, "Record already used in a model version; it is part of the audit trail.")
        c.execute("UPDATE records SET status=?, lab_cr2o3=?, review_note=?, reviewer=?, reviewed_at=? WHERE id=?",
                  (body.status, body.lab_cr2o3, body.note, body.reviewer, db.now(), rid))
    return {"id": rid, "status": body.status}


@app.post("/api/model/retrain")
def retrain(_: str = Depends(geologist_only)):
    with db.conn() as c:
        n = c.execute("SELECT COUNT(*) FROM records WHERE status IN ('endorsed','rejected') AND used_in_version IS NULL").fetchone()[0]
    if n == 0:
        raise HTTPException(400, "No newly reviewed records to add.")
    before = {t["id"]: t["rank"] for t in state()["model"]["targets"]}
    with _lock:
        m = db.retrain_from_db(note=f"{n} reviewed field record(s) added")
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


dist = Path(os.environ.get("WANA_WEB_DIST", ROOT / "frontend" / "dist"))
if dist.exists():
    app.mount("/", StaticFiles(directory=dist, html=True), name="web")
