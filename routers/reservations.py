import asyncio
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database import async_session
from models import ReservationRequest
from schemas import ReservationCreate, ReservationDetail, ReservationOut
from services.orchestrator import process_reservation
from services.resy_service import search_venues

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reservations", tags=["reservations"])


@router.get("/search/venues")
async def venue_search(q: str):
    """Search Resy for restaurants by name. Used for autocomplete."""
    if len(q) < 2:
        return []
    results = await search_venues(q)
    return results


@router.post("", response_model=ReservationOut, status_code=201)
async def create_reservation(data: ReservationCreate):
    async with async_session() as session:
        booking_open_time = None
        if data.booking_open_time:
            booking_open_time = datetime.fromisoformat(data.booking_open_time)

        req = ReservationRequest(
            restaurant_name=data.restaurant_name,
            date=data.date,
            time=data.time,
            party_size=data.party_size,
            contact_email=data.contact_email,
            venue_id=data.venue_id or None,
            booking_open_time=booking_open_time,
            status="pending",
        )
        session.add(req)
        await session.commit()
        await session.refresh(req)
        request_id = req.id

    # Fire and forget the orchestrator in the background
    asyncio.create_task(process_reservation(request_id))
    async with async_session() as session:
        req = await session.get(ReservationRequest, request_id)
        return req


@router.get("", response_model=List[ReservationOut])
async def list_reservations(status: Optional[str] = None):
    async with async_session() as session:
        stmt = select(ReservationRequest).order_by(ReservationRequest.created_at.desc())
        if status:
            stmt = stmt.where(ReservationRequest.status == status)
        result = await session.execute(stmt)
        return result.scalars().all()


@router.get("/{request_id}", response_model=ReservationDetail)
async def get_reservation(request_id: int):
    async with async_session() as session:
        stmt = (
            select(ReservationRequest)
            .where(ReservationRequest.id == request_id)
            .options(
                selectinload(ReservationRequest.subscriptions),
                selectinload(ReservationRequest.bookings),
                selectinload(ReservationRequest.logs),
            )
        )
        result = await session.execute(stmt)
        req = result.scalar_one_or_none()
        if not req:
            raise HTTPException(404, "Reservation not found")
        return req


@router.delete("/{request_id}")
async def cancel_reservation(request_id: int):
    async with async_session() as session:
        stmt = (
            select(ReservationRequest)
            .where(ReservationRequest.id == request_id)
            .options(selectinload(ReservationRequest.subscriptions))
        )
        result = await session.execute(stmt)
        req = result.scalar_one_or_none()
        if not req:
            raise HTTPException(404, "Reservation not found")
        req.status = "cancelled"
        for sub in req.subscriptions:
            sub.active = False
        await session.commit()
    return {"status": "cancelled"}


@router.post("/{request_id}/retry")
async def retry_reservation(request_id: int):
    async with async_session() as session:
        req = await session.get(ReservationRequest, request_id)
        if not req:
            raise HTTPException(404, "Reservation not found")
        if req.status == "booked":
            raise HTTPException(400, "Already booked")
        req.status = "pending"
        await session.commit()

    asyncio.create_task(process_reservation(request_id))
    return {"status": "retrying"}
