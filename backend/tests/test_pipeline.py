import csv
import json
import shutil

import numpy as np


def test_stack_has_all_layers(built):
    meta, model = built
    assert set(meta["features"]) == {"um_host", "shear", "mgoh", "ferric", "swir_oh", "ridge", "magnetics"}
    assert meta["any_sample"] is True, "sample data must be flagged"
    assert 0.6 < meta["provenance"]["magnetics"]["coverage"] < 0.75, "partial magnetics cover should be recorded"


def test_model_outputs(built):
    _, model = built
    m = model["metrics"]
    assert model["version"] == 0
    assert m["n_test"] > 5 and m["n_train"] > 5
    assert len(model["targets"]) == 12
    ids = [t["id"] for t in model["targets"]]
    assert len(set(ids)) == 12
    # host rock should matter most on the sample data (it drives the hidden truth)
    coefs = dict(zip(model["features"], model["coef_mean"]))
    assert max(coefs, key=coefs.get) == "um_host"


def test_targets_respect_spacing(built):
    _, model = built
    pts = [(t["row"], t["col"]) for t in model["targets"]]
    min_cells = 900 / 30
    for i, a in enumerate(pts):
        for b in pts[i + 1:]:
            assert np.hypot(a[0] - b[0], a[1] - b[1]) >= min_cells - 1e-6
    # miners see 1 km blocks: two targets in one block would hide one of them
    blocks = [tuple(t["miner_block"][0]) for t in model["targets"]]
    assert len(set(blocks)) == len(blocks)


def test_random_labels_do_not_validate(built, tmp_path):
    """Skeptic check: with random 'occurrences' the hold-out AUC must collapse towards 0.5.
    If it did not, the validation would be leaking information."""
    from wana.config import INPUTS, load_config
    from wana.model import train
    cfg = load_config()
    w, s, e, n = cfg.bbox
    src = INPUTS / "occurrences.csv"
    backup = tmp_path / "occ.csv"
    shutil.copy(src, backup)
    rng = np.random.default_rng(1)
    try:
        with open(src, "w", newline="") as fh:
            wr = csv.writer(fh)
            wr.writerow(["id", "lon", "lat", "label", "source", "notes"])
            for k in range(60):
                wr.writerow([f"R{k}", rng.uniform(w + .005, e - .005), rng.uniform(s + .005, n - .005), "chromite", "RANDOM", ""])
        aucs = [train(note="random-label check")["metrics"]["auc_holdout"]]
        assert 0.25 < aucs[0] < 0.75, aucs
    finally:
        shutil.copy(backup, src)
        # remove the random-label run so later tests see the real baseline as latest
        from wana.model import latest_version, run_dir
        shutil.rmtree(run_dir(latest_version()))


def test_mrds_gml_parsing():
    """The USGS WFS only serves GML in lat,lon order, and commodity codes are upper case."""
    from wana.ingest import is_chromium, parse_mrds_gml
    gml = b"""<wfs:FeatureCollection xmlns:ms="http://mapserver.gis.umn.edu/mapserver"
      xmlns:wfs="http://www.opengis.net/wfs" xmlns:gml="http://www.opengis.net/gml">
      <gml:featureMember><ms:mrds fid="mrds.1"><ms:geometry><gml:Point srsName="EPSG:4326">
        <gml:coordinates>-19.719120,30.013560</gml:coordinates></gml:Point></ms:geometry>
        <ms:dep_id>10135433</ms:dep_id><ms:site_name>Selukwe Peak</ms:site_name>
        <ms:code_list> CR AL CA FE MG SIL</ms:code_list></ms:mrds></gml:featureMember>
    </wfs:FeatureCollection>"""
    rows = parse_mrds_gml(gml)
    assert rows[0]["lon"] == 30.01356 and rows[0]["lat"] == -19.71912
    assert is_chromium(rows[0]["commodities"])
    assert is_chromium("Chromium") and not is_chromium(" AU AG CU")
