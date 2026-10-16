# Production audit (16 October 2026)

Scope: the full stack as deployed by `docker-compose.yml` (web, api, keycloak, keycloak-db, redis, minio, minio-init,
mailpit, prometheus, grafana), the web app, the Android app and the CI pipeline.

## How it was checked

| Check | Tool | Result |
|---|---|---|
| Backend unit and API tests | pytest (22 tests) | pass |
| Frontend unit tests (session policy, data layer) | vitest (12 tests) | pass |
| Full browser journey on the running stack | Playwright, `tests_e2e/e2e_auth.py` (25 checks) | pass |
| Python dependency vulnerabilities | pip-audit | none |
| JavaScript dependency vulnerabilities (shipped code) | npm audit --omit=dev (web, mobile) | none after fix 1 |
| Secrets in the repository | gitleaks on every staged file | none (one false positive annotated) |
| Endpoints that must not be public | curl through the web proxy | all 404 |
| Security headers | curl | present |
| Container privileges and exposed ports | docker top, compose ps | see below |
| Monitoring wiring | Prometheus targets and rules, Grafana API | all targets up, 7 alerts loaded |

## Findings fixed during the audit

1. **Critical: XSS sanitizer bypass in MapLibre GL ≤ 6.4** (GHSA-jrc7-96c5-q579). Upgraded to 6.14. Version 6 builds its
   worker URL at run time, so the worker is now bundled explicitly (`MapView.jsx`), and nginx serves `.mjs` as JavaScript.
2. **High: the service worker answered Keycloak pages with the app shell.** After one visit, every email link
   (set password, reset password) opened a blank page. `/auth/` and the silent sign-in page are now excluded.
3. **High: the service worker cached API answers by URL only, not by user.** On a shared phone a miner could be served a
   geologist's cached data offline. API caching moved to the app's own cache, which is keyed by user and cleared on sign-out;
   the full-resolution ranking image is no longer stored in the shared image cache.
4. **Medium: custom user attributes were silently dropped.** Keycloak 26 discards attributes not declared in the user
   profile, so `organisation` was lost on sign-up. Declared in the realm (users can view it; only the server edits it).
5. **Medium: the sign-up page was remembered as "where the user was".** Coming back from the email link showed the
   sign-up form again. Sign-up is now a one-off screen.
6. **Low: the hidden frame that keeps users signed in across refreshes was blocked** by `frame-ancestors 'none'`.
   That page now allows same-origin framing only.

## Controls in place

**Identity and sessions**
- Keycloak (OIDC authorization code + PKCE, public client, no implicit or password grant). Tokens live in memory only.
- The API checks the signature (RS256, keys from Keycloak), issuer, audience (`wana-api`) and expiry on every request.
  An invalid or expired token gets 401, never a silent downgrade to the public view.
- Passwords: 10 characters minimum, not equal to email, last 3 not reused. Brute-force lockout after 5 failures
  (growing wait, up to 15 minutes). Users choose their own password from a one-time emailed link (24 h).
- Sessions: the app signs out after 15 minutes without meaningful activity, with a 60-second warning. Mouse movement is not
  activity; reading a card counts for up to 30 minutes. Keycloak's SSO idle timeout (30 min) and max lifetime (10 h) are
  the server-side backstop. Refresh tokens rotate and cannot be reused.
- Sign-up cannot be used to discover which emails have accounts (same answer either way).
- Rate limits (Redis): sign-up 5/hour per network and 3/day per address, field records 120/hour per user, invites,
  profile changes and client error reports.

**Data protection**
- Location precision is enforced by the server: miners and visitors get 1 km blocks; exact points, occurrences, photos
  and the 30 m ranking need the geologist role.
- Field photos in a private MinIO bucket (no anonymous access, versioning on), reached only through the API with the
  geologist role. The API uses its own MinIO user limited to that bucket.
- Uploads: 8 MB limit, type checked from the file's content (JPEG, PNG, WebP); the stored name never comes from the client.
- Mutations accept an `Idempotency-Key`, so retries cannot apply a change twice; offline re-sync is idempotent by `client_id`.

**Network and containers**
- Only `web` (nginx) is published, on 127.0.0.1; TLS is added by the host's Caddy. Keycloak's admin console and admin API,
  `/metrics` and health endpoints return 404 publicly. Consoles (Keycloak 8180, Mailpit 8026, MinIO 9101, Grafana 3110,
  Prometheus 9190) listen on 127.0.0.1 only: use an SSH tunnel.
- Headers: Content-Security-Policy (no inline scripts), HSTS, nosniff, Referrer-Policy, Permissions-Policy
  (geolocation and camera for this site only), frame-ancestors none.
- The API container runs as an unprivileged user with a read-only root filesystem, all capabilities dropped and
  no-new-privileges. Redis and Postgres run as their own users. Images are pinned to exact versions (MinIO by digest).

**Observability**
- Every request gets an `X-Request-ID`, returned to the browser and written in a JSON log line.
- Errors are classified as **user** (bad input, not signed in), **business** (a rule refused: record locked, nothing to
  retrain, already running) or **platform** (our fault). Each has a counter by code, and users see a message that
  matches the kind.
- Browsers and phones report platform and network errors to `/api/client-errors` (rate-limited, no personal data).
- Prometheus scrapes the API, Keycloak and MinIO; 7 alert rules (API down, platform error bursts, dependency down,
  slow requests, sign-in failure spikes, user-error spikes). Grafana dashboard "MineSense Wana · overview" is provisioned.

## Accepted risks and follow-ups

| Item | Why accepted now | Follow-up |
|---|---|---|
| Mailpit relays mail but stores copies | Needed to see emails during the pilot | Turn retention down or remove once a real SMTP relay is set |
| Mailpit and the nginx master process run as root inside their containers | Upstream image defaults; no published ports | Switch to rootless variants |
| SQLite for field records | Single API process in the pilot | Move to Postgres/PostGIS before more than one API replica |
| Alerts are evaluated but not sent anywhere | No on-call channel chosen yet | Add Alertmanager with email or WhatsApp |
| Debug-signed Android APK | Sideloading for the pilot | Release signing key, Play Store listing |
| `style-src 'unsafe-inline'` in the CSP | MapLibre and React set inline styles | Revisit if those libraries offer nonce support |
| Chainguard MinIO image pinned to a `latest-dev` digest | Official MinIO images were withdrawn | Track updates and re-pin monthly |
