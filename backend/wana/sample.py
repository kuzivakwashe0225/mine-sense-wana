"""Synthetic sample dataset in exactly the formats ingest.py and the digitising team produce.

It lets the whole system be built and tested before real data arrives. Every file is tagged
SAMPLE, and the app shows a banner whenever any sample layer is in use. Never present results
from this dataset as real.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone

import numpy as np
import rasterio
from rasterio import features
from scipy.ndimage import gaussian_filter
from shapely.geometry import LineString, mapping, shape

from .config import INPUTS, RAW, ensure_dirs, load_config
from .grid import make_grid
from .ingest import _write


def _field(rng, shape, sigma):
    f = gaussian_filter(rng.standard_normal(shape), sigma)
    f -= f.min()
    return f / (f.max() + 1e-9)


def generate(seed: int = 7):
    cfg = load_config()
    ensure_dirs()
    g = make_grid(cfg)
    H, W = g.shape
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:H, 0:W].astype("float32")
    ykm, xkm = yy * g.res / 1000, xx * g.res / 1000  # km from top-left
    Hk, Wk = H * g.res / 1000, W * g.res / 1000

    # ultramafic belt trending NNE plus two lenses
    xc = 0.46 * Wk - 0.16 * (ykm - Hk / 2) + 1.2 * np.sin(ykm / 2.2)
    hw = 0.75 + 0.5 * _field(rng, (H, W), 40)
    um = 1 - np.clip((np.abs(xkm - xc) - hw + 0.15) / 0.5, 0, 1)
    for cx, cy, a, b, th in [(0.74 * Wk, 0.25 * Hk, 1.9, 0.65, 0.5), (0.22 * Wk, 0.8 * Hk, 1.3, 0.5, -0.3)]:
        ex = (xkm - cx) * np.cos(th) + (ykm - cy) * np.sin(th)
        ey = -(xkm - cx) * np.sin(th) + (ykm - cy) * np.cos(th)
        um = np.maximum(um, 1 - np.clip((np.hypot(ex / a, ey / b) - 0.8) / 0.4, 0, 1))

    # structures (km coordinates -> grid lon/lat later)
    faults_km = [[(0.1 * Wk, 0.05 * Hk), (0.9 * Wk, 0.9 * Hk)], [(0.6 * Wk, 0.0), (0.38 * Wk, Hk)],
                 [(0.0, 0.62 * Hk), (Wk, 0.4 * Hk)]]

    def seg_dist(ax, ay, bx, by):
        dx, dy = bx - ax, by - ay
        u = np.clip(((xkm - ax) * dx + (ykm - ay) * dy) / (dx * dx + dy * dy), 0, 1)
        return np.hypot(ax + u * dx - xkm, ay + u * dy - ykm)
    fd = np.min([seg_dist(*a, *b) for a, b in faults_km], axis=0)

    n1, n2, n3, n4, n5 = (_field(rng, (H, W), s) for s in (60, 25, 30, 20, 45))
    elev = 1330 + 160 * n1 + 60 * um
    # sentinel-2 reflectance: iron-stained soils over ultramafic -> higher red/blue
    blue = 0.06 + 0.02 * n2
    red = blue * (1.35 + 0.35 * um + 0.25 * n3)
    nir = 0.22 + 0.08 * n4
    swir1 = 0.28 + 0.05 * n2
    swir2 = swir1 / (1.15 + 0.2 * um + 0.1 * n5)
    s2 = np.stack([blue, red, nir, swir1, swir2]) + rng.normal(0, 0.003, (5, H, W))
    # ASTER SWIR DN: Mg-OH absorption near band 8 over serpentine
    base = 80 + 20 * n4
    b4, b5, b6, b7 = base * 1.3, base * 1.1, base * 1.05, base * 1.0
    b8 = base * (0.98 - 0.12 * um - 0.04 * n3)
    b9 = base * 0.95
    aster = np.stack([b4, b5, b6, b7, b8, b9]) * (1 + rng.normal(0, 0.01, (6, H, W)))
    # magnetics: partial coverage (east third missing)
    mag = 30 + 220 * um + 60 * n5
    mag[:, int(W * 0.68):] = np.nan

    tags = {"SAMPLE": "true", "source": "SYNTHETIC SAMPLE - not real data"}
    _write(RAW / "dem.tif", elev, g, ["elevation_m"], tags)
    _write(RAW / "s2.tif", s2, g, ["B02", "B04", "B08", "B11", "B12"], tags)
    _write(RAW / "aster_swir.tif", aster, g, ["B4", "B5", "B6", "B7", "B8", "B9"], tags)
    _write(INPUTS / "magnetics.tif", mag, g, ["tmi_nT"], tags)

    # digitised geology polygons (what the team traces from Survey sheets)
    litho = np.where(um > 0.5, 2, np.where(np.abs(xkm - xc) < 3.5 + 1.2 * n2, 1, 0)).astype("uint8")
    names = {0: ("Granite-gneiss", False), 1: ("Greenstone (mafic volcanics)", False), 2: ("Serpentinite / ultramafic", True)}
    feats = []
    for geom, v in features.shapes(litho, transform=g.transform):
        poly = shape(geom).simplify(45)
        if poly.area < 60 * 60 * 4:
            continue
        nm, ultra = names[int(v)]
        feats.append({"type": "Feature", "geometry": mapping(_to_lonlat(poly, g)),
                      "properties": {"unit": nm, "ultramafic": ultra, "source": "SAMPLE digitised sheet"}})
    (INPUTS / "geology.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))

    t = g.transform
    lines = []
    for a, b in faults_km:
        pts = [(t.c + x * 1000, t.f - y * 1000) for x, y in (a, b)]
        lines.append({"type": "Feature", "geometry": mapping(_to_lonlat(LineString(pts), g)),
                      "properties": {"kind": "shear zone", "source": "SAMPLE"}})
    (INPUTS / "structures.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": lines}))

    # hidden truth -> occurrences
    logit = -9.0 + 7.0 * um + 2.0 * np.exp(-fd / 0.4) * (0.4 + um) + 3.0 * (n3 - 0.5)
    p = 1 / (1 + np.exp(-logit))
    pts = []
    tries = 0
    while len(pts) < 52 and tries < 2_000_000:
        tries += 1
        r, c = rng.integers(0, H), rng.integers(0, W)
        if rng.random() < p[r, c] * 1.5 and all(np.hypot(r - a, c - b) > 15 for a, b in pts):
            pts.append((r, c))
    lon, lat = g.to_lonlat([a for a, _ in pts], [b for _, b in pts])
    with open(INPUTS / "occurrences.csv", "w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["id", "lon", "lat", "label", "source", "notes"])
        for k, (x, y) in enumerate(zip(lon, lat), 1):
            wr.writerow([f"S-{k:03d}", f"{x:.6f}", f"{y:.6f}", "chromite", "SAMPLE", "synthetic occurrence"])
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (RAW / "sources.json").write_text(json.dumps({
        k: {"layer": k, "source": "SYNTHETIC SAMPLE", "sample": True, "downloaded": now}
        for k in ("dem", "s2", "aster", "magnetics", "geology", "structures", "occurrences")}, indent=2))
    return {"grid": g.to_dict(), "occurrences": len(pts)}


def _to_lonlat(geom, g):
    from pyproj import Transformer
    import shapely
    tr = Transformer.from_crs(g.crs, "EPSG:4326", always_xy=True)
    return shapely.transform(geom, lambda a: np.column_stack(tr.transform(a[:, 0], a[:, 1])))
