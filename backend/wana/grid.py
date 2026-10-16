"""The common analysis grid every evidence layer is resampled onto."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from pyproj import Transformer
from rasterio.transform import from_origin, rowcol, xy

from .config import Config


@dataclass
class Grid:
    crs: str
    transform: object
    width: int
    height: int
    res: float

    @property
    def shape(self):
        return (self.height, self.width)

    @property
    def bounds(self):
        t = self.transform
        return (t.c, t.f - self.height * self.res, t.c + self.width * self.res, t.f)

    def to_lonlat(self, rows, cols):
        xs, ys = xy(self.transform, rows, cols)
        tr = Transformer.from_crs(self.crs, "EPSG:4326", always_xy=True)
        return tr.transform(np.asarray(xs), np.asarray(ys))

    def from_lonlat(self, lon, lat):
        tr = Transformer.from_crs("EPSG:4326", self.crs, always_xy=True)
        x, y = tr.transform(np.asarray(lon, dtype=float), np.asarray(lat, dtype=float))
        r, c = rowcol(self.transform, x, y)
        return np.asarray(r), np.asarray(c)

    def inside(self, r, c):
        r, c = np.asarray(r), np.asarray(c)
        return (r >= 0) & (c >= 0) & (r < self.height) & (c < self.width)

    def to_dict(self):
        return {"crs": self.crs, "transform": list(self.transform)[:6], "width": self.width,
                "height": self.height, "res": self.res}


def make_grid(cfg: Config) -> Grid:
    w, s, e, n = cfg.bbox
    tr = Transformer.from_crs("EPSG:4326", cfg.crs, always_xy=True)
    xs, ys = tr.transform([w, e, w, e], [s, s, n, n])
    r = cfg.resolution
    x0 = math.floor(min(xs) / r) * r
    y1 = math.ceil(max(ys) / r) * r
    x1 = math.ceil(max(xs) / r) * r
    y0 = math.floor(min(ys) / r) * r
    width, height = int((x1 - x0) / r), int((y1 - y0) / r)
    return Grid(cfg.crs, from_origin(x0, y1, r, r), width, height, r)
