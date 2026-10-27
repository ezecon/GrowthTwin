import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pathlib import Path

from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import advisor, auth, expert, irrigation, messaging, meta, solarflow, trust, twin
from .core.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    if s.app_env == "prod" and not s.auth_required:
        raise RuntimeError("AUTH_REQUIRED must be true in prod (dev mode trusts X-Dev-Role headers)")
    if s.auth_required and not (s.supabase_url and s.supabase_service_key and s.supabase_anon_key):
        raise RuntimeError("AUTH_REQUIRED=true needs SUPABASE_URL, SUPABASE_SERVICE_KEY and SUPABASE_ANON_KEY")
    task = asyncio.create_task(irrigation.loop())
    yield
    task.cancel()


app = FastAPI(title="GrowthTwin API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_methods=["*"], allow_headers=["*"],
)
for r in (meta.router, auth.router, advisor.router, expert.router, twin.router, trust.router, irrigation.router, messaging.router, solarflow.router):
    app.include_router(r)

# Farmer UI served from the same origin (no CORS needed): http://localhost:8000/
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="ui")
