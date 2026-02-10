from pydantic import BaseModel
from typing import Optional


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    clinic_id: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    session_id: Optional[str] = None
    metadata: Optional[dict] = None
