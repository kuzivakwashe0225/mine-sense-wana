import io
import json
import uuid

from conftest import bearer
from fastapi.testclient import TestClient

GEO = bearer("miner", "geologist", email="geo@example.org")


def client(built):
    from wana.api import app
    return TestClient(app)


def rec(c, lon, lat, cid=None, photo=None, headers=None):
    data = {"client_id": cid or str(uuid.uuid4()), "sample_no": "WANA-SHU-0001", "lon": lon, "lat": lat,
            "accuracy_m": 6, "checks": json.dumps({"black_grains": True, "heavy": True}), "notes": "test",
            "target_id": "SHU-T01", "created_at": "2026-10-16T08:00:00Z"}
    files = {"photo": photo} if photo else None
    return c.post("/api/records", data=data, files=files, headers=headers if headers is not None else bearer())


def test_miner_location_is_coarse(built):
    c = client(built)
    miner = c.get("/api/targets").json()
    signed_in_miner = c.get("/api/targets", headers=bearer("miner")).json()
    geo = c.get("/api/targets", headers=GEO).json()
    assert miner == signed_in_miner, "a miner account gets the same coarse view as anonymous visitors"
    assert all(t["precision_m"] == 1000 for t in miner)
    assert all("block" in t for t in miner)
    for a, b in zip(miner, geo):
        assert a["id"] == b["id"]
        assert (a["lon"], a["lat"]) != (b["lon"], b["lat"])
        assert abs(a["lon"] - b["lon"]) < 0.012 and abs(a["lat"] - b["lat"]) < 0.012


def test_sensitive_endpoints_need_geologist(built):
    c = client(built)
    for h in ({}, bearer("miner")):
        assert c.get("/api/occurrences", headers=h).status_code in (401, 403)
        assert c.get("/api/records", headers=h).status_code in (401, 403)
        assert c.get("/api/files/run/0/rank.png", headers=h).status_code == 403
    assert c.get("/api/files/run/0/rank_coarse.png").status_code == 200
    assert c.get("/api/occurrences", headers=GEO).status_code == 200
    assert "rank_coarse" in c.get("/api/overlays").json()["rank"]["url"]
    assert "rank_coarse" not in c.get("/api/overlays", headers=GEO).json()["rank"]["url"]


def test_bad_tokens_are_rejected_not_downgraded(built):
    """An expired or forged token must give 401 (so the app re-authenticates), never a silent miner view."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    c = client(built)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cases = {"expired": bearer("geologist", exp_in=-60), "forged": bearer("geologist", key=other),
             "wrong audience": bearer("geologist", aud="account"), "wrong issuer": bearer("geologist", iss="https://evil/realms/wana"),
             "not bearer": {"Authorization": "Basic abc"}}
    for name, h in cases.items():
        r = c.get("/api/targets", headers=h)
        assert r.status_code == 401, name
        assert r.json()["error"]["kind"] == "user", name
    assert c.get("/api/targets", headers=bearer("geologist", exp_in=-60)).json()["error"]["code"] == "token_expired"


def test_card_languages(built):
    c = client(built)
    en = c.get("/api/card", params={"target": "SHU-T01"}).json()
    sn = c.get("/api/card", params={"target": "SHU-T01", "lang": "sn"}).json()
    assert en["why"] and en["check_first"] and en["disclaimer"]
    assert en["score"] == sn["score"] and en["disclaimer"] != sn["disclaimer"]
    assert en["sample_data"] is True
    cell = c.get("/api/card", params={"lon": 30.0, "lat": -19.67}).json()
    assert cell["location"]["precision_m"] == 1000


def test_etag_lets_pollers_skip_unchanged_data(built):
    c = client(built)
    r1 = c.get("/api/meta")
    tag = r1.headers["etag"]
    r2 = c.get("/api/meta", headers={"If-None-Match": tag})
    assert r2.status_code == 304 and r2.content == b""
    geo = c.get("/api/meta", headers={**GEO, "If-None-Match": tag})
    assert geo.status_code == 200, "different role, different body, different tag"
    assert "Authorization" in r1.headers["vary"]


def test_error_envelope_classifies_kinds(built):
    c = client(built)
    user = c.get("/api/card", params={"lon": 10, "lat": 10})
    assert user.status_code == 400 and user.json()["error"]["kind"] == "user"
    business = c.post("/api/model/retrain", headers=GEO)
    assert business.json()["error"] == {**business.json()["error"], "kind": "business", "code": "nothing_to_retrain"}
    valid = c.post("/api/records/1/review", json={"status": "maybe"}, headers=GEO)
    assert valid.status_code == 422 and valid.json()["error"]["code"] == "validation"
    assert user.headers["x-request-id"] and user.json()["error"]["request_id"] == user.headers["x-request-id"]


def test_records_need_sign_in(built):
    c = client(built)
    r = rec(c, 30.0, -19.67, headers={})
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"


def test_record_flow_and_retrain(built):
    c = client(built)
    t = c.get("/api/targets", headers=GEO).json()
    cid = str(uuid.uuid4())
    png = ("x.png", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 100), "image/png")
    r1 = rec(c, t[0]["lon"], t[0]["lat"], cid, photo=png).json()
    r2 = rec(c, t[0]["lon"], t[0]["lat"], cid).json()
    assert r1["id"] == r2["id"] and r2["duplicate"] is True
    bad = rec(c, t[1]["lon"], t[1]["lat"], photo=("x.jpg", io.BytesIO(b"not an image"), "image/jpeg"))
    assert bad.status_code == 415
    other = rec(c, t[2]["lon"], t[2]["lat"]).json()
    rows = c.get("/api/records", headers=GEO).json()
    mine = next(r for r in rows if r["id"] == r1["id"])
    assert mine["user_email"] == "user@example.org" and mine["photo"].endswith(".png")
    assert c.get(f"/api/photos/{mine['photo']}", headers=GEO).content.startswith(b"\x89PNG")
    assert c.post(f"/api/records/{r1['id']}/review", json={"status": "endorsed"}, headers=bearer("miner")).status_code == 403
    # idempotent review: the same key twice gives the same answer and does one update
    h = {**GEO, "Idempotency-Key": "k-1"}
    a = c.post(f"/api/records/{r1['id']}/review", json={"status": "endorsed", "lab_cr2o3": 38.5}, headers=h)
    b = c.post(f"/api/records/{r1['id']}/review", json={"status": "endorsed", "lab_cr2o3": 38.5}, headers=h)
    assert a.status_code == b.status_code == 200 and a.json() == b.json()
    assert c.post(f"/api/records/{other['id']}/review", json={"status": "rejected", "lab_cr2o3": 1.2}, headers=GEO).status_code == 200
    # streaming retrain: progress lines, then the result
    with c.stream("POST", "/api/model/retrain/stream", headers=GEO) as s:
        assert s.status_code == 200
        lines = [json.loads(x) for x in s.iter_lines() if x]
    stages = [x for x in lines if "stage" in x]
    assert len(stages) > 5 and stages[-1]["progress"] == 1.0
    assert [p["progress"] for p in stages] == sorted(p["progress"] for p in stages), "progress only moves forward"
    body = lines[-1]["done"]
    assert body["version"] == 1 and body["metrics"]["n_absences"] == 1
    assert c.get("/api/meta").json()["version"] == 1
    locked = c.post(f"/api/records/{r1['id']}/review", json={"status": "rejected"}, headers=GEO)
    assert locked.status_code == 409 and locked.json()["error"]["kind"] == "business"
    assert [v["version"] for v in c.get("/api/model/versions").json()] == [0, 1]
    assert c.post("/api/model/retrain", headers=GEO).status_code == 400


def test_retrain_lock_refuses_second_run(built):
    from wana import cache
    c = client(built)
    with cache.Lock("retrain"):
        rec_id = rec(c, 30.0, -19.67).json()["id"]
        c.post(f"/api/records/{rec_id}/review", json={"status": "rejected"}, headers=GEO)
        r = c.post("/api/model/retrain", headers=GEO)
        assert r.status_code == 409 and r.json()["error"]["code"] == "busy"


def test_client_error_reports_and_metrics(built):
    c = client(built)
    assert c.post("/api/client-errors", json={"kind": "platform", "message": "boom", "where": "Review"}).status_code == 204
    m = c.get("/metrics").text
    assert 'wana_client_errors_total{kind="platform"}' in m
    assert 'wana_errors_total{code="validation",kind="user"}' in m
    assert "wana_http_request_duration_seconds_bucket" in m


def test_config_and_me(built):
    c = client(built)
    cfg = c.get("/api/config").json()
    assert cfg["auth"]["enabled"] and cfg["session"]["warn_seconds"] == 60
    assert c.get("/api/me").json()["signed_in"] is False
    me = c.get("/api/me", headers=GEO).json()
    assert me["signed_in"] and me["view"] == "geologist" and "geologist" in me["roles"]


def test_my_records_are_only_mine(built):
    c = client(built)
    me, other = bearer("miner", sub="me-1"), bearer("miner", sub="other-1")
    rec(c, 30.0, -19.67, headers=me)
    rec(c, 30.0, -19.66, headers=other)
    mine = c.get("/api/me/records", headers=me).json()
    assert len(mine) == 1 and mine[0]["lat"] == -19.67 and mine[0]["status"] == "pending"
    assert c.get("/api/me/records").status_code == 401
