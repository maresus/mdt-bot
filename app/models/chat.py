from pydantic import BaseModel
from typing import Optional


class BookingFormData(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    service: Optional[str] = None
    date: Optional[str] = None
    note: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    clinic_id: Optional[str] = None
    booking_form: Optional[BookingFormData] = None


class ChatResponse(BaseModel):
    reply: str
    session_id: Optional[str] = None
    metadata: Optional[dict] = None
