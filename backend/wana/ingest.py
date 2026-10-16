"""Download the real open datasets for the pilot area.

Run on a machine with normal internet access:
    python -m wana ingest            # download everything
    python -m wana ingest --dry-run  # only search the catalogues and report what was found

Sources (all free, no account needed):
  * Copernicus DEM GLO-30          Microsoft Planetary Computer, collection "cop-dem-glo-30"
  * Sentinel-2 L2A                 Planetary Computer, collection "sentinel-2-l2a" (dry-season median)
  * ASTER L1T (SWIR, 2000-2008)    Planetary Computer, collection "aster-l1t"
  * USGS MRDS mineral occurrences  mrdata.usgs.gov (filtered to chromium)

Everything is written to data/raw/ with a provenance entry in data/raw/sources.json.
"""
from __future__ import annotations

import csv
import io
import json
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject

from .config import RAW, Config, ensure_dirs, load_config
from .grid import Grid, make_grid

PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
# The USGS MapServer WFS only serves GML (no GeoJSON). WFS 1.1 + EPSG:4326 means lat,lon axis order.
MRDS_WFS = ("https://mrdata.usgs.gov/services/wfs/mrds?service=WFS&version=1.1.0&request=GetFeature"
            "&typeName=mrds&outputFormat=text/xml;%20subtype=gml/2.1.2&srsName=EPSG:4326&bbox={s},{w},{n},{e},EPSG:4326")
_GML = "{http://www.opengis.net/gml}"
_MS = "{http://mapserver.gis.umn.edu/mapserver}"
MRDS_CSV_ZIP = "https://mrdata.usgs.gov/mrds/mrds-csv.zip"


def log(msg):
    print(f"[ingest {datetime.now():%H:%M:%S}] {msg}", flush=True)


def _catalog():
    try:
        import planetary_computer
        from pystac_client import Client
    except ImportError as e:  # pragma: no cover
        sys.exit(f"Missing package: {e}. Run: pip install -r requirements.txt")
    return Client.open(PC_STAC, modifier=planetary_computer.sign_inplace)


def _warp_into(href: str, bands: list[int], grid: Grid, resampling=Resampling.bilinear) -> np.ndarray:
    """Read the given 1-based bands of a (remote) raster and resample onto the grid. NaN where no data."""
    out = np.full((len(bands), *grid.shape), np.nan, dtype="float32")
    with rasterio.open(href) as src:
        for k, b in enumerate(bands):
            reproject(
                source=rasterio.band(src, b), destination=out[k],
                src_nodata=src.nodata, dst_transform=grid.transform, dst_crs=grid.crs,
                dst_nodata=np.nan, resampling=resampling,
            )
    return out


def _write(path, arr, grid: Grid, descriptions, tags):
    if arr.ndim == 2:
        arr = arr[None]
    with rasterio.open(path, "w", driver="GTiff", width=grid.width, height=grid.height, count=arr.shape[0],
                       dtype="float32", crs=grid.crs, transform=grid.transform, nodata=np.nan,
                       compress="deflate") as dst:
        dst.write(arr.astype("float32"))
        for i, d in enumerate(descriptions, 1):
            dst.set_band_description(i, d)
        dst.update_tags(**{k: str(v) for k, v in tags.items()})


def fetch_dem(cfg: Config, grid: Grid, dry=False):
    items = list(_catalog().search(collections=["cop-dem-glo-30"], bbox=cfg.bbox).items())
    log(f"DEM: {len(items)} tile(s): {[i.id for i in items]}")
    if dry or not items:
        return None
    acc = np.full(grid.shape, np.nan, dtype="float32")
    for it in items:
        a = _warp_into(it.assets["data"].href, [1], grid)[0]
        acc = np.where(np.isnan(acc), a, acc)
    _write(RAW / "dem.tif", acc, grid, ["elevation_m"], {"source": "Copernicus DEM GLO-30 via Planetary Computer",
                                                          "items": ",".join(i.id for i in items)})
    return {"layer": "dem", "source": "Copernicus DEM GLO-30", "items": [i.id for i in items]}


S2_BANDS = ["B02", "B04", "B08", "B11", "B12"]


def fetch_s2(cfg: Config, grid: Grid, dry=False, max_items=10):
    m0, m1 = cfg.s2_months
    items = []
    for y in range(cfg.s2_years[0], cfg.s2_years[1] + 1):
        dt = f"{y}-{m0:02d}-01/{y}-{m1:02d}-30"
        found = _catalog().search(collections=["sentinel-2-l2a"], bbox=cfg.bbox, datetime=dt,
                                  query={"eo:cloud_cover": {"lt": cfg.s2_max_cloud}}).items()
        items += list(found)
    items.sort(key=lambda i: i.properties.get("eo:cloud_cover", 100))
    items = items[:max_items]
    log(f"Sentinel-2: using {len(items)} low-cloud dry-season scene(s)")
    if dry or not items:
        return None
    stack = []
    for it in items:
        log(f"  reading {it.id} (cloud {it.properties.get('eo:cloud_cover')}%)")
        bands = np.concatenate([_warp_into(it.assets[b].href, [1], grid) for b in S2_BANDS])
        scl = _warp_into(it.assets["SCL"].href, [1], grid, Resampling.nearest)[0]
        bad = np.isin(scl, [0, 1, 3, 8, 9, 10]) | np.isnan(scl)
        bands[:, bad] = np.nan
        # L2A processing baseline >= 04.00 adds a +1000 offset to reflectance DNs
        if float(it.properties.get("s2:processing_baseline", "0")) >= 4.0:
            bands = bands - 1000.0
        stack.append(bands / 10000.0)
    med = np.nanmedian(np.stack(stack), axis=0)
    _write(RAW / "s2.tif", med, grid, S2_BANDS, {"source": "Sentinel-2 L2A median, SCL-masked",
                                                  "items": ",".join(i.id for i in items), "units": "reflectance"})
    return {"layer": "s2", "source": "Sentinel-2 L2A", "items": [i.id for i in items]}


def fetch_aster(cfg: Config, grid: Grid, dry=False, max_items=6):
    # ASTER SWIR detector failed in April 2008; only earlier scenes carry usable SWIR bands.
    found = list(_catalog().search(collections=["aster-l1t"], bbox=cfg.bbox, datetime="2000-03-01/2008-03-31").items())
    found = [i for i in found if "SWIR" in i.assets]
    found.sort(key=lambda i: i.properties.get("eo:cloud_cover", 100))
    items = found[:max_items]
    log(f"ASTER L1T with SWIR: {len(found)} found, using {len(items)}")
    if items:
        log(f"  asset keys on first item: {list(items[0].assets)}")
    if dry or not items:
        return None
    stack = []
    for it in items:
        with rasterio.open(it.assets["SWIR"].href) as src:
            n = src.count
        if n != 6:
            log(f"  skip {it.id}: SWIR asset has {n} bands, expected 6 (bands 4-9)")
            continue
        a = _warp_into(it.assets["SWIR"].href, [1, 2, 3, 4, 5, 6], grid)
        a[a <= 0] = np.nan
        stack.append(a)
    if not stack:
        log("ASTER: no usable SWIR scenes")
        return None
    med = np.nanmedian(np.stack(stack), axis=0)
    _write(RAW / "aster_swir.tif", med, grid, ["B4", "B5", "B6", "B7", "B8", "B9"],
           {"source": "ASTER L1T SWIR (DN) median", "items": ",".join(i.id for i in items)})
    return {"layer": "aster_swir", "source": "ASTER L1T", "items": [i.id for i in items]}


def _get(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "minesense-wana/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def is_chromium(commodities: str) -> bool:
    """MRDS lists commodity codes in upper case (" CR AL FE") or names ("Chromium")."""
    c = commodities.upper()
    return "CR" in c.replace(",", " ").split() or "CHROM" in c


def parse_mrds_gml(xml: bytes) -> list[dict]:
    root = ET.fromstring(xml)
    if root.tag.endswith("ExceptionReport"):
        raise RuntimeError(" ".join(t.strip() for t in root.itertext() if t.strip())[:200])
    rows = []
    for f in root.iter(f"{_MS}mrds"):
        pt = f.find(f"{_MS}geometry/{_GML}Point/{_GML}coordinates")
        if pt is None or not pt.text:
            continue
        lat, lon = (float(v) for v in pt.text.strip().split(",")[:2])
        val = lambda k: (f.findtext(f"{_MS}{k}") or "").strip()  # noqa: E731
        rows.append({"id": val("dep_id"), "name": val("site_name"), "lon": lon, "lat": lat,
                     "commodities": val("code_list"), "source": "USGS MRDS (WFS)"})
    return rows


def fetch_mrds(cfg: Config, dry=False):
    w, s, e, n = cfg.bbox
    pad = 0.1
    rows = []
    try:
        rows = parse_mrds_gml(_get(MRDS_WFS.format(w=w - pad, s=s - pad, e=e + pad, n=n + pad)))
        log(f"MRDS WFS: {len(rows)} sites in padded bbox")
    except Exception as ex:  # noqa: BLE001
        log(f"MRDS WFS failed ({ex}); falling back to full CSV download (large)")
        if dry:
            return None
        z = zipfile.ZipFile(io.BytesIO(_get(MRDS_CSV_ZIP, timeout=600)))
        name = next(x for x in z.namelist() if x.lower().endswith(".csv"))
        reader = csv.DictReader(io.TextIOWrapper(z.open(name), encoding="latin-1"))
        need = {"latitude", "longitude"}
        if not need.issubset(reader.fieldnames or []):
            raise RuntimeError(f"MRDS CSV columns changed: {reader.fieldnames}")
        for p in reader:
            try:
                lon, lat = float(p["longitude"]), float(p["latitude"])
            except ValueError:
                continue
            if w - pad <= lon <= e + pad and s - pad <= lat <= n + pad:
                commod = " ".join(v for k, v in p.items() if k.startswith("commod") and v)
                rows.append({"id": p.get("dep_id"), "name": p.get("site_name"), "lon": lon, "lat": lat,
                             "commodities": commod, "source": "USGS MRDS (CSV)"})
    chrome = [r for r in rows if is_chromium(r["commodities"])]
    log(f"MRDS: {len(chrome)} chromium site(s) of {len(rows)}")
    if dry:
        return None
    with open(RAW / "mrds_sites.csv", "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=["id", "name", "lon", "lat", "commodities", "source"])
        wr.writeheader()
        wr.writerows(rows)
    return {"layer": "mrds_sites", "source": "USGS Mineral Resources Data System", "count": len(rows),
            "chromium": len(chrome)}


def run(dry=False, only=None):
    cfg = load_config()
    ensure_dirs()
    grid = make_grid(cfg)
    log(f"Pilot '{cfg.name}' bbox={cfg.bbox} grid={grid.width}x{grid.height} @ {grid.res} m in {grid.crs}")
    steps = {"dem": lambda: fetch_dem(cfg, grid, dry), "s2": lambda: fetch_s2(cfg, grid, dry),
             "aster": lambda: fetch_aster(cfg, grid, dry), "mrds": lambda: fetch_mrds(cfg, dry)}
    src_path = RAW / "sources.json"
    sources = json.loads(src_path.read_text()) if src_path.exists() else {}
    for k, fn in steps.items():
        if only and k not in only:
            continue
        t = time.time()
        try:
            res = fn()
        except Exception as ex:  # noqa: BLE001
            log(f"{k}: FAILED: {ex}")
            continue
        if res:
            res["downloaded"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            res["sample"] = False
            sources[k] = res
            log(f"{k}: done in {time.time() - t:.0f}s")
    if not dry:
        src_path.write_text(json.dumps(sources, indent=2))
