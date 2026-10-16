import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="wana-test-")
os.environ["WANA_ROOT"] = _tmp
os.environ["WANA_GEOLOGIST_KEY"] = "test-key"
os.environ["WANA_WEB_DIST"] = str(Path(_tmp) / "no-dist")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def built():
    from wana.db import retrain_from_db
    from wana.model import render_evidence
    from wana.sample import generate
    from wana.stack import build
    generate()
    meta = build()
    render_evidence()
    model = retrain_from_db(note="test baseline")
    return meta, model
