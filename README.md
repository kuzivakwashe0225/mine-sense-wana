# MineSense Wana

Chrome prospectivity map and offline field app for small-scale miners. Pilot: Shurugwi, Midlands, Zimbabwe.

Wana shows places worth checking. It does not prove a resource and does not confer mining rights.

## What is in this folder

| Part | Built on (open source) | Folder |
|---|---|---|
| Data download | pystac-client + planetary-computer (Copernicus DEM, Sentinel-2 L2A, ASTER L1T), USGS MRDS | `backend/wana/ingest.py` |
| Evidence stack | rasterio, pyproj, shapely, scipy | `backend/wana/stack.py` |
| Model | scikit-learn logistic regression ensemble | `backend/wana/model.py` |
| API | FastAPI + SQLite, Redis (rate limits, idempotency, locks), MinIO (photos) | `backend/wana/api.py` |
| Accounts and sign-in | Keycloak (OIDC + PKCE), Wana sign-in and email theme | `backend/wana/auth.py`, `infra/keycloak/` |
| Monitoring | Prometheus metrics and alerts, Grafana dashboard, JSON logs with request ids | `backend/wana/obs.py`, `infra/` |
| Web app + field app | React, Vite, MapLibre GL, Dexie (IndexedDB), vite-plugin-pwa, keycloak-js, react-icons | `frontend/` |
| Android app (Wana Field) | Capacitor, wrapping the same React app | `mobile/` |
| Deployment | Docker Compose, one container per service | `docker-compose.yml`, `infra/`, `.env.example` |
| CI | GitHub Actions: tests, lint, web build, Android APK | `.github/workflows/ci.yml` |

## Quick start on Windows

Needs Python 3.10+ and Node.js 20+.

```
setup.bat          (once)
run_sample.bat     (synthetic SAMPLE data, to try the system)
```

Open http://127.0.0.1:8000. This is **laptop mode**: there is no sign-in server, so every request is treated as a local
geologist (`WANA_DEV_AUTH=geologist`, set by the batch file). It is ignored whenever Keycloak is configured. For
accounts, sessions and everything else, run the full stack below.

## Full stack (Docker): every service in its own container

| Container | Role | Reachable at |
|---|---|---|
| `web` | nginx: the app, and the single public entry routing `/api` and `/auth` | `127.0.0.1:8095` (TLS from the host's Caddy) |
| `api` | FastAPI, model pipeline (non-root, read-only filesystem) | internal |
| `keycloak` + `keycloak-db` | accounts, sign-in, password emails; Postgres for Keycloak | admin console `127.0.0.1:8180/auth/admin` |
| `redis` | rate limits, idempotency keys, retrain lock | internal |
| `minio` + `minio-init` | private photo bucket; one-shot setup of the bucket and an app user | console `127.0.0.1:9101` |
| `mailpit` | every email passes through; relays to real SMTP when configured | `127.0.0.1:8026` |
| `prometheus` + `grafana` | metrics, 7 alert rules, "MineSense Wana · overview" dashboard | `127.0.0.1:9190`, `127.0.0.1:3110` |

```
cp .env.example .env        # fill in every secret: openssl rand -hex 24
docker compose up -d --build
```

Consoles listen on 127.0.0.1 only. From your PC: `ssh -L 3110:127.0.0.1:3110 -L 8026:127.0.0.1:8026 user@server`,
then open http://localhost:3110 (Grafana) or http://localhost:8026 (Mailpit).

The first start builds the SAMPLE dataset so the app works at once, and creates an administrator account for
`WANA_ADMIN_EMAIL`, who receives a link to choose a password. Load real data with
`docker compose exec api python -m wana ingest` (then `stack`, `train`).

**Email.** Keycloak sends through Mailpit. To deliver to real inboxes, set `WANA_SMTP_RELAY_*` and
`WANA_SMTP_RELAY_ALL=true` in `.env` (for Gmail: an App Password from Google Account > Security > App passwords,
host `smtp.gmail.com`, port 587), then `docker compose up -d mailpit`.

## Accounts and sessions

- **Sign-up** asks only for name and email. Keycloak emails a one-time link (24 h) to confirm the address and choose a
  password. New accounts are miners; an administrator grants **geologist** or **admin** in *Admin · users*.
- **Sign-in** happens on Keycloak's pages, themed to match the app (`infra/keycloak/themes/wana`). Tokens stay in memory.
- **A refresh keeps you signed in** (Keycloak's SSO cookie, checked silently). Only *Log out* ends it.
- **Idle sign-out:** after 15 minutes without meaningful activity, with a 60-second "Stay signed in" warning first.
  Clicks, taps, typing, scrolling and successful saves count; **mouse movement does not**. Reading a target card or a
  report counts as activity for up to 30 minutes. Activity in another tab counts too.
- **You come back where you were:** the page, selected target, map view, layer switches, typed lab results and the
  unsent field form are kept. After an idle sign-out, signing in returns the same person to that place.
- Keycloak's own idle (30 min) and maximum (10 h) session limits are the server-side backstop. Tune the app's timings
  with `WANA_IDLE_SECONDS`, `WANA_WARN_SECONDS`, `WANA_READING_SECONDS`.

## Data handling in the app

| Pattern | Where |
|---|---|
| Request deduplication | `frontend/src/query.js`: components asking for the same URL share one request |
| Stale-while-revalidate | the last answer shows at once (memory, then this device, per user) and refreshes in the background; ETags make re-checks an empty 304 |
| Smart polling | review queue (15 s to 2 min), my records, model version: slows while nothing changes, pauses when hidden or offline, checks at once on return |
| Retry with backoff | `withRetry` in `api.js`: jittered exponential backoff for network, 5xx and 429 (honours `Retry-After`), never for user errors; the field outbox retries 2 s to 5 min |
| Optimistic updates | review decisions, role changes and profile edits show at once and roll back with the reason if refused |
| Streaming UI | "Update map" streams each training stage (`/api/model/retrain/stream`, NDJSON) |
| Deduplicated writes | `Idempotency-Key` on changes; offline re-sync is idempotent by record id |

## Errors and monitoring

Every error is one of three kinds, counted separately and shown to people differently:
**user** (fix your input or sign in), **business** (a rule refused: record locked, nothing new to add, update already
running) and **platform** (our fault: logged with a request id and alerted). Browsers and phones report platform and
network errors to the server. See `docs/PRODUCTION_AUDIT.md` for the audit and the alert list.

## Using real data

1. **Digitise the geology** (team task, QGIS). Put these in `data\inputs\`:
   - `geology.geojson`: polygons from the Geological Survey sheets. Each one has a `unit` name and `"ultramafic": true/false`.
   - `structures.geojson`: shear and fault lines.
   - `occurrences.csv`: known chromite points, with columns `id,lon,lat,label,source,notes`. Use `label = chromite`. Survey records, old workings and geologist labels all go here.
   - optional `magnetics.tif`: any airborne magnetics grid you are given.
2. Run `run_real.bat`. It first does a dry run that only searches the catalogues and prints what it found, then downloads the data, builds the stack, trains and starts the app.
3. Check the **Data sources** tab. Every layer must show **real**. The yellow "Sample data" banner disappears only when no sample layer is left.

Command reference (run from `backend\` with the venv active):

```
python -m wana ingest --dry-run          # search only
python -m wana ingest --only dem,s2      # some sources only
python -m wana stack                     # rebuild evidence stack
python -m wana train                     # new model version from occurrences + reviewed field records
python -m wana serve --port 8000
```

## How the model works

- The model is a presence-background logistic regression on standardised evidence layers. Fifteen bootstrap models give the ranking and its spread.
- Each target card's "why" bars are coefficient × layer value at that cell, so a geologist can audit every claim.
- Confidence is low where the bootstrap models disagree or where a weighted layer is missing (for example, outside the magnetics cover).
- **Validation is a spatial hold-out.** Occurrences south of `holdout_rule.value` in `wana.json` are never used for training. Change that value so that 25–35% of the real occurrences fall in the test area.
- **Skeptic check.** `backend/tests/test_pipeline.py::test_random_labels_do_not_validate` retrains on random fake occurrences and fails unless the hold-out AUC drops back near 0.5.
- Field records are endorsed or rejected by the geologist. They enter the next model version as presences or confirmed blanks. Records already used in a version are locked.

## Android app (Wana Field)

`mobile/` packages the same web app as an Android app with Capacitor, so the map, target cards, picture checklist,
offline outbox, GPS and camera all behave as tested in the browser. The app talks to the server in `VITE_API_BASE`
(set in `frontend/.env.mobile`; default `https://minesense-wana.meshcloud.co.zw`). The last answers from the server are
kept on the phone, so targets and cards still open with no network, and records wait in the outbox until signal returns.

- **Download:** every push to `main` builds `wana-field.apk` in GitHub Actions (run page → Artifacts). Pushing a tag
  such as `v0.1.0` also attaches the APK to a GitHub Release.
- **Build locally:** needs Node 20+, JDK 21 and the Android SDK (or Android Studio):
  `cd mobile && npm install && npm run apk` → `mobile/android/app/build/outputs/apk/debug/app-debug.apk`.
  Without Android Studio, `mobile/build-env/Dockerfile` gives a build container.
- The APK is a debug build (installs by sideloading). Sign a release build before Play Store distribution.

## Deploying

On a server whose ports 80/443 already belong to Caddy, run the full stack as above and add `deploy/Caddyfile.snippet`
to `/etc/caddy/Caddyfile`, then validate and reload. On an empty server, `docker compose --profile standalone up -d`
adds a Caddy container instead.

## Privacy and safety built in

- Miners see targets as 1 km blocks and a 1 km ranking map. Exact points, occurrences, photos and the 30 m ranking need a geologist account. This is enforced by the server, not just hidden in the browser.
- Each target card carries the no-rights disclaimer, a mineral-rights notice (that layer stays hidden until verified data is available) and safety flags for steep ground and nearby old workings.

## Tests

```
cd backend && python -m pytest -q          # pipeline, model, API, tokens, roles, sign-up, limits, idempotency, streaming
cd frontend && npm test                    # session policy and data layer (vitest)
python tests_e2e/e2e_auth.py               # 25 browser checks on the running stack: sign-up by email link, sign-in,
                                           # refresh, idle warning, expiry and return, profile, admin, review, phone
                                           # (set WANA_IDLE_SECONDS=80 WANA_READING_SECONDS=30 in .env for this run)
```

## Known limits

- **Training data is thin.** A live check (Oct 2026) found 9 USGS MRDS chrome records in the pilot box at about 7
  distinct locations: just enough to train (minimum 5) and only 2 in the hold-out area. Geologist-labelled occurrences
  from the Survey sheets are needed before the validation numbers mean anything.
- Sentinel-1 radar (named in the concept note) is not yet a layer; structures come from the digitised maps only.
- The mineral-rights layer is a placeholder notice until verified Mining Commissioner data is available, as the concept note intends.
- Machines with PostGIS, QGIS or OSGeo4W often set `PROJ_LIB`/`GDAL_DATA` system-wide, which breaks rasterio.
  Wana clears them at start-up; set `WANA_KEEP_PROJ_ENV=1` to keep them.

- USGS MRDS may hold only a few chromite sites inside the pilot box. Training refuses to run with fewer than 5 points, so geologist-labelled occurrences are needed.
- The ASTER index uses DN band ratios with no atmospheric correction. That is fine for relative ranking within one district, but the values cannot be compared between districts.
- Phones need **HTTPS** to use GPS and to install the app for offline use. Over plain `http://<laptop-ip>`, typed coordinates still work, but GPS and offline install do not. Use `docker-compose.yml` with a domain, or a tunnel, for fieldwork.
- The basemap is OpenStreetMap's public tile server, which is fine for a pilot. Use a tile provider (for example MapTiler) or self-hosted tiles beyond that.
- SQLite holds the field records, which is fine with one API container. Move to PostGIS before running several.
- The ChiShona text is a draft. It must be reviewed by Shona-speaking miners.
