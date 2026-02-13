from __future__ import annotations

import asyncio
import email
import imaplib
import logging
from email.header import decode_header

from config import settings

logger = logging.getLogger(__name__)

RESY_SENDERS = ["notify@resy.com", "no-reply@resy.com"]
OPENTABLE_SENDERS = ["notifications@opentable.com", "no-reply@opentable.com"]


def _decode_header_value(value: str) -> str:
    decoded_parts = decode_header(value)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return "".join(result)


def _get_email_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode("utf-8", errors="replace")
            elif content_type == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode("utf-8", errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode("utf-8", errors="replace")
    return ""


def _identify_platform(from_addr: str) -> str | None:
    from_lower = from_addr.lower()
    for sender in RESY_SENDERS:
        if sender in from_lower:
            return "resy"
    for sender in OPENTABLE_SENDERS:
        if sender in from_lower:
            return "opentable"
    return None


def _parse_notification_email(subject: str, body: str, platform: str) -> dict | None:
    """Extract restaurant name and other details from a notification email.

    Returns dict with restaurant_name, or None if not a relevant notification.
    """
    subject_lower = subject.lower()
    body_lower = body.lower()

    # Check if this is actually a notification (not a marketing email)
    notify_keywords = [
        "table available", "reservation available", "opening",
        "notify", "spot just opened", "now available",
        "a table is available", "good news",
    ]
    is_notify = any(kw in subject_lower or kw in body_lower for kw in notify_keywords)
    if not is_notify:
        return None

    result = {"platform": platform, "subject": subject}

    # Try to extract restaurant name
    # Resy typically: "Good news! A table at [Restaurant] is now available"
    # OpenTable: "[Restaurant] - A table is now available"
    import re

    patterns = [
        r"table at (.+?)(?:\s+is|\s+has|\s+—|\s*-|\.|!)",
        r"(.+?)\s*[-—]\s*[Aa] table",
        r"at (.+?) (?:on|for)",
        r"news.*?(?:at|from)\s+(.+?)(?:\s+is|\.|!)",
    ]
    for pattern in patterns:
        match = re.search(pattern, subject)
        if match:
            result["restaurant_name"] = match.group(1).strip()
            break

    if "restaurant_name" not in result:
        for pattern in patterns:
            match = re.search(pattern, body[:500])
            if match:
                result["restaurant_name"] = match.group(1).strip()
                break

    return result if "restaurant_name" in result else None


async def check_emails() -> list[dict]:
    """Check Gmail for new notification emails from Resy/OpenTable.

    Returns list of parsed notification dicts.
    """
    if not settings.gmail_email or not settings.gmail_app_password:
        return []

    notifications = []
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(settings.gmail_email, settings.gmail_app_password)
        mail.select("INBOX")

        # Search for unread emails from notification senders
        all_senders = RESY_SENDERS + OPENTABLE_SENDERS
        for sender in all_senders:
            _, message_ids = mail.search(None, f'(UNSEEN FROM "{sender}")')
            if not message_ids[0]:
                continue

            for msg_id in message_ids[0].split():
                _, msg_data = mail.fetch(msg_id, "(RFC822)")
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                from_addr = _decode_header_value(msg.get("From", ""))
                subject = _decode_header_value(msg.get("Subject", ""))
                body = _get_email_body(msg)

                platform = _identify_platform(from_addr)
                if not platform:
                    continue

                parsed = _parse_notification_email(subject, body, platform)
                if parsed:
                    parsed["email_id"] = msg_id.decode()
                    notifications.append(parsed)
                    logger.info(
                        "Found notification email: platform=%s restaurant=%s",
                        platform, parsed.get("restaurant_name"),
                    )

                # Mark as read
                mail.store(msg_id, "+FLAGS", "\\Seen")

        mail.logout()
    except imaplib.IMAP4.error:
        logger.exception("IMAP error while checking emails")
    except Exception:
        logger.exception("Error checking emails")

    return notifications


async def start_polling():
    """Main polling loop — runs as a background task."""
    from services.notification_handler import handle_notifications

    logger.info(
        "Gmail monitor started, polling every %ds", settings.gmail_poll_interval_seconds
    )
    while True:
        try:
            notifications = await check_emails()
            if notifications:
                await handle_notifications(notifications)
        except asyncio.CancelledError:
            logger.info("Gmail monitor stopped")
            raise
        except Exception:
            logger.exception("Error in Gmail polling loop")

        await asyncio.sleep(settings.gmail_poll_interval_seconds)
