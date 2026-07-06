from __future__ import annotations
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

class Event(BaseModel):
    type: str
    ts: float
    request_id: Optional[str] = None
    job_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)

def make_event(event_type: str, *, payload: Dict[str, Any] | None = None,
               request_id: str | None = None, job_id: str | None = None) -> Dict[str, Any]:
    import time
    e = Event(type=event_type, ts=time.time(), request_id=request_id, job_id=job_id,
              payload=payload or {})
    return e.model_dump()
