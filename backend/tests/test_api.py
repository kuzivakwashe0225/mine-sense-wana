import io
import json
import uuid

from fastapi.testclient import TestClient

GEO = {"Authorization": "Bearer test-key"}


def client(built):
    from wana.api import app
    return TestClient(app)


def rec(c, lon, lat, cid=None, photo=None, headers=None):
    data = {"client_id": cid or str(uuid.uuid4()), "sample_no": "WANA-SHU-0001", "lon": lon, "lat": lat,
            "accuracy_m": 6, "checks": json.dumps({"black_grains": True, "heavy": True}), "notes": "test",
            "target_id": "SHU-T01", "created_at": "2026-10-16T08:00:00Z"}
    files = {"photo": photo} if photo else None
    return c.post("/api/records", data=data, files=files, headers=headers or {})


def test_miner_location_is_coarse(built):
    c = client(built)
    miner = c.get("/api/targets").json()
    geo = c.get("/api/targets", headers=GEO).json()
    assert all(t["precision_m"] == 1000 for t in miner)
    assert all("block" in t for t in miner)
    for a, b in zip(miner, geo):
        assert a["id"] == b["id"]
        assert (a["lon"], a["lat"]) != (b["lon"], b["lat"])
        assert abs(a["lon"] - b["lon"]) < 0.012 and abs(a["lat"] - b["lat"]) < 0.012


def test_sensitive_endpoints_need_key(built):
    c = client(built)
    assert c.get("/api/occurrences").status_code == 403
    assert c.get("/api/records").status_code == 403
    assert c.get("/api/files/run/0/rank.png").status_code == 403
    assert c.get("/api/files/run/0/rank_coarse.png").status_code == 200
    assert c.get("/api/occurrences", headers=GEO).status_code == 200
    ov = c.get("/api/overlays").json()
    assert "rank_coarse" in ov["rank"]["url"]


def test_card_languages(built):
    c = client(built)
    en = c.get("/api/card", params={"target": "SHU-T01"}).json()
    sn = c.get("/api/card", params={"target": "SHU-T01", "lang": "sn"}).json()
    assert en["why"] and en["check_first"] and en["disclaimer"]
    assert en["score"] == sn["score"] and en["disclaimer"] != sn["disclaimer"]
    assert en["sample_data"] is True
    cell = c.get("/api/card", params={"lon": 30.0, "lat": -19.67}).json()
    assert cell["location"]["precision_m"] == 1000


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
    assert c.post(f"/api/records/{r1['id']}/review", json={"status": "endorsed"}).status_code == 403
    assert c.post(f"/api/records/{r1['id']}/review", json={"status": "endorsed", "lab_cr2o3": 38.5}, headers=GEO).status_code == 200
    assert c.post(f"/api/records/{other['id']}/review", json={"status": "rejected", "lab_cr2o3": 1.2}, headers=GEO).status_code == 200
    out = c.post("/api/model/retrain", headers=GEO)
    assert out.status_code == 200, out.text
    body = out.json()
    assert body["version"] == 1
    assert body["metrics"]["n_absences"] == 1
    assert c.get("/api/meta").json()["version"] == 1
    assert c.post(f"/api/records/{r1['id']}/review", json={"status": "rejected"}, headers=GEO).status_code == 409
    vs = c.get("/api/model/versions").json()
    assert [v["version"] for v in vs] == [0, 1]
    assert c.post("/api/model/retrain", headers=GEO).status_code == 400
