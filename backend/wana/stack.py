"""Build the evidence stack: every layer resampled onto one grid, with its source recorded."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio import features
from rasterio.warp import Resampling, reproject
from scipy.ndimage import distance_transform_edt, uniform_filter
from shapely.geometry import shape
import shapely

from .config import INPUTS, RAW, STACK, ensure_dirs, load_config
from .grid import Grid, make_grid
from .ingest import is_chromium

# Plain-language meaning of each evidence layer. Keys are the feature names used everywhere.
FEATURES = {
    "um_host":   {"label": "Ultramafic host rock", "source": "Digitised Geological Survey maps", "file": "inputs/geology.geojson"},
    "shear":     {"label": "Proximity to shears", "source": "Mapped structures + radar lineaments", "file": "inputs/structures.geojson"},
    "mgoh":      {"label": "Serpentine Mg-OH index", "source": "ASTER SWIR (B6+B9)/(B7+B8)", "file": "raw/aster_swir.tif"},
    "ferric":    {"label": "Iron oxide index", "source": "Sentinel-2 B04/B02", "file": "raw/s2.tif"},
    "swir_oh":   {"label": "OH-mineral index", "source": "Sentinel-2 B11/B12", "file": "raw/s2.tif"},
    "ridge":     {"label": "Ridge position", "source": "Copernicus DEM topographic position", "file": "raw/dem.tif"},
    "magnetics": {"label": "Magnetic intensity", "source": "Airborne magnetics (partial cover)", "file": "inputs/magnetics.tif"},
}


def _read_on_grid(path: Path, grid: Grid, bands=None) -> np.ndarray:
    with rasterio.open(path) as src:
        bands = bands or list(range(1, src.count + 1))
        out = np.full((len(bands), *grid.shape), np.nan, dtype="float32")
        for k, b in enumerate(bands):
            reproject(rasterio.band(src, b), out[k], src_nodata=src.nodata, dst_transform=grid.transform,
                      dst_crs=grid.crs, dst_nodata=np.nan, resampling=Resampling.bilinear)
    return out


def _vec_to_grid(geojson_path: Path, grid: Grid, prop_filter=None):
    fc = json.loads(geojson_path.read_text())
    tr = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)
    shapes = []
    for f in fc["features"]:
        if prop_filter and not prop_filter(f.get("properties", {})):
            continue
        shapes.append((shapely.transform(shape(f["geometry"]), lambda a: np.column_stack(tr.transform(a[:, 0], a[:, 1]))), 1))
    if not shapes:
        return np.zeros(grid.shape, dtype=bool)
    return features.rasterize(shapes, out_shape=grid.shape, transform=grid.transform, fill=0,
                              all_touched=True, dtype="uint8").astype(bool)


def _ratio(a, b):
    with np.errstate(divide="ignore", invalid="ignore"):
        r = a / b
    r[~np.isfinite(r)] = np.nan
    return r


def _is_sample(path: Path) -> bool:
    if path.suffix == ".tif":
        with rasterio.open(path) as s:
            return s.tags().get("SAMPLE") == "true"
    return "SAMPLE" in path.read_text()[:200000]


def build() -> dict:
    cfg = load_config()
    ensure_dirs()
    g = make_grid(cfg)
    layers, provenance = {}, {}

    def add(name, arr, path):
        layers[name] = arr.astype("float32")
        cov = float(np.isfinite(arr).mean())
        provenance[name] = {**FEATURES[name], "coverage": round(cov, 3), "sample": _is_sample(path)}

    geo = INPUTS / "geology.geojson"
    if geo.exists():
        inside = _vec_to_grid(geo, g, lambda p: bool(p.get("ultramafic")))
        d = distance_transform_edt(~inside) * g.res
        add("um_host", np.exp(-d / 150.0), geo)
    st = INPUTS / "structures.geojson"
    if st.exists():
        lines = _vec_to_grid(st, g)
        d = distance_transform_edt(~lines) * g.res
        add("shear", np.exp(-d / 350.0), st)
    a = RAW / "aster_swir.tif"
    if a.exists():
        b = _read_on_grid(a, g)
        add("mgoh", _ratio(b[2] + b[5], b[3] + b[4]), a)
    s = RAW / "s2.tif"
    if s.exists():
        b = _read_on_grid(s, g)
        add("ferric", _ratio(b[1], b[0]), s)
        add("swir_oh", _ratio(b[3], b[4]), s)
    dem = RAW / "dem.tif"
    elev = None
    if dem.exists():
        elev = _read_on_grid(dem, g)[0]
        filled = np.where(np.isfinite(elev), elev, np.nanmean(elev))
        tpi = filled - uniform_filter(filled, size=int(1500 / g.res) | 1)
        add("ridge", np.where(np.isfinite(elev), tpi, np.nan), dem)
    m = INPUTS / "magnetics.tif"
    if m.exists():
        add("magnetics", _read_on_grid(m, g)[0], m)

    if len(layers) < 2:
        raise SystemExit("Fewer than two evidence layers found. Run `python -m wana sample` or `python -m wana ingest` first.")

    slope = np.zeros(g.shape, dtype="float32")
    if elev is not None:
        gy, gx = np.gradient(np.where(np.isfinite(elev), elev, np.nanmean(elev)), g.res)
        slope = np.degrees(np.arctan(np.hypot(gx, gy))).astype("float32")

    names = list(layers)
    np.savez_compressed(STACK / "stack.npz", names=np.array(names), X=np.stack([layers[n] for n in names]),
                        slope=slope, elev=elev if elev is not None else np.zeros(g.shape, "float32"))
    occ = load_occurrences(g)
    meta = {"grid": g.to_dict(), "features": names, "provenance": provenance, "occurrences": len(occ),
            "any_sample": any(p["sample"] for p in provenance.values())}
    (STACK / "stack.json").write_text(json.dumps(meta, indent=2))
    return meta


def load_occurrences(g: Grid) -> list[dict]:
    """Known chromite occurrences: geologist/Survey labels plus USGS MRDS chromium sites."""
    rows = []
    p = INPUTS / "occurrences.csv"
    if p.exists():
        with open(p) as fh:
            for r in csv.DictReader(fh):
                if r.get("label", "chromite").lower() in ("chromite", "chrome", "chromium", "1", "yes"):
                    rows.append({"id": r["id"], "lon": float(r["lon"]), "lat": float(r["lat"]), "source": r.get("source", "")})
    p = RAW / "mrds_sites.csv"
    if p.exists():
        with open(p) as fh:
            for r in csv.DictReader(fh):
                if is_chromium(r["commodities"]):
                    rows.append({"id": f"MRDS-{r['id']}", "lon": float(r["lon"]), "lat": float(r["lat"]), "source": r["source"]})
    if not rows:
        return []
    rr, cc = g.from_lonlat([r["lon"] for r in rows], [r["lat"] for r in rows])
    out, seen = [], set()
    for r, a, b in zip(rows, rr, cc):
        if g.inside(a, b) and (int(a), int(b)) not in seen:
            seen.add((int(a), int(b)))
            out.append({**r, "row": int(a), "col": int(b)})
    return out


def load_stack():
    z = np.load(STACK / "stack.npz", allow_pickle=False)
    meta = json.loads((STACK / "stack.json").read_text())
    return z, meta
