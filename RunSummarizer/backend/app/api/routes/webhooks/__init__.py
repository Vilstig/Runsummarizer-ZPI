from fastapi import APIRouter

from app.api.routes.webhooks import clerk, providers

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
router.include_router(clerk.router)
router.include_router(providers.router)
