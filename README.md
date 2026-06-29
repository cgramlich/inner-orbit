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
  index.html            # the app (single-file PWA)
  CLAUDE.md             # architecture / endpoints / env / conventions (read this first)
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

## Status — LIVE on the web
Inner Orbit is deployed and in use. (Deployed version is sourced from `APP_VERSION` in
`index.html` + the `/api/health` endpoint — never hardcoded here.)
- **App:** https://getinnerorbit.io — GitHub Pages (repo root), HTTPS
- **API:** https://inner-orbit-production.up.railway.app — Railway (`backend/`); health at `/api/health`
- **DB / Auth:** Supabase (ES256 / JWKS); schema in `backend/schema.sql`

**Built (V1):** contacts · organizations · tags · interaction log · follow-up + cadence
"who to reach out to" engine · upcoming birthdays · gated deals pipeline · AI (✨ Summarize /
✨ Draft check-in) · vCard import with dedupe · offline mode.

**Next:** contact-import rounds (Gmail → iCloud) · Google Contacts sync · email-to-timeline ·
Blinq-style digital business card · Apple contacts + Capacitor native build + store listings.

See **`CLAUDE.md`** for architecture, endpoints, env vars, and conventions.

## Run it
- **Live app:** https://getinnerorbit.io
- **Local frontend:** `python dev_server.py` → http://localhost:8300 (or any static host).
  "Explore offline (no account)" appears only while `SUPABASE_URL` is unset.
- **Local backend:** see `backend/README.md` (`uvicorn main:app` with `backend/.env`).
- **Native build:** `node build.js` → precompiles JSX to `www/` for Capacitor.
