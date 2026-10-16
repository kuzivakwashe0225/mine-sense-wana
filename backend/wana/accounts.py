"""Accounts through the Keycloak admin API, using the `wana-backend` service account.

Sign-up asks only for a name and an email. Keycloak then emails a one-time link; following it verifies the
address and lets the person choose their own password. We never see or store passwords.
"""
from __future__ import annotations

import logging
import re
import threading
import time

import httpx

from .obs import DEPENDENCY_UP, EVENTS, BusinessError, PlatformError, UserError
from .settings import settings

log = logging.getLogger("wana.accounts")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[A-Za-z]{2,}$")
ROLES = ("miner", "geologist", "admin")


class Keycloak:
    def __init__(self):
        self._token, self._exp = "", 0.0
        self._lock = threading.Lock()

    def _admin_token(self):
        with self._lock:
            if time.time() < self._exp - 30:
                return self._token
            r = self._http("POST", f"{settings.kc_url}/realms/{settings.kc_realm}/protocol/openid-connect/token",
                           data={"grant_type": "client_credentials", "client_id": settings.kc_admin_client,
                                 "client_secret": settings.kc_admin_secret}, auth=False)
            j = r.json()
            self._token, self._exp = j["access_token"], time.time() + j.get("expires_in", 60)
            return self._token

    def _http(self, method, url, auth=True, ok=(200, 201, 204), **kw):
        headers = kw.pop("headers", {})
        if auth:
            headers["Authorization"] = f"Bearer {self._admin_token()}"
        try:
            r = httpx.request(method, url, headers=headers, timeout=10, **kw)
        except httpx.HTTPError as e:
            DEPENDENCY_UP.labels("keycloak").set(0)
            raise PlatformError("The account service is not answering. Please try again shortly.", "keycloak_down") from e
        DEPENDENCY_UP.labels("keycloak").set(1)
        if r.status_code not in ok:
            log.error("keycloak %s %s -> %s %s", method, url.split("/admin/")[-1], r.status_code, r.text[:300])
            raise PlatformError("The account service refused the request.", "keycloak_error")
        return r

    @property
    def base(self):
        return f"{settings.kc_url}/admin/realms/{settings.kc_realm}"

    # ----- users -----
    def find(self, email: str):
        r = self._http("GET", f"{self.base}/users", params={"email": email, "exact": "true"})
        return next((u for u in r.json() if (u.get("email") or "").lower() == email), None)

    def create(self, email: str, first: str, last: str, attrs: dict | None = None) -> str:
        r = self._http("POST", f"{self.base}/users", ok=(201, 409), json={
            "username": email, "email": email, "firstName": first, "lastName": last, "enabled": True,
            "emailVerified": False, "attributes": attrs or {}})
        if r.status_code == 409:
            return self.find(email)["id"]
        return r.headers["Location"].rstrip("/").split("/")[-1]

    def send_actions(self, uid: str, actions: list[str]):
        """Email a one-time link: verify the address and/or set a password, then return to the app."""
        self._http("PUT", f"{self.base}/users/{uid}/execute-actions-email", json=actions, params={
            "client_id": settings.kc_web_client, "redirect_uri": f"{settings.public_url}/#welcome",
            "lifespan": settings.invite_lifespan_seconds})

    def list_users(self, first=0, maxn=200):
        users = self._http("GET", f"{self.base}/users", params={"first": first, "max": maxn, "briefRepresentation": "false"}).json()
        out = []
        for u in users:
            roles = {r["name"] for r in self._http("GET", f"{self.base}/users/{u['id']}/role-mappings/realm").json()}
            out.append({"id": u["id"], "email": u.get("email", ""), "name": f"{u.get('firstName', '')} {u.get('lastName', '')}".strip(),
                        "organisation": (u.get("attributes", {}).get("organisation") or [""])[0],
                        "email_verified": u.get("emailVerified", False), "enabled": u.get("enabled", True),
                        "created": u.get("createdTimestamp"), "roles": sorted(roles & set(ROLES)),
                        "needs_password": bool(u.get("requiredActions"))})
        return out

    def get(self, uid: str):
        return self._http("GET", f"{self.base}/users/{uid}").json()

    def update_profile(self, uid: str, first: str, last: str, organisation: str):
        u = self.get(uid)
        attrs = u.get("attributes") or {}
        attrs["organisation"] = [organisation] if organisation else []
        # the full representation goes back, so Keycloak does not clear fields we did not send
        self._http("PUT", f"{self.base}/users/{uid}", json={**u, "firstName": first, "lastName": last, "attributes": attrs})

    def set_role(self, uid: str, role: str, grant: bool):
        rep = self._http("GET", f"{self.base}/roles/{role}").json()
        self._http("POST" if grant else "DELETE", f"{self.base}/users/{uid}/role-mappings/realm", json=[rep])

    def required_actions(self, uid: str):
        return self._http("GET", f"{self.base}/users/{uid}").json().get("requiredActions", [])

    def ping(self) -> bool:
        try:
            httpx.get(f"{settings.kc_url}/realms/{settings.kc_realm}", timeout=3).raise_for_status()
            DEPENDENCY_UP.labels("keycloak").set(1)
            return True
        except httpx.HTTPError:
            DEPENDENCY_UP.labels("keycloak").set(0)
            return False


kc = Keycloak()


def _split_name(name: str):
    parts = name.strip().split()
    return (parts[0], " ".join(parts[1:])) if parts else ("", "")


def signup(email: str, name: str, organisation: str = "") -> str:
    """Returns 'invited' or 'reset'. Callers show the same message either way, so nobody can use sign-up to
    find out which addresses already have accounts."""
    email = email.strip().lower()
    name = " ".join(name.split())
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise UserError("Please enter a valid email address.", "invalid_email", 422)
    if not 2 <= len(name) <= 80:
        raise UserError("Please enter your name (2 to 80 characters).", "invalid_name", 422)
    existing = kc.find(email)
    if existing:
        # already registered: send a fresh set-password link instead of creating anything
        kc.send_actions(existing["id"], ["UPDATE_PASSWORD"] if existing.get("emailVerified") else ["VERIFY_EMAIL", "UPDATE_PASSWORD"])
        EVENTS.labels("signup", "existing").inc()
        return "reset"
    first, last = _split_name(name)
    uid = kc.create(email, first, last, {"organisation": [organisation[:120]]} if organisation else None)
    kc.set_role(uid, "miner", True)
    kc.send_actions(uid, ["VERIFY_EMAIL", "UPDATE_PASSWORD"])
    EVENTS.labels("signup", "created").inc()
    return "invited"


def set_role(actor_sub: str, uid: str, role: str, grant: bool):
    if role not in ROLES:
        raise UserError(f"Unknown role '{role}'.", "invalid_role", 422)
    if role == "miner" and not grant:
        raise BusinessError("Every account keeps the miner role.", "role_required")
    if uid == actor_sub and role == "admin" and not grant:
        raise BusinessError("You cannot remove your own administrator role. Ask another administrator.", "self_demote")
    kc.set_role(uid, role, grant)
    EVENTS.labels("role_change", f"{'grant' if grant else 'revoke'}_{role}").inc()


def resend_invite(uid: str):
    actions = kc.required_actions(uid) or ["UPDATE_PASSWORD"]
    kc.send_actions(uid, actions)


def bootstrap_admin(stop: threading.Event, attempts=60):
    """Make sure WANA_ADMIN_EMAIL has an account with admin + geologist roles. Keycloak may still be starting,
    so retry for a few minutes. A brand-new admin gets the same set-password email as everyone else."""
    if not (settings.admin_email and settings.auth_enabled and settings.kc_admin_secret):
        return
    for _ in range(attempts):
        if stop.is_set():
            return
        try:
            u = kc.find(settings.admin_email)
            if u:
                uid = u["id"]
            else:
                uid = kc.create(settings.admin_email, "Wana", "Administrator")
                kc.send_actions(uid, ["VERIFY_EMAIL", "UPDATE_PASSWORD"])
                log.info("created administrator account and emailed the set-password link")
            for role in ROLES:
                kc.set_role(uid, role, True)
            return
        except Exception as e:  # noqa: BLE001
            log.info("admin bootstrap waiting for Keycloak: %s", e)
            stop.wait(5)


def profile(uid: str) -> dict:
    u = kc.get(uid)
    return {"name": f"{u.get('firstName', '')} {u.get('lastName', '')}".strip(), "email": u.get("email", ""),
            "organisation": ((u.get("attributes") or {}).get("organisation") or [""])[0],
            "email_verified": u.get("emailVerified", False), "created": u.get("createdTimestamp")}


def update_profile(uid: str, name: str, organisation: str):
    name = " ".join(name.split())
    if not 2 <= len(name) <= 80:
        raise UserError("Please enter your name (2 to 80 characters).", "invalid_name", 422)
    first, last = _split_name(name)
    kc.update_profile(uid, first, last, " ".join(organisation.split())[:120])
    EVENTS.labels("profile", "updated").inc()
