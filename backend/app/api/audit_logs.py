from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import require_admin
from app.database import get_db
from app.models.audit_log import AuditLog
from app.schemas.audit_log import AuditLogResponse

router = APIRouter(prefix="/api/audit-logs", tags=["audit-logs"])


@router.get("/", response_model=list[AuditLogResponse])
async def list_audit_logs(
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    _auth: dict = Depends(require_admin),
):
    result = await db.execute(
        select(AuditLog)
        .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
        .limit(limit)
    )
    return result.scalars().all()
