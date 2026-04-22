from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


async def log_action(
    db: AsyncSession,
    operator: str,
    action: str,
    target_id: int | None = None,
    detail: Any | None = None,
) -> None:
    db.add(
        AuditLog(
            operator=operator,
            action=action,
            target_id=target_id,
            detail=detail,
        )
    )
    await db.commit()
