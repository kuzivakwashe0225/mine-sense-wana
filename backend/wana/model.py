"""Explainable chrome prospectivity model.

Method (deliberately simple so a geologist can audit it):
  * presence-background logistic regression (scikit-learn) on standardised evidence layers
  * bootstrap ensemble -> mean ranking + spread (uncertainty); missing layers add uncertainty
  * per-cell explanation = coefficient x standardised value for each layer
  * spatial hold-out: occurrences south of a latitude are never used for training, only for testing
Field records: geologist-endorsed finds are added as presences, confirmed blanks as absences.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from . import render
from .config import RUNS, ensure_dirs, load_config
from .grid import Grid
from .stack import FEATURES, load_occurrences, load_stack


def _grid_from(meta) -> Grid:
    from affine import Affine
    gd = meta["grid"]
    return Grid(gd["crs"], Affine(*gd["transform"]), gd["width"], gd["height"], gd["res"])


def latest_version() -> int:
    vs = [int(p.name[1:]) for p in RUNS.glob("v*") if p.name[1:].isdigit() and (p / "model.json").exists()]
    return max(vs) if vs else -1


def run_dir(v: int):
    return RUNS / f"v{v}"


def split_occurrences(occ, cfg):
    rule = cfg.holdout_rule
    if rule.get("type") == "lat_below":
        test = [o for o in occ if o["lat"] < rule["value"]]
    else:
        test = []
    ids = {o["id"] for o in test}
    return [o for o in occ if o["id"] not in ids], test


def train(field_presences=(), field_absences=(), note="", parent=None) -> dict:
    """field_presences / field_absences: iterables of (row, col)."""
    cfg = load_config()
    ensure_dirs()
    z, meta = load_stack()
    g = _grid_from(meta)
    names = [str(n) for n in z["names"]]
    X = z["X"].astype("float32")                      # (F, H, W)
    F, H, W = X.shape
    N = H * W
    flat = X.reshape(F, N).T                          # (N, F)
    finite = np.isfinite(flat)
    mu = np.array([np.nanmean(flat[:, j]) for j in range(F)])
    sd = np.array([np.nanstd(flat[:, j]) or 1.0 for j in range(F)])
    Z = np.where(finite, (flat - mu) / sd, 0.0).astype("float32")
    Z = np.clip(Z, -5, 5)

    occ = load_occurrences(g)
    train_occ, test_occ = split_occurrences(occ, cfg)
    pres = [o["row"] * W + o["col"] for o in train_occ] + [r * W + c for r, c in field_presences]
    absn = [r * W + c for r, c in field_absences]
    if len(pres) < 5:
        raise SystemExit(f"Only {len(pres)} training occurrences inside the pilot area; need at least 5.")

    rng = np.random.default_rng(cfg.seed + (parent or 0))
    coefs, inter = [], []
    for _ in range(cfg.n_models):
        P = rng.choice(pres, size=len(pres), replace=True)
        B = rng.integers(0, N, size=cfg.n_background)
        idx = np.concatenate([P, B, np.array(absn, dtype=int)])
        y = np.concatenate([np.ones(len(P)), np.zeros(len(B) + len(absn))])
        wp = len(B) / len(P)
        w = np.concatenate([np.full(len(P), wp), np.ones(len(B)), np.full(len(absn), wp * 0.6)])
        m = LogisticRegression(C=0.5, max_iter=2000)
        m.fit(Z[idx], y, sample_weight=w)
        coefs.append(m.coef_[0])
        inter.append(m.intercept_[0])
    coefs, inter = np.array(coefs), np.array(inter)

    logits = Z @ coefs.T + inter                      # (N, M)
    mean, spread = logits.mean(1), logits.std(1)
    order = np.argsort(-mean)
    rank = np.empty(N, dtype=np.int64)
    rank[order] = np.arange(N)
    score = (100.0 * (1 - rank / (N - 1))).astype("float32")      # percentile: 100 = best cell
    wscore = (100.0 / (1 + np.exp(-(mean - mean.max() + 2.2))) * (1 + np.exp(-2.2))).clip(0, 100).astype("float32")
    wabs = np.abs(coefs.mean(0))
    missing_pen = ((~finite) * wabs).sum(1) / (wabs.sum() + 1e-9)
    unc = (spread + 1.5 * missing_pen).astype("float32")
    q1, q2 = np.quantile(unc, [0.45, 0.8])
    conf = np.where(unc >= q2, 0, np.where(unc >= q1, 1, 2)).astype("uint8")  # 0 Low, 1 Medium, 2 High

    # validation on the spatial hold-out
    metrics = {"n_train": len(pres), "n_test": len(test_occ), "n_absences": len(absn)}
    if test_occ:
        ti = np.array([o["row"] * W + o["col"] for o in test_occ])
        frac = np.sort(rank[ti] / N)
        curve = [[a / 100, float((frac <= a / 100).mean())] for a in range(0, 101)]
        bg = rng.integers(0, N, 20000)
        auc = roc_auc_score(np.r_[np.ones(len(ti)), np.zeros(len(bg))], np.r_[mean[ti], mean[bg]])
        metrics.update({"auc_holdout": float(auc), "capture_top10": curve[10][1], "capture_top20": curve[20][1],
                        "curve": curve})
    tri = np.array(pres[: len(train_occ)])
    if len(tri):
        bg = rng.integers(0, N, 20000)
        metrics["auc_train"] = float(roc_auc_score(np.r_[np.ones(len(tri)), np.zeros(len(bg))], np.r_[mean[tri], mean[bg]]))

    # targets: best cells with minimum spacing, one per miner block (miners see blocks, so two targets
    # in one block would draw on top of each other), stable ids across versions
    sp = cfg.target_min_spacing_m / g.res
    bx, by = _block_ids(g, cfg.miner_grid_m)
    chosen, blocks = [], set()
    for i in order[:20000]:
        r, c = divmod(int(i), W)
        if (by[r], bx[c]) not in blocks and all((r - a) ** 2 + (c - b) ** 2 >= sp * sp for a, b in chosen):
            chosen.append((r, c))
            blocks.add((by[r], bx[c]))
            if len(chosen) >= cfg.target_count:
                break
    v = latest_version() + 1
    prev = _prev_targets(v - 1)
    used, next_id = set(), max([int(t["id"].split("T")[-1]) for t in prev] + [0])
    lons, lats = g.to_lonlat([a for a, _ in chosen], [b for _, b in chosen])
    targets = []
    for k, ((r, c), lon, lat) in enumerate(zip(chosen, lons, lats), 1):
        match = next((t for t in prev if t["id"] not in used and
                      (t["row"] - r) ** 2 + (t["col"] - c) ** 2 < (600 / g.res) ** 2), None)
        if match:
            tid = match["id"]
            used.add(tid)
        else:
            next_id += 1
            tid = f"SHU-T{next_id:02d}"
        targets.append({"id": tid, "rank": k, "row": r, "col": c, "lon": float(lon), "lat": float(lat)})

    out = run_dir(v)
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out / "grids.npz", score=score.reshape(H, W), wscore=wscore.reshape(H, W),
                        unc=unc.reshape(H, W), conf=conf.reshape(H, W), z=Z.reshape(H, W, F))
    overlays = {
        "rank": {"file": "rank.png", "coords": render.png_rank(score.reshape(H, W), g, out / "rank.png")},
        "uncertainty": {"file": "unc.png", "coords": render.png_hatch(
            ((conf == 0) & (score >= 70)).reshape(H, W), g, out / "unc.png")},
        "rank_coarse": {"file": "rank_coarse.png", "coords": render.png_rank(
            _pct(block_max(score.reshape(H, W), g, cfg.miner_grid_m)), g, out / "rank_coarse.png")},
    }
    for t in targets:
        t["miner_lon"], t["miner_lat"], t["miner_block"] = miner_block(g, t["row"], t["col"], cfg.miner_grid_m)
    model = {
        "version": v, "parent": parent, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": note or ("Baseline: known occurrences only" if v == 0 else ""),
        "features": names, "feature_labels": {n: FEATURES[n]["label"] for n in names},
        "mean": mu.tolist(), "std": sd.tolist(), "coef_mean": coefs.mean(0).tolist(), "coef_sd": coefs.std(0).tolist(),
        "intercept_mean": float(inter.mean()), "n_models": cfg.n_models, "metrics": metrics,
        "targets": targets, "overlays": overlays, "grid": meta["grid"], "provenance": meta["provenance"],
        "any_sample": meta["any_sample"], "test_ids": [o["id"] for o in test_occ],
    }
    (out / "model.json").write_text(json.dumps(model, indent=2))
    return model


def _block_ids(g: Grid, size_m: float):
    t = g.transform
    xs = t.c + (np.arange(g.width) + 0.5) * g.res
    ys = t.f - (np.arange(g.height) + 0.5) * g.res
    bx = np.floor(xs / size_m).astype(int)
    by = np.floor(ys / size_m).astype(int)
    return bx, by


def _pct(a: np.ndarray) -> np.ndarray:
    from scipy.stats import rankdata
    return (100.0 * (rankdata(a.ravel(), method="max") - 1) / (a.size - 1)).reshape(a.shape).astype("float32")


def block_max(a: np.ndarray, g: Grid, size_m: float) -> np.ndarray:
    """Replace each cell by the max of its size_m x size_m block (hides the exact hot cell)."""
    bx, by = _block_ids(g, size_m)
    BX, BY = np.meshgrid(bx - bx.min(), by - by.min())
    key = BY * (bx.max() - bx.min() + 1) + BX
    mx = np.full(key.max() + 1, -np.inf)
    np.maximum.at(mx, key.ravel(), a.ravel())
    return mx[key].astype("float32")


def miner_block(g: Grid, r: int, c: int, size_m: float):
    from pyproj import Transformer
    t = g.transform
    x, y = t.c + (c + 0.5) * g.res, t.f - (r + 0.5) * g.res
    x0, y0 = np.floor(x / size_m) * size_m, np.floor(y / size_m) * size_m
    tr = Transformer.from_crs(g.crs, "EPSG:4326", always_xy=True)
    ring = [tr.transform(px, py) for px, py in
            [(x0, y0), (x0 + size_m, y0), (x0 + size_m, y0 + size_m), (x0, y0 + size_m), (x0, y0)]]
    cx, cy = tr.transform(x0 + size_m / 2, y0 + size_m / 2)
    return float(cx), float(cy), [[float(a), float(b)] for a, b in ring]


def _prev_targets(v):
    p = run_dir(v) / "model.json"
    return json.loads(p.read_text())["targets"] if v >= 0 and p.exists() else []


def render_evidence():
    """PNG of each raw evidence layer (for the 'show evidence' switch)."""
    z, meta = load_stack()
    g = _grid_from(meta)
    out = {}
    from .config import STACK
    for k, n in enumerate(z["names"]):
        n = str(n)
        out[n] = {"file": f"ev_{n}.png", "coords": render.png_evidence(z["X"][k], g, STACK / f"ev_{n}.png"),
                  "label": FEATURES[n]["label"]}
    (STACK / "evidence.json").write_text(json.dumps(out, indent=2))
    return out
