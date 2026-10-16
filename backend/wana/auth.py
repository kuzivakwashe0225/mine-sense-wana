"""Who is calling: Keycloak access tokens (OIDC, RS256), checked on every request.

* No token          -> anonymous miner view (free basic access, coarse locations only)
* Valid token       -> signed-in user; roles come from the realm roles in the token
* Invalid / expired -> 401, so the browser knows to refresh or sign in again (never silently downgraded)

Roles: `miner` (every account), `geologist` (exact locations, review, retrain), `admin` (manage users).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx
import jwt
from fastapi import Depends, Header

from .obs import DEPENDENCY_UP, EVENTS, PlatformError, UserError, user_id
from .settings import settings

log = logging.getLogger("wana.auth")


@dataclass
class Principal:
    sub: str = ""
    email: str = ""
    name: str = ""
    roles: set[str] = field(default_factory=set)

    @property
    def signed_in(self) -> bool:
        return bool(self.sub)

    @property
    def is_geologist(self) -> bool:
        return bool(self.roles & {"geologist", "admin"})

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles

    @property
    def view(self) -> str:
        """Location precision the server will serve."""
        return "geologist" if self.is_geologist else "miner"


ANON = Principal()


class _Jwks:
    """Keycloak signing keys, cached; refetched (at most every 30 s) when a token names an unknown key."""

    def __init__(self):
        self.keys: dict[str, object] = {}
        self.fetched = 0.0
        self.lock = threading.Lock()

    def key(self, kid: str):
        if kid not in self.keys and time.time() - self.fetched > 30:
            with self.lock:
                self._fetch()
        k = self.keys.get(kid)
        if k is None:
            raise UserError("Sign-in token is not recognised. Please sign in again.", "token_unknown_key", 401)
        return k

    def _fetch(self):
        url = f"{settings.kc_url}/realms/{settings.kc_realm}/protocol/openid-connect/certs"
        self.fetched = time.time()
        try:
            r = httpx.get(url, timeout=5)
            r.raise_for_status()
            DEPENDENCY_UP.labels("keycloak").set(1)
        except httpx.HTTPError as e:
            DEPENDENCY_UP.labels("keycloak").set(0)
            raise PlatformError("The sign-in service is not answering. Please try again shortly.", "keycloak_down") from e
        self.keys = {k["kid"]: jwt.PyJWK(k).key for k in r.json()["keys"] if k.get("use", "sig") == "sig"}


jwks = _Jwks()


def verify(token: str) -> Principal:
    try:
        kid = jwt.get_unverified_header(token).get("kid", "")
        claims = jwt.decode(token, jwks.key(kid), algorithms=["RS256"], audience=settings.kc_audience,
                            issuer=settings.issuer, options={"require": ["exp", "iat", "sub"]}, leeway=10)
    except jwt.ExpiredSignatureError:
        EVENTS.labels("auth", "expired").inc()
        raise UserError("Your session has expired. Please sign in again.", "token_expired", 401,
                        headers={"WWW-Authenticate": 'Bearer error="invalid_token"'})
    except jwt.InvalidTokenError as e:
        EVENTS.labels("auth", "invalid").inc()
        log.info("rejected token: %s", e)
        raise UserError("Sign-in token is not valid. Please sign in again.", "token_invalid", 401,
                        headers={"WWW-Authenticate": 'Bearer error="invalid_token"'})
    roles = set(claims.get("realm_access", {}).get("roles", []))
    return Principal(sub=claims["sub"], email=claims.get("email", ""), roles=roles,
                     name=claims.get("name") or claims.get("preferred_username", ""))


# Laptop mode only (no Keycloak configured): WANA_DEV_AUTH=geologist makes every request a local geologist, so
# run_sample.bat can exercise records and review. Ignored whenever Keycloak is configured, so it cannot leak into production.
DEV = Principal(sub="local-dev", email="dev@localhost", name="Local developer", roles={"miner", "geologist"})     if os.environ.get("WANA_DEV_AUTH") == "geologist" and not settings.auth_enabled else None
if DEV:
    log.warning("WANA_DEV_AUTH=geologist: no sign-in, every request is a local geologist. Never use on a server.")


def current(authorization: Optional[str] = Header(None)) -> Principal:
    if DEV:
        return DEV
    if not authorization:
        return ANON
    if not authorization.startswith("Bearer ") or not settings.auth_enabled:
        raise UserError("Sign-in token is not valid. Please sign in again.", "token_invalid", 401)
    p = verify(authorization[7:])
    user_id.set(p.sub)
    return p


def signed_in(p: Principal = Depends(current)) -> Principal:
    if not p.signed_in:
        raise UserError("Please sign in first.", "unauthenticated", 401)
    return p


def geologist(p: Principal = Depends(signed_in)) -> Principal:
    if not p.is_geologist:
        raise UserError("This needs a geologist account.", "forbidden", 403)
    return p


def admin(p: Principal = Depends(signed_in)) -> Principal:
    if not p.is_admin:
        raise UserError("This needs an administrator account.", "forbidden", 403)
    return p
