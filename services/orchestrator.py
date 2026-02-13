from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session
from models import ActivityLog, Booking, ReservationRequest
from services import resy_service

logger = logging.getLogger(__name__)


async def _log(session: AsyncSession, request_id: int, action: str, platform=None, details=None):
    entry = ActivityLog(
        request_id=request_id,
        action=action,
        platform=platform,
        details=json.dumps(details) if details else None,
    )
    session.add(entry)
    await session.flush()


async def _update_status(session: AsyncSession, request: ReservationRequest, status: str):
    request.status = status
    await session.flush()


async def _resolve_venue_id(request: ReservationRequest) -> str:
    """Get venue_id — from the request if provided, otherwise search the API."""
    if request.venue_id:
        return request.venue_id

    # Fallback: search via Resy API
    results = await resy_service.search_venues(request.restaurant_name)
    if results:
        return results[0]["venue_id"]
    return ""


async def process_reservation(request_id: int):
    """Main orchestration flow for a reservation request."""
    async with async_session() as session:
        request = await session.get(ReservationRequest, request_id)
        if not request:
            logger.error("Request %d not found", request_id)
            return

        await _update_status(session, request, "searching")
        await _log(session, request_id, "search_started")
        await session.commit()

    try:
        # Step 1: Try immediate booking
        booked = await _try_resy(request_id)
        if booked:
            return

        # Step 2: If booking_open_time is set, schedule sniper
        async with async_session() as session:
            request = await session.get(ReservationRequest, request_id)
            if not request:
                return
            if request.status == "cancelled":
                return

            if request.booking_open_time:
                await session.commit()
                await _snipe_reservation(request_id)
            else:
                # No open time — mark as no_availability
                request.status = "no_availability"
                await _log(session, request_id, "no_availability",
                           details={"reason": "No slots found and no booking_open_time set"})
                await session.commit()

    except Exception:
        logger.exception("Error during booking for request %d", request_id)
        async with async_session() as session:
            request = await session.get(ReservationRequest, request_id)
            if request and request.status not in ("booked", "cancelled"):
                request.status = "failed"
                await _log(session, request_id, "orchestration_error")
                await session.commit()


async def _snipe_reservation(request_id: int):
    """Wait until booking_open_time, then rapid-poll every 500ms."""
    async with async_session() as session:
        request = await session.get(ReservationRequest, request_id)
        if not request or request.status == "cancelled":
            return

        wait_seconds = (request.booking_open_time - datetime.now()).total_seconds()
        max_poll_duration = request.max_poll_duration_secs

        if wait_seconds > 0:
            request.status = "waiting"
            await _log(session, request_id, "sniper_waiting",
                       details={"wait_seconds": round(wait_seconds, 1)})
            await session.commit()
            await asyncio.sleep(wait_seconds)
        else:
            await session.commit()

    # Check if cancelled during wait
    async with async_session() as session:
        request = await session.get(ReservationRequest, request_id)
        if not request or request.status == "cancelled":
            return
        request.status = "polling"
        await _log(session, request_id, "sniper_polling_started")
        await session.commit()

    # Rapid poll loop
    start = time.time()
    while (time.time() - start) < max_poll_duration:
        # Check for cancellation periodically
        async with async_session() as session:
            request = await session.get(ReservationRequest, request_id)
            if not request or request.status == "cancelled":
                return

        booked = await _try_resy(request_id)
        if booked:
            return

        # Increment poll_attempts
        async with async_session() as session:
            request = await session.get(ReservationRequest, request_id)
            if request:
                request.poll_attempts += 1
                await session.commit()

        await asyncio.sleep(0.5)

    # Timed out
    async with async_session() as session:
        request = await session.get(ReservationRequest, request_id)
        if request and request.status not in ("booked", "cancelled"):
            request.status = "failed"
            await _log(session, request_id, "sniper_timeout",
                       details={"poll_attempts": request.poll_attempts,
                                "duration_secs": max_poll_duration})
            await session.commit()


async def _try_resy(request_id: int) -> bool:
    async with async_session() as session:
        request = await session.get(ReservationRequest, request_id)
        if not request:
            return False

        await _log(session, request_id, "resy_search", "resy")
        await session.commit()

    venue_id = await _resolve_venue_id(request)
    if not venue_id:
        async with async_session() as session:
            await _log(
                session, request_id, "resy_venue_not_found", "resy",
                {"restaurant": request.restaurant_name},
            )
            await session.commit()
        return False

    # Save venue_id on request if it wasn't set
    if not request.venue_id:
        async with async_session() as session:
            req = await session.get(ReservationRequest, request_id)
            if req:
                req.venue_id = venue_id
                await session.commit()

    # Search and book via API
    result = await resy_service.search_and_book(
        venue_id=venue_id,
        date=request.date,
        time_preferred=request.time,
        party_size=request.party_size,
    )

    async with async_session() as session:
        request = await session.get(ReservationRequest, request_id)
        if not request:
            return False

        if result["success"]:
            request.status = "booked"
            request.platform = "resy"
            booking = Booking(
                request_id=request_id,
                platform="resy",
                confirmation_id=result.get("resy_token") or result.get("reservation_id"),
                restaurant_name=request.restaurant_name,
                date=request.date,
                time=result.get("booked_time", request.time),
                party_size=request.party_size,
                status="confirmed",
                raw_response=json.dumps(result.get("raw", {})),
            )
            session.add(booking)
            await _log(session, request_id, "resy_booked", "resy", result)
            await session.commit()
            return True

        await _log(session, request_id, "resy_unavailable", "resy", result)
        await session.commit()
    return False
