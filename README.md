# MineSense Wana

Chrome prospectivity map and offline field app for small-scale miners. Pilot: Shurugwi, Midlands, Zimbabwe.

Wana shows places worth checking. It does not prove a resource and does not confer mining rights.

## What is in this folder

| Part | Built on (open source) | Folder |
|---|---|---|
| Data download | pystac-client + planetary-computer (Copernicus DEM, Sentinel-2 L2A, ASTER L1T), USGS MRDS | `backend/wana/ingest.py` |
| Evidence stack | rasterio, pyproj, shapely, scipy | `backend/wana/stack.py` |
| Model | scikit-learn logistic regression ensemble | `backend/wana/model.py` |
| API | FastAPI + SQLite | `backend/wana/api.py` |
| Web app + field app | React, Vite, MapLibre GL, Dexie (IndexedDB), vite-plugin-pwa | `frontend/` |
| Android app (Wana Field) | Capacitor, wrapping the same React app | `mobile/` |
| Deployment | Docker + Caddy (automatic HTTPS) | `Dockerfile`, `docker-compose.yml`, `deploy/` |
| CI | GitHub Actions: tests, lint, web build, Android APK | `.github/workflows/ci.yml` |

## Quick start on Windows

Needs Python 3.10+ and Node.js 20+.

```
setup.bat          (once)
run_sample.bat     (synthetic SAMPLE data, to try the system)
```

Open http://127.0.0.1:8000. You start in the miner view. To get the geologist view, click **Miner view · sign in** and enter the key. The development key is `dev-geologist-key`. Set `WANA_GEOLOGIST_KEY` to a long random string before anyone else uses the app.

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
(set in `frontend/.env.mobile`; default `https://wana.161-97-176-218.sslip.io`). The last answers from the server are
kept on the phone, so targets and cards still open with no network, and records wait in the outbox until signal returns.

- **Download:** every push to `main` builds `wana-field.apk` in GitHub Actions (run page → Artifacts). Pushing a tag
  such as `v0.1.0` also attaches the APK to a GitHub Release.
- **Build locally:** needs Node 20+, JDK 21 and the Android SDK (or Android Studio):
  `cd mobile && npm install && npm run apk` → `mobile/android/app/build/outputs/apk/debug/app-debug.apk`.
  Without Android Studio, `mobile/build-env/Dockerfile` gives a build container.
- The APK is a debug build (installs by sideloading). Sign a release build before Play Store distribution.

## Deploying on a server that already runs Caddy

```
git clone https://github.com/kuzivakwashe0225/mine-sense-wana.git && cd mine-sense-wana/deploy
cp .env.example .env            # set WANA_GEOLOGIST_KEY (openssl rand -hex 24) and WANA_DOMAIN
docker compose -f docker-compose.server.yml up -d --build
# add deploy/Caddyfile.snippet to /etc/caddy/Caddyfile, validate, reload
```

The first start builds the SAMPLE dataset so the app works immediately. Load real data with
`docker compose -f docker-compose.server.yml exec wana python -m wana ingest` (then `stack`, `train`).

## Privacy and safety built in

- Miners see targets as 1 km blocks and a 1 km ranking map. Exact points, occurrences, photos and the 30 m ranking need the geologist key. This is enforced by the server, not just hidden in the browser.
- Each target card carries the no-rights disclaimer, a mineral-rights notice (that layer stays hidden until verified data is available) and safety flags for steep ground and nearby old workings.

## Tests

```
cd backend && python -m pytest -q                     # pipeline, model, API, roles, idempotent sync
python tests_e2e/e2e.py                               # browser flow (needs Playwright and a server on :8000)
```

## Known limits

- **Training data is thin.** A live check (Oct 2026) found 9 USGS MRDS chrome records in the pilot box at about 7
  distinct locations: just enough to train (minimum 5) and only 2 in the hold-out area. Geologist-labelled occurrences
  from the Survey sheets are needed before the validation numbers mean anything.
- Sentinel-1 radar (named in the concept note) is not yet a layer; structures come from the digitised maps only.
- The mineral-rights layer is a placeholder notice until verified Mining Commissioner data is available, as the concept note intends.
- Machines with PostGIS, QGIS or OSGeo4W often set `PROJ_LIB`/`GDAL_DATA` system-wide, which breaks rasterio.
  Wana clears them at start-up; set `WANA_KEEP_PROJ_ENV=1` to keep them.

- **The real-data download has not yet been run against the live services.** It was built offline, and only the code paths were tested, on sample files in the same formats. Run `--dry-run` first. The ASTER step prints the asset keys it finds; if Planetary Computer has changed them, the step reports that and skips ASTER rather than guessing.
- USGS MRDS may hold only a few chromite sites inside the pilot box. Training refuses to run with fewer than 5 points, so geologist-labelled occurrences are needed.
- The ASTER index uses DN band ratios with no atmospheric correction. That is fine for relative ranking within one district, but the values cannot be compared between districts.
- Phones need **HTTPS** to use GPS and to install the app for offline use. Over plain `http://<laptop-ip>`, typed coordinates still work, but GPS and offline install do not. Use `docker-compose.yml` with a domain, or a tunnel, for fieldwork.
- The basemap is OpenStreetMap's public tile server, which is fine for a pilot. Use a tile provider (for example MapTiler) or self-hosted tiles beyond that.
- One shared geologist key and SQLite are fine for a pilot. Move to per-user accounts and PostGIS before scaling.
- The ChiShona text is a draft. It must be reviewed by Shona-speaking miners.
