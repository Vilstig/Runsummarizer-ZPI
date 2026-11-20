from sqlalchemy.orm import configure_mappers

from app.db.models.activity import (
    Activity,
    ActivityRawPayload,
    ActivitySegment,
    ActivityStream,
    Lap,
)
from app.db.models.base import Base
from app.db.models.hr_zones import HrZones
from app.db.models.import_item import ImportItem
from app.db.models.provider_account import ProviderAccount
from app.db.models.provider_budget import ProviderBudget, ProviderBudgetUsage
from app.db.models.user import User

configure_mappers()

__all__ = [
    "Activity",
    "ActivityRawPayload",
    "ActivitySegment",
    "ActivityStream",
    "Base",
    "HrZones",
    "ImportItem",
    "Lap",
    "ProviderAccount",
    "ProviderBudget",
    "ProviderBudgetUsage",
    "User",
]
