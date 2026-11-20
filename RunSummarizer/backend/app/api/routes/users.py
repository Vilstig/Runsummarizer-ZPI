from fastapi import APIRouter, Depends

from app.api.deps import get_user_service, require_user
from app.api.schemas.errors import ErrorResponse
from app.api.schemas.users import HeartRateZonesSchema, UserProfileSchema
from app.domain.models import HeartRateZones, UserProfile
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me/profile", response_model=UserProfileSchema)
async def get_user_profile(
    user_id: str = Depends(require_user),
    service: UserService = Depends(get_user_service),
):
    """Return the signed-in user's profile. Unset fields are null."""
    return UserProfileSchema.model_validate(
        await service.get_profile(user_id), from_attributes=True
    )


@router.put(
    "/me/profile",
    response_model=UserProfileSchema,
    responses={409: {"model": ErrorResponse}},
)
async def put_user_profile(
    body: UserProfileSchema,
    user_id: str = Depends(require_user),
    service: UserService = Depends(get_user_service),
):
    """Replace the signed-in user's profile. Fields left out are stored as null."""
    await service.replace_profile(user_id, UserProfile(**body.model_dump()))
    return body


@router.get("/me/hr-zones", response_model=HeartRateZonesSchema | None)
async def get_hr_zones(
    user_id: str = Depends(require_user),
    service: UserService = Depends(get_user_service),
):
    """Return the signed-in user's current heart rate zones, or null when none are set."""
    zones = await service.get_hr_zones(user_id)
    if zones is None:
        return None
    return HeartRateZonesSchema.model_validate(zones, from_attributes=True)


@router.put(
    "/me/hr-zones",
    response_model=HeartRateZonesSchema,
    responses={409: {"model": ErrorResponse}},
)
async def put_hr_zones(
    body: HeartRateZonesSchema,
    user_id: str = Depends(require_user),
    service: UserService = Depends(get_user_service),
):
    """Set the signed-in user's heart rate zones."""
    await service.replace_hr_zones(user_id, HeartRateZones(**body.model_dump()))
    return body
