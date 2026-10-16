"""Render grid arrays to transparent PNG overlays in lon/lat for MapLibre image sources."""
from __future__ import annotations

import numpy as np
from PIL import Image
from rasterio.warp import Resampling, calculate_default_transform, reproject

from .grid import Grid

RANK_RAMP = [(0.0, (247, 215, 116)), (0.35, (242, 176, 75)), (0.6, (224, 112, 47)), (0.82, (180, 35, 42)), (1.0, (74, 13, 31))]
EVID_RAMP = [(0.0, (240, 244, 236)), (0.33, (150, 190, 170)), (0.66, (46, 106, 84)), (1.0, (20, 58, 46))]


def _ramp(v, stops):
    v = np.clip(v, 0, 1)
    out = np.zeros(v.shape + (3,), dtype="float32")
    for (a, ca), (b, cb) in zip(stops[:-1], stops[1:]):
        m = (v >= a) & (v <= b)
        q = ((v - a) / (b - a))[m][:, None]
        out[m] = np.array(ca) + (np.array(cb) - np.array(ca)) * q
    return out


def to_lonlat(arr: np.ndarray, grid: Grid, nearest=False):
    left, bottom, right, top = grid.bounds
    tr, w, h = calculate_default_transform(grid.crs, "EPSG:4326", grid.width, grid.height, left, bottom, right, top)
    dst = np.full((h, w), np.nan, dtype="float32")
    reproject(arr.astype("float32"), dst, src_transform=grid.transform, src_crs=grid.crs, src_nodata=np.nan,
              dst_transform=tr, dst_crs="EPSG:4326", dst_nodata=np.nan,
              resampling=Resampling.nearest if nearest else Resampling.bilinear)
    west, north = tr.c, tr.f
    east, south = west + w * tr.a, north + h * tr.e
    # MapLibre image source corners: top-left, top-right, bottom-right, bottom-left
    coords = [[west, north], [east, north], [east, south], [west, south]]
    return dst, coords


def png_rank(score_pct: np.ndarray, grid: Grid, path, floor=70.0):
    a, coords = to_lonlat(score_pct, grid)
    v = (a - floor) / (100 - floor)
    rgb = _ramp(np.nan_to_num(v), RANK_RAMP)
    alpha = np.where(np.isfinite(a) & (a >= floor), np.clip(0.3 + v * 0.65, 0, 0.92) * 255, 0)
    Image.fromarray(np.dstack([rgb, alpha]).astype("uint8"), "RGBA").save(path, optimize=True)
    return coords


def png_evidence(arr: np.ndarray, grid: Grid, path):
    a, coords = to_lonlat(arr, grid)
    lo, hi = np.nanpercentile(a, 2), np.nanpercentile(a, 98)
    v = (a - lo) / (hi - lo + 1e-9)
    rgb = _ramp(np.nan_to_num(v), EVID_RAMP)
    alpha = np.where(np.isfinite(a), 205, 70)
    rgb[~np.isfinite(a)] = 120
    Image.fromarray(np.dstack([rgb, alpha]).astype("uint8"), "RGBA").save(path, optimize=True)
    return coords


def png_hatch(mask: np.ndarray, grid: Grid, path, scale=3):
    a, coords = to_lonlat(mask.astype("float32"), grid, nearest=True)
    a = np.nan_to_num(a) > 0.5
    big = np.kron(a, np.ones((scale, scale), dtype=bool))
    yy, xx = np.mgrid[0:big.shape[0], 0:big.shape[1]]
    on = big & ((xx + yy) % (scale * 2) == 0)
    img = np.zeros(big.shape + (4,), dtype="uint8")
    img[on] = (106, 79, 160, 230)
    Image.fromarray(img, "RGBA").save(path, optimize=True)
    return coords
