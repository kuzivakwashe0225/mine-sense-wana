import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="wana-test-")
os.environ["WANA_ROOT"] = _tmp
os.environ["WANA_WEB_DIST"] = str(Path(_tmp) / "no-dist")
os.environ["WANA_LOG_JSON"] = "0"
# Keycloak is "configured" but never contacted: tests sign their own tokens with a throwaway key.
os.environ["KEYCLOAK_URL"] = "http://keycloak.test/auth"
os.environ["KEYCLOAK_PUBLIC_URL"] = "https://wana.test/auth"
for k in ("REDIS_URL", "MINIO_ENDPOINT", "WANA_ADMIN_EMAIL"):
    os.environ.pop(k, None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import jwt  # noqa: E402
import pytest  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_KID = "test-kid"


def _install_key():
    from wana.auth import jwks
    jwks.keys = {_KID: _KEY.public_key()}
    jwks.fetched = time.time() + 10 ** 9   # never refetch


def token(roles=("miner",), sub=None, exp_in=300, aud="wana-api", iss="https://wana.test/auth/realms/wana", key=_KEY,
          email="user@example.org"):
    _install_key()
    now = int(time.time())
    claims = {"sub": sub or str(uuid.uuid4()), "iat": now, "exp": now + exp_in, "aud": aud, "iss": iss,
              "email": email, "name": "Test User", "realm_access": {"roles": list(roles)}}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": _KID})


def bearer(*roles, **kw):
    return {"Authorization": f"Bearer {token(roles or ('miner',), **kw)}"}


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


@pytest.fixture(autouse=True)
def fresh_limits():
    """Each test starts with empty rate-limit counters (the in-memory stand-in for Redis)."""
    from wana import cache
    cache._client = None
    yield
