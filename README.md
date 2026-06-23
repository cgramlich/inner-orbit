# Inner Orbit — Personal CRM

Stay close to the people in your orbit. A personal relationship manager (with an
optional lightweight deals layer) in the **Forever Apps** portfolio, built on the
MenuCaptain stack: single-file React-via-CDN + Babel PWA, FastAPI + Supabase
backend, Capacitor native wrap, service-worker offline.

- **Name:** Inner Orbit  ·  **Domain:** getinnerorbit.io
- **appId:** `com.orbitcrm.app` (invisible to users; not yet published — can switch to `com.innerorbit.app` before first publish if desired)
- **Publisher:** MilSpo Life LLC (future Forever Apps)
- **Scope:** see `Dropbox\My AI\CG Apps\Personal CRM\Personal CRM Architecture & Design\SCOPE-crm.md`

## Layout
```
orbit-crm/
  index.html            # the app (single-file PWA) — built in a later pass
  sw.js                 # service worker (offline shell + data reads)
  manifest.json         # PWA manifest
  build.js              # native build: JSX -> www/app.js, vendor libs (store-safe)
  capacitor.config.json # Capacitor (appId/appName/webDir)
  icon-*.png            # icon set (drop-in; generate from a logo)
  backend/              # FastAPI + Supabase API (own Railway service)
    main.py  schema.sql  requirements.txt  .env.example  README.md
```

## Branding = drop-in swap (Forever Apps principle)
Never hardcode brand text/colors. Route through `APP_NAME`/`BRAND` config + an
`ASSETS` map + fixed icon filenames + the CSS `:root` palette.

**Orbit palette (dark default — cosmic indigo):**
```css
:root{
  --bg:#0e1116; --bg-2:#141925; --surface:#1a2030; --surface-2:#222a3d;
  --line:#2c3650; --line-soft:#283044;
  --text:#eef2fb; --text-dim:#a9b4cc; --text-faint:#6f7c99;
  --accent:#6c8cff; --accent-dim:#4f6bd6;          /* periwinkle/indigo */
  --ok:#56c596; --amber:#e7b24c; --danger:#e5645a;
  --shadow:0 8px 28px rgba(0,0,0,0.5);
}
```

## Status
- [x] Repo + infra: `sw.js`, `manifest.json`, `build.js`, `capacitor.config.json`
- [x] Backend skeleton + schema (`backend/`)
- [x] `index.html` shell — auth screen, nav, settings (theme + deals toggle),
      collections + AI relay clients, sync loader, SW registration, in-app updater
      (compiles + renders clean; placeholder CRM screens)
- [x] **Phase 2:** Contacts + Organizations + Tags — list/search/filter, add/edit/delete,
      contact↔company linking, contact & company detail views
- [x] **Phase 3:** Interactions log (timeline + types) + follow-up tasks +
      cadence engine + Home "who to reach out to" / follow-ups / upcoming birthdays
- [x] Explore-offline mode (local-only, no backend) for trying it before Supabase is wired
- [x] **Phase 5:** Deals layer (gated) — pipeline by stage, open/won totals,
      deal form + detail with quick stage changes, contact/company linking
- [ ] **Phase 4:** AI — summarize history / draft message (needs live backend to run)

## Try it now (no backend needed)
Run `python dev_server.py` in this folder, open http://localhost:8300 (or 8302),
tap **“Explore offline (no account)”**, and add contacts / log interactions / set
cadences. Data stays local on the device. The Explore button auto-hides once
`SUPABASE_URL` is set.
- [ ] Supabase project created + `schema.sql` applied
- [ ] Native build (vendor libs, icons) + store listing

## Quick start
- **Backend:** see `backend/README.md`.
- **Frontend (dev):** serve the repo root over http (e.g. `python -m http.server 8000`)
  and open `http://localhost:8000` once `index.html` exists.
