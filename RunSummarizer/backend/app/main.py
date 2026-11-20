from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_exception_handlers
from app.api.routes import activities, health, providers, sync, users, webhooks
from app.config.loader import CONFIG
from app.config.settings import FRONTEND_URL
from app.config.validation import validate_required_settings
from app.core.body_limit import DEFAULT_MAX_BODY_BYTES, BodySizeLimitMiddleware
from app.core.logging import configure_logging, install_redacting_access_log
from app.core.request_context import RequestContextMiddleware
from app.db.client import dispose_engine
from app.ratelimiter import RateLimitMiddleware


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_required_settings()
    install_redacting_access_log()
    configure_logging()
    yield
    await dispose_engine()


app = FastAPI(title="RunSummarizer", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL or "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    BodySizeLimitMiddleware,
    max_bytes=CONFIG.get("MAX_REQUEST_BODY_BYTES", DEFAULT_MAX_BODY_BYTES),
)
# Last add_middleware is outermost: request id wraps every other layer.
app.add_middleware(RequestContextMiddleware)
register_exception_handlers(app)


@app.get("/")
async def root():
    return {"message": "Welcome to RunSummarizer"}


api = APIRouter(prefix="/api")

v1 = APIRouter(prefix="/v1")
v1.include_router(activities.router)
v1.include_router(sync.router)
v1.include_router(providers.router)
v1.include_router(users.router)

api.include_router(v1)

api.include_router(health.router)
api.include_router(webhooks.router)
api.include_router(providers.callback_router)

app.include_router(api)
