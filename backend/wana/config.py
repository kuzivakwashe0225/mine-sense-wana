"""Project configuration. Edit wana.json at the repo root to change the pilot area."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(os.environ.get("WANA_ROOT", Path(__file__).resolve().parents[2]))
DATA = Path(os.environ.get("WANA_DATA", ROOT / "data"))
RAW = DATA / "raw"          # downloaded or sample source files
INPUTS = DATA / "inputs"    # hand-digitised geology, structures, geologist labels
STACK = DATA / "stack"      # aligned evidence grid
RUNS = DATA / "runs"        # versioned model outputs
PHOTOS = DATA / "photos"    # field photos
DB_PATH = DATA / "wana.sqlite"


@dataclass
class Config:
    name: str = "Shurugwi pilot"
    # lon/lat bounding box: west, south, east, north
    bbox: tuple[float, float, float, float] = (29.93, -19.75, 30.13, -19.60)
    crs: str = "EPSG:32736"          # UTM 36S (Shurugwi sits on the 35/36 zone line; distortion is negligible at 20 km)
    resolution: float = 30.0         # metres, matches Copernicus DEM GLO-30 and ASTER SWIR
    s2_months: tuple[int, int] = (6, 9)   # dry season composite
    s2_years: tuple[int, int] = (2023, 2025)
    s2_max_cloud: int = 10
    holdout_rule: dict = field(default_factory=lambda: {"type": "lat_below", "value": -19.70})
    target_count: int = 12
    target_min_spacing_m: float = 900.0
    miner_grid_m: float = 1000.0     # precision of locations shown to miners
    n_models: int = 15
    n_background: int = 8000
    seed: int = 2026


def load_config() -> Config:
    p = ROOT / "wana.json"
    cfg = Config()
    if p.exists():
        raw = json.loads(p.read_text())
        for k, v in raw.items():
            if hasattr(cfg, k):
                setattr(cfg, k, tuple(v) if isinstance(getattr(cfg, k), tuple) else v)
    return cfg


def ensure_dirs() -> None:
    for d in (RAW, INPUTS, STACK, RUNS, PHOTOS):
        d.mkdir(parents=True, exist_ok=True)
