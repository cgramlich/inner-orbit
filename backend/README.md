# Orbit backend

FastAPI + Supabase backend for Orbit (Personal CRM). Adapted from the
MenuCaptain reference plumbing.

## Endpoints
- `GET  /api/health` — liveness.
- `GET  /api/collection/{name}` — load a whole collection for the signed-in user.
- `PUT  /api/collection/{name}` — replace a whole collection.
  Collections: `contacts`, `organizations`, `interactions`, `tasks`, `deals` (arrays), `meta` (object).
- `POST /api/ai/relay` — relay to Claude (task→model routing, capped + metered). Free for now.
- `POST /api/push/register` / `unregister` — device-token registry (dormant; push gated OFF until Firebase).
- `POST /api/account/delete` — wipe all of the user's data.

Auth: every call must send `Authorization: Bearer <supabase access token>`. The
token is verified locally against Supabase's JWKS (ES256). The service_role key
is server-only and bypasses RLS.

## Local dev
```bash
cd backend
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements.txt
cp .env.example .env   # fill in SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, ANTHROPIC_API_KEY
uvicorn main:app --reload --port 8000
```

## Supabase setup
1. Create a new Supabase project for Orbit (own project, isolated data).
2. Run `schema.sql` in the SQL editor (creates tables + service_role grants + RLS).
3. Copy the project URL + service_role key into `.env`.
4. Enable Email auth (and any providers you want) in Supabase Auth settings.

## Deploy (Railway, like MenuCaptain)
- New Railway service from this repo, root directory = `backend/`.
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Set the env vars from `.env.example`. Add the Orbit web domain to `ALLOWED_ORIGINS`.

## Not ported yet (deliberately)
Stripe/Pro billing (comes with the "Pro later" milestone), Google Places,
group orders, GitHub publishing. AI is free + capped (`AI_CALL_CAPS`) for now.
