from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class ReservationCreate(BaseModel):
    restaurant_name: str
    date: str  # YYYY-MM-DD
    time: str  # HH:MM
    party_size: int = 2
    contact_email: str = ""
    venue_id: str = ""
    booking_open_time: Optional[str] = None  # ISO datetime string


class ReservationOut(BaseModel):
    id: int
    restaurant_name: str
    date: str
    time: str
    party_size: int
    contact_email: str
    status: str
    platform: Optional[str]
    booking_open_time: Optional[datetime] = None
    poll_attempts: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SubscriptionOut(BaseModel):
    id: int
    platform: str
    subscribed_at: datetime
    active: bool
    search_date: str
    search_time: str
    search_party_size: int
    restaurant_name: str
    venue_id: Optional[str]

    model_config = {"from_attributes": True}


class BookingOut(BaseModel):
    id: int
    request_id: int
    platform: str
    confirmation_id: Optional[str]
    restaurant_name: str
    date: str
    time: str
    party_size: int
    status: str

    model_config = {"from_attributes": True}


class ActivityLogOut(BaseModel):
    id: int
    request_id: Optional[int]
    timestamp: datetime
    action: str
    platform: Optional[str]
    details: Optional[str]

    model_config = {"from_attributes": True}


class ReservationDetail(ReservationOut):
    subscriptions: List[SubscriptionOut] = []
    bookings: List[BookingOut] = []
    logs: List[ActivityLogOut] = []


class StatusOut(BaseModel):
    total_requests: int
    active_snipers: int
    total_bookings: int
