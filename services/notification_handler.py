from __future__ import annotations

import json
import logging

from sqlalchemy import select

from database import async_session
from models import ActivityLog, NotificationSubscription, ReservationRequest

logger = logging.getLogger(__name__)


async def handle_notifications(notifications: list[dict]):
    """Match incoming email notifications to active subscriptions and trigger auto-booking."""
    for notif in notifications:
        restaurant_name = notif.get("restaurant_name", "")
        platform = notif.get("platform", "")

        if not restaurant_name or not platform:
            continue

        # Find matching active subscriptions
        async with async_session() as session:
            stmt = (
                select(NotificationSubscription)
                .where(NotificationSubscription.active.is_(True))
                .where(NotificationSubscription.platform == platform)
            )
            result = await session.execute(stmt)
            subscriptions = result.scalars().all()

        # Match by restaurant name (fuzzy — case-insensitive contains)
        matched = []
        for sub in subscriptions:
            if (
                restaurant_name.lower() in sub.restaurant_name.lower()
                or sub.restaurant_name.lower() in restaurant_name.lower()
            ):
                matched.append(sub)

        if not matched:
            logger.info(
                "No matching subscription for notification: platform=%s restaurant=%s",
                platform, restaurant_name,
            )
            continue

        for sub in matched:
            await _process_match(sub, notif)


async def _process_match(sub: NotificationSubscription, notif: dict):
    """Process a matched notification — update status and trigger auto-booking."""
    from services.orchestrator import auto_book_from_notification

    async with async_session() as session:
        request = await session.get(ReservationRequest, sub.request_id)
        if not request:
            return
        if request.status in ("booked", "cancelled"):
            return

        request.status = "notify_received"
        log = ActivityLog(
            request_id=sub.request_id,
            action="notification_received",
            platform=sub.platform,
            details=json.dumps({
                "restaurant": notif.get("restaurant_name"),
                "subject": notif.get("subject"),
                "email_id": notif.get("email_id"),
            }),
        )
        session.add(log)
        await session.commit()

    logger.info(
        "Auto-booking triggered for request %d via %s notification",
        sub.request_id, sub.platform,
    )
    success = await auto_book_from_notification(sub.request_id, sub.platform)

    if success:
        # Deactivate all subscriptions for this request
        async with async_session() as session:
            stmt = select(NotificationSubscription).where(
                NotificationSubscription.request_id == sub.request_id
            )
            result = await session.execute(stmt)
            for s in result.scalars():
                s.active = False
            await session.commit()
        logger.info("Auto-booking succeeded for request %d", sub.request_id)
    else:
        logger.warning("Auto-booking failed for request %d", sub.request_id)
