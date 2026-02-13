from __future__ import annotations

import logging

from automation.opentable_browser import book_slot, search_restaurant

logger = logging.getLogger(__name__)


async def search_and_book(
    restaurant_name: str, date: str, time: str, party_size: int
) -> dict:
    """Search OpenTable and book the best matching slot."""
    slots = await search_restaurant(restaurant_name, date, time, party_size)
    if not slots:
        return {"success": False, "error": "no_availability"}

    # Pick the best slot (first one is usually closest to requested time)
    best = slots[0]

    result = await book_slot(
        restaurant_name=restaurant_name,
        date=date,
        time=time,
        party_size=party_size,
        card_index=best.get("card_index", 0),
        slot_index=best.get("slot_index", 0),
    )

    if result.get("success"):
        result["booked_time"] = best.get("time", time)
    return result
