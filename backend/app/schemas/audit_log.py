from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditLogResponse(BaseModel):
    id: int
    timestamp: datetime
    operator: str
    action: str
    target_id: int | None
    detail: Any | None

    model_config = {"from_attributes": True}
