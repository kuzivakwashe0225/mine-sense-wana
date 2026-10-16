"""Runtime settings for the API, read once from the environment.

Everything that differs between a laptop, the test suite and the server lives here. Services that are not
configured fall back to in-process equivalents (memory instead of Redis, local disk instead of MinIO), so
`python -m wana serve` still runs on a laptop with no containers.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    public_url: str = os.environ.get("WANA_PUBLIC_URL", "http://localhost:8000").rstrip("/")
    cors: list[str] = field(default_factory=lambda: [o for o in os.environ.get(
        "WANA_CORS", "http://localhost:5173").split(",") if o])

    # Keycloak. `kc_url` is how the API reaches Keycloak (inside the container network); tokens carry the
    # public issuer `kc_issuer_base`, which is what browsers use.
    kc_url: str = os.environ.get("KEYCLOAK_URL", "").rstrip("/")
    kc_issuer_base: str = os.environ.get("KEYCLOAK_PUBLIC_URL", "").rstrip("/")
    kc_realm: str = os.environ.get("KEYCLOAK_REALM", "wana")
    kc_web_client: str = os.environ.get("KEYCLOAK_WEB_CLIENT", "wana-web")
    kc_audience: str = os.environ.get("KEYCLOAK_AUDIENCE", "wana-api")
    kc_admin_client: str = os.environ.get("KEYCLOAK_ADMIN_CLIENT", "wana-backend")
    kc_admin_secret: str = os.environ.get("KEYCLOAK_ADMIN_SECRET", "")
    admin_email: str = os.environ.get("WANA_ADMIN_EMAIL", "").strip().lower()

    # Session policy, served to the browser by /api/config. Keycloak's SSO idle timeout (realm setting) is the
    # server-side backstop: a client that stops refreshing is signed out there even if this code is bypassed.
    idle_seconds: int = _int("WANA_IDLE_SECONDS", 15 * 60)
    warn_seconds: int = _int("WANA_WARN_SECONDS", 60)
    reading_seconds: int = _int("WANA_READING_SECONDS", 30 * 60)
    invite_lifespan_seconds: int = _int("WANA_INVITE_SECONDS", 24 * 3600)

    redis_url: str = os.environ.get("REDIS_URL", "")
    minio_endpoint: str = os.environ.get("MINIO_ENDPOINT", "")
    minio_access_key: str = os.environ.get("MINIO_ACCESS_KEY", "")
    minio_secret_key: str = os.environ.get("MINIO_SECRET_KEY", "")
    minio_bucket: str = os.environ.get("MINIO_BUCKET", "wana-photos")
    minio_secure: bool = os.environ.get("MINIO_SECURE", "0") == "1"

    log_json: bool = os.environ.get("WANA_LOG_JSON", "1") == "1"

    @property
    def issuer(self) -> str:
        return f"{self.kc_issuer_base}/realms/{self.kc_realm}"

    @property
    def auth_enabled(self) -> bool:
        return bool(self.kc_url and self.kc_issuer_base)


settings = Settings()
