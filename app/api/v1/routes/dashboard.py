from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_dashboard_service, require_manager_or_above
from app.db.session import get_db
from app.identity.models.user import User
from app.schemas.dashboard import DashboardSummaryResponse
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/", response_model=DashboardSummaryResponse)
async def get_dashboard_summary(
    expiring_leases_lookahead_days: int = 30,
    recent_payments_limit: int = 10,
    db: AsyncSession = Depends(get_db),
    dashboard_service: DashboardService = Depends(get_dashboard_service),
    current_user: User = Depends(require_manager_or_above),
):
    """Composed landlord dashboard: collected this month, outstanding,
    total credits, late payments, vacant units, expiring leases, and recent payments."""
    return DashboardSummaryResponse(
        collected_this_month=await dashboard_service.collected_this_month(db, current_user),
        outstanding=await dashboard_service.outstanding(db, current_user),
        total_credits=await dashboard_service.total_credits(db, current_user),
        late_payments=await dashboard_service.late_payments(db, current_user),
        vacant_units=await dashboard_service.vacant_units(db, current_user),
        expiring_leases=await dashboard_service.expiring_leases(
            db, current_user, lookahead_days=expiring_leases_lookahead_days
        ),
        recent_payments=await dashboard_service.recent_payments(db, current_user, limit=recent_payments_limit),
    )
