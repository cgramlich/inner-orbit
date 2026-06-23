"""
Orbit (Personal CRM) — FastAPI backend.

Adapted from the MenuCaptain backend (the Forever Apps reference plumbing):
  - Supabase Auth via Bearer JWT (verified locally against JWKS, ES256).
  - service_role Supabase client (bypasses RLS; clients never touch tables
    directly — they always go through this API).
  - Generic whole-collection data API: GET/PUT /api/collection/<name>.
  - Generic AI relay: POST /api/ai/relay (task->model routing, metering,
    cost circuit-breaker). NO domain text injected server-side.
  - Push registry seam (gated OFF until Firebase is configured).

Dining specifics (restaurants/menus/visits, Google Places, group orders,
GitHub publishing, Stripe) are intentionally NOT ported yet. Stripe/Pro comes
with the "Pro later" milestone; AI is free (capped) for now.
"""

import os
import sys
import json
import time
import base64
import logging
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone, date
from typing import Any, Dict, List, Optional

import jwt
from jwt import PyJWKClient
from fastapi import FastAPI, HTTPException, Header, Body, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
from anthropic import Anthropic

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("orbit")

# --------------------------------------------------------------------------- #
# Config / env
# --------------------------------------------------------------------------- #
APP_VERSION = "0.1.0"
APP_ENV = os.getenv("RAILWAY_ENVIRONMENT_NAME", "development")

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
# Only needed if the project signs JWTs with the legacy HS256 shared secret.
# Newer projects use asymmetric keys (ES256/RS256) verified via JWKS — no secret needed.
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Owner/debug (optional)
OWNER_USER_IDS = {u for u in os.getenv("OWNER_USER_IDS", "").split(",") if u}
DEBUG_KEY = os.getenv("DEBUG_KEY", "")

# AI cost guardrails
AI_MONTHLY_BUDGET_USD = float(os.getenv("AI_MONTHLY_BUDGET_USD", "50"))
MAX_TOKENS_CEILING = int(os.getenv("AI_MAX_TOKENS_CEILING", "8192"))

# CORS — web origins + Capacitor native origins.
#   iOS default scheme   = capacitor://localhost
#   Android default      = https://localhost
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "ALLOWED_ORIGINS",
        "https://getinnerorbit.io,https://www.getinnerorbit.io,https://app.getinnerorbit.io,"
        "capacitor://localhost,https://localhost,http://localhost,"
        "http://localhost:8000,http://127.0.0.1:8000,"
        "http://localhost:8300,http://127.0.0.1:8300,http://localhost:8302,http://127.0.0.1:8302",
    ).split(",")
    if o.strip()
]

# --------------------------------------------------------------------------- #
# Collections — Orbit's CRM domain.
#   Whole-collection JSONB model: one row per user per collection, the client
#   reads/writes the entire collection at once (the client is the source of
#   truth for ordering). Arrays default to []; "meta" is a singleton object {}.
# --------------------------------------------------------------------------- #
ARRAY_COLLECTIONS = ("contacts", "organizations", "interactions", "tasks", "deals")
OBJECT_COLLECTIONS = ("meta",)
COLLECTIONS = ARRAY_COLLECTIONS + OBJECT_COLLECTIONS

# --------------------------------------------------------------------------- #
# AI task -> model routing. The server owns the model choice; the client's
# `model` is advisory. Haiku is plenty for these short text tasks; bump to
# Sonnet per-task later if drafting quality needs it.
# --------------------------------------------------------------------------- #
HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-4-6"
AI_MODELS = {
    "summarize_contact": HAIKU,   # condense an interaction history
    "draft_message": HAIKU,       # write a check-in / follow-up message
    "reconnect_opener": HAIKU,    # suggested opener for a reconnect nudge
}
ALLOWED_MODEL_PREFIXES = ("claude-haiku-4-5", "claude-sonnet-4", "claude-opus-4")

AI_PRICES = {  # USD per token
    "claude-haiku-4-5": {"in": 1.0 / 1_000_000, "out": 5.0 / 1_000_000},
    "claude-sonnet-4": {"in": 3.0 / 1_000_000, "out": 15.0 / 1_000_000},
}
_DEFAULT_PRICE = {"in": 3.0 / 1_000_000, "out": 15.0 / 1_000_000}

# Per-user monthly AI call cap by tier. "free" is the only tier today
# (Pro arrives with the billing milestone).
AI_CALL_CAPS = {"free": 50, "pro": 1000}
_DEFAULT_CAP = 50

# --------------------------------------------------------------------------- #
# Clients (initialised in lifespan)
# --------------------------------------------------------------------------- #
supabase: Optional[Client] = None
anthropic_client: Optional[Anthropic] = None
_jwks_client: Optional[PyJWKClient] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global supabase, anthropic_client, _jwks_client
    logger.info(f"[STARTUP] Orbit backend v{APP_VERSION} env={APP_ENV}")

    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        logger.error("[STARTUP] SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing")
        sys.exit(1)
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
        logger.info("[STARTUP] Supabase client ready")
    except Exception as exc:
        logger.error(f"[STARTUP] Supabase init failed: {exc}")
        sys.exit(1)

    _jwks_client = PyJWKClient(
        SUPABASE_URL.rstrip("/") + "/auth/v1/.well-known/jwks.json",
        cache_keys=True,
        lifespan=600,
    )

    if ANTHROPIC_API_KEY:
        anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)
        logger.info("[STARTUP] Anthropic client ready")
    else:
        logger.warning("[STARTUP] ANTHROPIC_API_KEY missing — /api/ai/relay disabled")

    yield


app = FastAPI(title="Orbit CRM API", version=APP_VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def db_exc(op: str, name: str, exc: Exception) -> HTTPException:
    logger.error(f"[DB] {op} {name} failed: {type(exc).__name__}: {exc}")
    return HTTPException(status_code=500, detail=f"Database error ({op} {name})")


def ai_exc(where: str, exc: Exception) -> HTTPException:
    logger.error(f"[AI] {where} failed: {type(exc).__name__}: {exc}")
    return HTTPException(status_code=502, detail="AI provider error")


# --------------------------------------------------------------------------- #
# Auth — verify Supabase access token (ES256, JWKS) and return the user id.
# --------------------------------------------------------------------------- #
def verify_jwt(token: str) -> str:
    """Verify a Supabase access token and return its user id (the 'sub' claim).
    Handles both asymmetric signing keys (ES256/RS256 via JWKS — the default for
    new projects) and the legacy HS256 shared secret (SUPABASE_JWT_SECRET)."""
    try:
        alg = jwt.get_unverified_header(token).get("alg", "")
        if alg.startswith(("ES", "RS")):
            key = _jwks_client.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=[alg], audience="authenticated", leeway=10)
        elif alg == "HS256":
            if not SUPABASE_JWT_SECRET:
                raise RuntimeError("HS256 token but SUPABASE_JWT_SECRET is not set")
            claims = jwt.decode(token, SUPABASE_JWT_SECRET, algorithms=["HS256"], audience="authenticated", leeway=10)
        else:
            raise RuntimeError(f"Unsupported JWT alg '{alg}'")
    except Exception as exc:
        logger.warning(f"[AUTH] JWT verify failed: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Token missing subject")
    return sub


def resolve_user_id(authorization: Optional[str], x_user_id: Optional[str]) -> str:
    """A verified Bearer token is REQUIRED. x_user_id is accepted for client
    signature stability but ignored."""
    if authorization and authorization.strip().lower().startswith("bearer "):
        token = authorization.strip()[7:].strip()
        if token:
            return verify_jwt(token)
    raise HTTPException(status_code=401, detail="Authentication required")


def require_anthropic() -> None:
    if anthropic_client is None:
        raise HTTPException(status_code=503, detail="AI is not configured")


# --------------------------------------------------------------------------- #
# In-memory sliding-window rate limiter (resets on deploy; fine as a backstop).
# --------------------------------------------------------------------------- #
_RATE_BUCKETS: Dict[str, List[float]] = {}


def check_rate_limit(action: str, user_id: str, limit: int, window_seconds: int) -> None:
    now = time.time()
    key = f"{action}:{user_id}"
    recent = [t for t in _RATE_BUCKETS.get(key, []) if now - t < window_seconds]
    if len(recent) >= limit:
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")
    recent.append(now)
    _RATE_BUCKETS[key] = recent


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #
@app.get("/")
@app.get("/api/health")
async def health():
    return {"ok": True, "app": "orbit", "version": APP_VERSION, "env": APP_ENV}


# --------------------------------------------------------------------------- #
# Collections API — generic whole-collection load/save.
# --------------------------------------------------------------------------- #
def _default_for(name: str) -> Any:
    return {} if name in OBJECT_COLLECTIONS else []


@app.get("/api/collection/{name}")
async def get_collection(
    name: str,
    x_user_id: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    user_id = resolve_user_id(authorization, x_user_id)
    if name not in COLLECTIONS:
        raise HTTPException(status_code=404, detail=f"Unknown collection '{name}'")
    try:
        rows = (
            supabase.table(name)
            .select("data")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        raise db_exc("select", name, exc)
    data = rows.data[0]["data"] if rows.data else _default_for(name)
    return data


@app.put("/api/collection/{name}")
async def put_collection(
    name: str,
    payload: Any = Body(...),
    x_user_id: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    user_id = resolve_user_id(authorization, x_user_id)
    if name not in COLLECTIONS:
        raise HTTPException(status_code=404, detail=f"Unknown collection '{name}'")
    # Light shape guard: arrays stay arrays, meta stays an object.
    if name in ARRAY_COLLECTIONS and not isinstance(payload, list):
        raise HTTPException(status_code=400, detail=f"'{name}' must be an array")
    if name in OBJECT_COLLECTIONS and not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail=f"'{name}' must be an object")
    try:
        supabase.table(name).upsert(
            {"user_id": user_id, "data": payload, "updated_at": _now_iso()},
            on_conflict="user_id",
        ).execute()
    except Exception as exc:
        raise db_exc("upsert", name, exc)
    count = len(payload) if isinstance(payload, list) else None
    return {"ok": True, "collection": name, "count": count}


# --------------------------------------------------------------------------- #
# AI relay — task->model routing, metering, cost circuit-breaker. Free (capped).
# --------------------------------------------------------------------------- #
class AIRelayRequest(BaseModel):
    model: str
    max_tokens: int
    messages: List[Dict[str, Any]]
    system: Optional[str] = None
    task: Optional[str] = None


def _price_for(model: str) -> Dict[str, float]:
    for prefix, price in AI_PRICES.items():
        if model.startswith(prefix):
            return price
    return _DEFAULT_PRICE


def _month_start_iso() -> str:
    today = datetime.now(timezone.utc)
    return datetime(today.year, today.month, 1, tzinfo=timezone.utc).isoformat()


def _global_spend_this_period() -> float:
    try:
        rows = (
            supabase.table("ai_usage")
            .select("cost_usd")
            .gte("created_at", _month_start_iso())
            .execute()
        )
        return float(sum((r.get("cost_usd") or 0) for r in rows.data))
    except Exception as exc:
        logger.warning(f"[AI] spend lookup failed (fail-open): {exc}")
        return 0.0


def _usage_calls_this_period(user_id: str) -> int:
    try:
        rows = (
            supabase.table("ai_usage")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .gte("created_at", _month_start_iso())
            .execute()
        )
        return rows.count or 0
    except Exception as exc:
        logger.warning(f"[AI] usage count failed (fail-open): {exc}")
        return 0


def get_tier(user_id: str) -> str:
    # Only "free" today. Pro arrives with the billing milestone.
    return "free"


def enforce_ai_limits(user_id: str, model: str, max_tokens: int) -> int:
    if not model or not model.startswith(ALLOWED_MODEL_PREFIXES):
        raise HTTPException(status_code=400, detail="Unsupported model")
    if _global_spend_this_period() >= AI_MONTHLY_BUDGET_USD:
        logger.error("[AI] CIRCUIT BREAKER: monthly budget reached")
        raise HTTPException(status_code=503, detail="AI is temporarily unavailable")
    tier = get_tier(user_id)
    cap = AI_CALL_CAPS.get(tier, _DEFAULT_CAP)
    if _usage_calls_this_period(user_id) >= cap:
        raise HTTPException(status_code=402, detail="You've reached this month's AI limit")
    return max(1, min(int(max_tokens or 0), MAX_TOKENS_CEILING))


def record_usage(user_id: str, model: str, in_tok: int, out_tok: int) -> None:
    price = _price_for(model)
    cost = in_tok * price["in"] + out_tok * price["out"]
    try:
        supabase.table("ai_usage").insert(
            {
                "user_id": user_id,
                "model": model,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "cost_usd": cost,
                "created_at": _now_iso(),
            }
        ).execute()
    except Exception as exc:
        logger.warning(f"[AI] usage record failed (non-fatal): {exc}")


@app.post("/api/ai/relay")
async def ai_relay(
    req: AIRelayRequest,
    x_user_id: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    user_id = resolve_user_id(authorization, x_user_id)
    require_anthropic()

    model = req.model
    if req.task:
        routed = AI_MODELS.get(req.task)
        if routed:
            model = routed
        else:
            logger.warning(f"[AI] unknown task '{req.task}' from user={user_id}")

    clamped = enforce_ai_limits(user_id, model, req.max_tokens)
    logger.info(f"[AI] relay user={user_id} task={req.task} model={model} max={clamped}")

    def _call(kwargs):
        with anthropic_client.messages.stream(**kwargs) as stream:
            return stream.get_final_message()

    kwargs = {"model": model, "max_tokens": clamped, "messages": req.messages}
    if req.system:
        kwargs["system"] = req.system
    try:
        resp = await asyncio.to_thread(_call, kwargs)
    except Exception as exc:
        raise ai_exc("relay", exc)

    blocks = [{"type": b.type, "text": getattr(b, "text", "")} for b in resp.content]
    usage = getattr(resp, "usage", None)
    record_usage(
        user_id,
        getattr(resp, "model", None) or model,
        getattr(usage, "input_tokens", 0) if usage else 0,
        getattr(usage, "output_tokens", 0) if usage else 0,
    )
    return {"content": blocks, "stop_reason": resp.stop_reason, "model": resp.model}


# --------------------------------------------------------------------------- #
# Push registry seam — gated OFF until Firebase (FCM/APNs) is configured.
# The frontend's PUSH_ENABLED flag also stays false, so these are dormant.
# --------------------------------------------------------------------------- #
class PushRegisterRequest(BaseModel):
    token: str
    platform: Optional[str] = None


@app.post("/api/push/register")
async def push_register(
    payload: PushRegisterRequest,
    x_user_id: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    user_id = resolve_user_id(authorization, x_user_id)
    token = (payload.token or "").strip()
    if not token or len(token) > 4096:
        raise HTTPException(status_code=400, detail="Invalid token")
    platform = (payload.platform or "unknown").strip()[:16] or "unknown"
    try:
        supabase.table("device_tokens").upsert(
            {"user_id": user_id, "token": token, "platform": platform, "updated_at": _now_iso()},
            on_conflict="token",
        ).execute()
    except Exception as exc:
        raise db_exc("upsert", "device_tokens", exc)
    return {"ok": True}


@app.post("/api/push/unregister")
async def push_unregister(
    payload: PushRegisterRequest,
    x_user_id: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    user_id = resolve_user_id(authorization, x_user_id)
    token = (payload.token or "").strip()
    if not token:
        return {"ok": True}
    try:
        supabase.table("device_tokens").delete().eq("token", token).eq(
            "user_id", user_id
        ).execute()
    except Exception as exc:
        raise db_exc("delete", "device_tokens", exc)
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Account deletion — privacy-critical; wipes all of the user's rows.
# --------------------------------------------------------------------------- #
@app.post("/api/account/delete")
async def account_delete(
    x_user_id: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    user_id = resolve_user_id(authorization, x_user_id)
    check_rate_limit("account_delete", user_id, limit=5, window_seconds=3600)
    errors = []
    for name in list(COLLECTIONS) + ["device_tokens", "ai_usage"]:
        try:
            supabase.table(name).delete().eq("user_id", user_id).execute()
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    if errors:
        logger.error(f"[ACCOUNT] partial delete for {user_id}: {errors}")
        raise HTTPException(status_code=500, detail="Account deletion partially failed")
    logger.info(f"[ACCOUNT] deleted all data for {user_id}")
    return {"ok": True}
