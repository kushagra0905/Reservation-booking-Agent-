import logging
from typing import List, Optional

from fastapi import APIRouter
from sqlalchemy import func, select

from database import async_session
from models import ActivityLog, Booking, ReservationRequest
from schemas import ActivityLogOut, BookingOut, StatusOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["status"])


@router.get("/status", response_model=StatusOut)
async def system_status():
    async with async_session() as session:
        total_requests = (
            await session.execute(select(func.count(ReservationRequest.id)))
        ).scalar() or 0
        active_snipers = (
            await session.execute(
                select(func.count(ReservationRequest.id)).where(
                    ReservationRequest.status.in_(("waiting", "polling"))
                )
            )
        ).scalar() or 0
        total_bookings = (
            await session.execute(select(func.count(Booking.id)))
        ).scalar() or 0

    return StatusOut(
        total_requests=total_requests,
        active_snipers=active_snipers,
        total_bookings=total_bookings,
    )


@router.get("/bookings", response_model=List[BookingOut])
async def list_bookings():
    async with async_session() as session:
        result = await session.execute(select(Booking).order_by(Booking.id.desc()))
        return result.scalars().all()


@router.get("/activity", response_model=List[ActivityLogOut])
async def list_activity(request_id: Optional[int] = None, limit: int = 50):
    async with async_session() as session:
        stmt = select(ActivityLog).order_by(ActivityLog.timestamp.desc()).limit(limit)
        if request_id is not None:
            stmt = stmt.where(ActivityLog.request_id == request_id)
        result = await session.execute(stmt)
        return result.scalars().all()


@router.get("/health")
async def health():
    return {"status": "ok"}
