"""Sign-up and user management, against a fake Keycloak admin API."""
import pytest
from conftest import bearer
from fastapi.testclient import TestClient


class FakeKC:
    def __init__(self):
        self.users, self.emails, self.roles = {}, [], {}

    def find(self, email):
        return next((u for u in self.users.values() if u["email"] == email), None)

    def create(self, email, first, last, attrs=None):
        uid = f"u{len(self.users) + 1}"
        self.users[uid] = {"id": uid, "email": email, "emailVerified": False, "first": first, "attrs": attrs}
        return uid

    def send_actions(self, uid, actions):
        self.emails.append((self.users[uid]["email"], tuple(actions)))

    def set_role(self, uid, role, grant):
        r = self.roles.setdefault(uid, set())
        (r.add if grant else r.discard)(role)

    def get(self, uid):
        u = self.users[uid]
        return {"firstName": u["first"], "lastName": u.get("last", ""), "email": u["email"], "attributes": u["attrs"] or {}}

    def update_profile(self, uid, first, last, organisation):
        self.users[uid].update(first=first, last=last, attrs={"organisation": [organisation]})

    def required_actions(self, uid):
        return ["UPDATE_PASSWORD"]

    def list_users(self):
        return [{"id": u, "email": v["email"], "roles": sorted(self.roles.get(u, ()))} for u, v in self.users.items()]


@pytest.fixture
def kc(monkeypatch):
    from wana import accounts
    fake = FakeKC()
    monkeypatch.setattr(accounts, "kc", fake)
    return fake


def client():
    from wana.api import app
    return TestClient(app)


def signup(c, email, name="Rudo Moyo", accept=True, ip="10.0.0.1"):
    return c.post("/api/auth/signup", json={"email": email, "name": name, "accept": accept},
                  headers={"X-Forwarded-For": ip})


def test_signup_sends_set_password_link(kc):
    c = client()
    r = signup(c, "Rudo@Example.org")
    assert r.status_code == 202
    assert kc.emails == [("rudo@example.org", ("VERIFY_EMAIL", "UPDATE_PASSWORD"))]
    uid = kc.find("rudo@example.org")["id"]
    assert kc.roles[uid] == {"miner"}, "new accounts start as miners; a geologist role is granted by an admin"


def test_signup_does_not_reveal_existing_accounts(kc):
    c = client()
    first = signup(c, "tendai@example.org", ip="10.0.0.2")
    again = signup(c, "tendai@example.org", ip="10.0.0.2")
    assert first.status_code == again.status_code == 202 and first.json() == again.json()
    assert len(kc.users) == 1 and len(kc.emails) == 2


def test_signup_validation_and_limits(kc):
    c = client()
    assert signup(c, "not-an-email", ip="10.0.0.3").json()["error"]["code"] == "invalid_email"
    assert signup(c, "a@example.org", accept=False, ip="10.0.0.3").json()["error"]["code"] == "terms_required"
    codes = [signup(c, "same@example.org", ip=f"10.1.0.{k}").status_code for k in range(5)]
    assert codes[:3] == [202] * 3 and codes[3] == 429, "three emails per address per day"


def test_admin_role_rules(kc):
    c = client()
    signup(c, "geo@example.org", ip="10.0.0.9")
    uid = kc.find("geo@example.org")["id"]
    assert c.get("/api/admin/users", headers=bearer("miner", "geologist")).status_code == 403
    adm = bearer("miner", "admin", sub="admin-1")
    assert c.post(f"/api/admin/users/{uid}/roles", json={"role": "geologist", "grant": True}, headers=adm).status_code == 200
    assert "geologist" in kc.roles[uid]
    self_demote = c.post("/api/admin/users/admin-1/roles", json={"role": "admin", "grant": False}, headers=adm)
    assert self_demote.status_code == 409 and self_demote.json()["error"]["kind"] == "business"
    assert c.post(f"/api/admin/users/{uid}/roles", json={"role": "miner", "grant": False}, headers=adm).status_code == 409


def test_profile_read_and_update(kc):
    c = client()
    signup(c, "chipo@example.org", name="Chipo", ip="10.0.0.20")
    uid = kc.find("chipo@example.org")["id"]
    h = bearer("miner", sub=uid)
    assert c.get("/api/me/profile", headers=h).json()["name"] == "Chipo"
    r = c.put("/api/me/profile", json={"name": "Chipo  Ncube", "organisation": "Tongogara Co-op"}, headers=h)
    assert r.status_code == 200 and r.json()["name"] == "Chipo Ncube" and r.json()["organisation"] == "Tongogara Co-op"
    assert c.put("/api/me/profile", json={"name": "C"}, headers=h).status_code == 422
    assert c.get("/api/me/profile").status_code == 401
