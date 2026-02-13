from __future__ import annotations

import json
import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.resy.com"
HEADERS = {
    "authorization": f'ResyAPI api_key="{settings.resy_api_key}"',
    "x-resy-auth-token": settings.resy_auth_token,
    "x-resy-universal-auth": settings.resy_auth_token,
    "origin": "https://widgets.resy.com",
    "referer": "https://widgets.resy.com/",
    "accept": "application/json",
    "content-type": "application/x-www-form-urlencoded",
}


def _make_headers() -> dict:
    return {
        "authorization": f'ResyAPI api_key="{settings.resy_api_key}"',
        "x-resy-auth-token": settings.resy_auth_token,
        "x-resy-universal-auth": settings.resy_auth_token,
        "origin": "https://widgets.resy.com",
        "referer": "https://widgets.resy.com/",
        "accept": "application/json",
        "content-type": "application/x-www-form-urlencoded",
    }


async def search_venues(query: str) -> list:
    """Search Resy for venues matching a query string.

    Returns list of dicts with venue_id, name, neighborhood, cuisine, url_slug.
    """
    payload = {
        "query": query,
        "geo": {"latitude": 40.7128, "longitude": -74.0060},
        "types": ["venue"],
        "per_page": 5,
    }
    headers = _make_headers()
    headers["content-type"] = "application/json"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{BASE_URL}/3/venuesearch/search",
            json=payload,
            headers=headers,
        )
        if resp.status_code != 200:
            logger.warning("Venue search failed: %s %s", resp.status_code, resp.text[:200])
            return []

    data = resp.json()
    hits = data.get("search", {}).get("hits", [])
    results = []
    for hit in hits:
        venue_id = hit.get("id", {})
        if isinstance(venue_id, dict):
            venue_id = str(venue_id.get("resy", ""))
        else:
            venue_id = str(venue_id)
        results.append({
            "venue_id": venue_id,
            "name": hit.get("name", ""),
            "neighborhood": hit.get("neighborhood", ""),
            "cuisine": hit.get("cuisine", []),
            "region": hit.get("location", {}).get("name", ""),
            "url_slug": hit.get("url_slug", ""),
        })
    return results


async def find_available_slots(
    venue_id: str, date: str, party_size: int
) -> list[dict]:
    """Search Resy for available reservation slots.

    Returns list of slot dicts with keys: config_id, token, time, type.
    """
    params = {
        "lat": "40.7128",
        "long": "-74.0060",
        "day": date,
        "party_size": str(party_size),
        "venue_id": venue_id,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{BASE_URL}/4/find", params=params, headers=_make_headers()
        )
        if resp.status_code == 401:
            logger.warning("Resy auth token expired — needs refresh")
            return []
        if resp.status_code != 200:
            logger.warning("Resy find returned %s: %s", resp.status_code, resp.text[:200])
            return []

    data = resp.json()
    results = data.get("results", {})
    venues = results.get("venues", [])
    if not venues:
        return []

    slots = []
    for venue in venues:
        for slot_group in venue.get("slots", []):
            config = slot_group.get("config", {})
            date_info = slot_group.get("date", {})
            slots.append(
                {
                    "config_id": config.get("id"),
                    "token": config.get("token"),
                    "time": date_info.get("start"),
                    "type": config.get("type"),
                }
            )
    return slots


async def get_slot_details(config_id: str, date: str, party_size: int) -> dict | None:
    """Get booking details for a specific slot (needed before booking)."""
    params = {
        "config_id": config_id,
        "day": date,
        "party_size": str(party_size),
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{BASE_URL}/3/details", params=params, headers=_make_headers()
        )
        if resp.status_code != 200:
            logger.error("Failed to get slot details: %s", resp.text)
            return None

    data = resp.json()
    book_token = data.get("book_token", {})
    return {
        "book_token": book_token.get("value"),
        "date": book_token.get("date_starts"),
        "cancellation_policy": data.get("cancellation", {}).get("display", {}).get("policy"),
    }


async def book_slot(book_token: str) -> dict:
    """Book a reservation using the book token from details endpoint."""
    payload = {
        "book_token": book_token,
        "struct_payment_method": json.dumps(
            {"id": int(settings.resy_payment_method_id)}
        )
        if settings.resy_payment_method_id
        else "",
        "source_id": "resy.com-venue-details",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            f"{BASE_URL}/3/book",
            data=payload,
            headers=_make_headers(),
        )
        if resp.status_code != 200:
            logger.error("Booking failed: %s %s", resp.status_code, resp.text)
            return {"success": False, "error": resp.text}

    data = resp.json()
    return {
        "success": True,
        "resy_token": data.get("resy_token"),
        "reservation_id": data.get("reservation_id"),
        "raw": data,
    }


async def search_and_book(
    venue_id: str, date: str, time_preferred: str, party_size: int
) -> dict:
    """End-to-end: find slots → pick best match → get details → book.

    Returns dict with success bool and booking info or error.
    """
    slots = await find_available_slots(venue_id, date, party_size)
    if not slots:
        return {"success": False, "error": "no_availability"}

    # Pick the closest slot to the preferred time
    best = _pick_best_slot(slots, time_preferred)
    if not best:
        return {"success": False, "error": "no_matching_slot"}

    details = await get_slot_details(best["config_id"], date, party_size)
    if not details or not details.get("book_token"):
        return {"success": False, "error": "details_failed"}

    result = await book_slot(details["book_token"])
    if result["success"]:
        result["booked_time"] = best["time"]
    return result


def _pick_best_slot(slots: list[dict], preferred_time: str) -> dict | None:
    """Pick the slot closest to the preferred time (HH:MM)."""
    if not slots:
        return None

    def time_diff(slot):
        slot_time = slot.get("time", "")
        if not slot_time:
            return 9999
        # slot_time might be "2024-01-15 19:30:00" or just "19:30"
        time_part = slot_time.split(" ")[-1][:5] if " " in slot_time else slot_time[:5]
        try:
            sh, sm = int(time_part[:2]), int(time_part[3:5])
            ph, pm = int(preferred_time[:2]), int(preferred_time[3:5])
            return abs((sh * 60 + sm) - (ph * 60 + pm))
        except (ValueError, IndexError):
            return 9999

    return min(slots, key=time_diff)


async def subscribe_to_notify(venue_id: str, date: str, time_preferred: str, party_size: int) -> bool:
    """Subscribe to Resy Notify via API for a venue/date/time."""
    # Resy uses a POST to /3/notify for notify subscriptions
    payload = {
        "venue_id": venue_id,
        "day": date,
        "time_preferred": time_preferred,
        "party_size": str(party_size),
        "service_type_id": "2",  # dinner
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{BASE_URL}/3/notify",
            data=payload,
            headers=_make_headers(),
        )
        if resp.status_code in (200, 201):
            logger.info("Resy Notify subscribed: venue=%s date=%s", venue_id, date)
            return True
        logger.warning(
            "Resy Notify subscription failed: %s %s", resp.status_code, resp.text[:300]
        )
    return False


async def refresh_auth_token() -> str | None:
    """Get a fresh auth token using email/password login."""
    payload = {
        "email": settings.resy_email,
        "password": settings.resy_password,
    }
    headers = {
        "authorization": f'ResyAPI api_key="{settings.resy_api_key}"',
        "accept": "application/json",
        "content-type": "application/x-www-form-urlencoded",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{BASE_URL}/3/auth/password", data=payload, headers=headers
        )
        if resp.status_code != 200:
            logger.error("Auth refresh failed: %s", resp.text)
            return None

    data = resp.json()
    token = data.get("token")
    if token:
        settings.resy_auth_token = token
        payment_methods = data.get("payment_method_id")
        if payment_methods:
            settings.resy_payment_method_id = str(payment_methods)
        logger.info("Resy auth token refreshed")
    return token
