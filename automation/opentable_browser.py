from __future__ import annotations

import logging

from playwright.async_api import Page

from automation.browser_manager import human_delay, new_page, save_state, take_screenshot
from config import settings

logger = logging.getLogger(__name__)

OPENTABLE_URL = "https://www.opentable.com"


async def _ensure_logged_in(page: Page) -> bool:
    """Check if logged in to OpenTable, login if not."""
    await page.goto(OPENTABLE_URL, wait_until="domcontentloaded")
    await human_delay()

    # Check if already logged in (avatar/profile icon present)
    profile = page.locator('[data-test="user-profile-button"], [class*="avatar"], [aria-label*="profile"]')
    if await profile.count() > 0:
        return True

    if not settings.opentable_email or not settings.opentable_password:
        logger.error("OpenTable credentials not configured")
        return False

    # Click sign in
    signin = page.locator('a:has-text("Sign in"), button:has-text("Sign in")')
    if await signin.count() > 0:
        await signin.first.click()
        await human_delay(1000, 2000)

    # Fill email
    email_input = page.locator('input[name="email"], input[type="email"]')
    if await email_input.count() > 0:
        await email_input.first.fill(settings.opentable_email)
        await human_delay(500, 1000)

    # Continue/Next
    continue_btn = page.locator('button:has-text("Continue"), button[type="submit"]')
    if await continue_btn.count() > 0:
        await continue_btn.first.click()
        await human_delay(1000, 2000)

    # Fill password
    pw_input = page.locator('input[name="password"], input[type="password"]')
    if await pw_input.count() > 0:
        await pw_input.first.fill(settings.opentable_password)
        await human_delay(500, 1000)

    # Submit
    submit = page.locator('button:has-text("Sign in"), button:has-text("Log in"), button[type="submit"]')
    if await submit.count() > 0:
        await submit.first.click()
        await human_delay(3000, 5000)

    # Verify
    profile = page.locator('[data-test="user-profile-button"], [class*="avatar"], [aria-label*="profile"]')
    if await profile.count() > 0:
        await save_state()
        return True

    logger.error("OpenTable login failed")
    await take_screenshot(page, "opentable_login_fail")
    return False


async def search_restaurant(
    restaurant_name: str, date: str, time: str, party_size: int
) -> list[dict]:
    """Search OpenTable for available time slots.

    Returns list of dicts with keys: time, slot_url, restaurant_name.
    """
    page: Page = await new_page()
    try:
        # Build search URL
        # OpenTable date format: YYYY-MM-DD, time: HH:MM
        search_url = (
            f"{OPENTABLE_URL}/s?dateTime={date}T{time}&covers={party_size}"
            f"&term={restaurant_name.replace(' ', '%20')}"
        )
        await page.goto(search_url, wait_until="domcontentloaded")
        await human_delay(2000, 4000)

        # Find restaurant in results
        results = page.locator('[data-test="restaurant-card"], [class*="RestaurantCard"]')
        count = await results.count()
        slots = []

        for i in range(min(count, 5)):
            card = results.nth(i)
            name_el = card.locator('h2, [class*="name"], a[class*="RestaurantName"]')
            name_text = await name_el.first.text_content() if await name_el.count() > 0 else ""

            if not name_text or restaurant_name.lower() not in name_text.lower():
                continue

            # Get available time slots from the card
            time_buttons = card.locator('button[data-test*="time-slot"], [class*="TimeSlot"] button')
            time_count = await time_buttons.count()
            for j in range(time_count):
                btn = time_buttons.nth(j)
                time_text = await btn.text_content()
                if time_text:
                    slots.append({
                        "time": time_text.strip(),
                        "restaurant_name": name_text.strip(),
                        "card_index": i,
                        "slot_index": j,
                    })

            if slots:
                break

        if not slots:
            await take_screenshot(page, f"opentable_search_{restaurant_name[:20]}")

        return slots
    except Exception:
        logger.exception("OpenTable search failed for '%s'", restaurant_name)
        await take_screenshot(page, f"opentable_search_error_{restaurant_name[:20]}")
        return []
    finally:
        await page.close()


async def book_slot(
    restaurant_name: str, date: str, time: str, party_size: int,
    card_index: int = 0, slot_index: int = 0,
) -> dict:
    """Book a specific slot on OpenTable by clicking through the form."""
    page: Page = await new_page()
    try:
        if not await _ensure_logged_in(page):
            return {"success": False, "error": "login_failed"}

        # Navigate to search results
        search_url = (
            f"{OPENTABLE_URL}/s?dateTime={date}T{time}&covers={party_size}"
            f"&term={restaurant_name.replace(' ', '%20')}"
        )
        await page.goto(search_url, wait_until="domcontentloaded")
        await human_delay(2000, 4000)

        # Find the restaurant card
        results = page.locator('[data-test="restaurant-card"], [class*="RestaurantCard"]')
        if await results.count() <= card_index:
            return {"success": False, "error": "restaurant_card_not_found"}

        card = results.nth(card_index)

        # Click the time slot
        time_buttons = card.locator('button[data-test*="time-slot"], [class*="TimeSlot"] button')
        if await time_buttons.count() <= slot_index:
            return {"success": False, "error": "time_slot_not_found"}

        await time_buttons.nth(slot_index).click()
        await human_delay(2000, 3500)

        # Fill booking form
        # First name
        first_name = page.locator('input[name="firstName"], input[data-test="first-name"]')
        if await first_name.count() > 0 and settings.user_first_name:
            await first_name.first.fill(settings.user_first_name)
            await human_delay(300, 600)

        # Last name
        last_name = page.locator('input[name="lastName"], input[data-test="last-name"]')
        if await last_name.count() > 0 and settings.user_last_name:
            await last_name.first.fill(settings.user_last_name)
            await human_delay(300, 600)

        # Phone
        phone = page.locator('input[name="phone"], input[data-test="phone"]')
        if await phone.count() > 0 and settings.user_phone:
            await phone.first.fill(settings.user_phone)
            await human_delay(300, 600)

        # Email
        email = page.locator('input[name="email"], input[data-test="email"]')
        if await email.count() > 0 and settings.user_email:
            await email.first.fill(settings.user_email)
            await human_delay(300, 600)

        # Click complete reservation
        complete_btn = page.locator(
            'button:has-text("Complete"), button:has-text("Reserve"), '
            'button[data-test="complete-reservation"]'
        )
        if await complete_btn.count() == 0:
            await take_screenshot(page, "opentable_no_complete_btn")
            return {"success": False, "error": "no_complete_button"}

        await complete_btn.first.click()
        await human_delay(3000, 5000)

        # Check for confirmation
        confirmation = page.locator(
            '[data-test="confirmation"], [class*="Confirmation"], '
            'h1:has-text("confirmed"), h2:has-text("confirmed")'
        )
        if await confirmation.count() > 0:
            conf_text = await confirmation.first.text_content()
            await save_state()
            return {
                "success": True,
                "confirmation_text": conf_text,
                "booked_time": time,
            }

        await take_screenshot(page, "opentable_book_uncertain")
        return {"success": False, "error": "confirmation_not_detected"}
    except Exception:
        logger.exception("OpenTable booking failed")
        await take_screenshot(page, "opentable_book_error")
        return {"success": False, "error": "exception"}
    finally:
        await page.close()


async def subscribe_to_notify(
    restaurant_name: str, date: str, time: str, party_size: int
) -> bool:
    """Subscribe to OpenTable notifications for a restaurant."""
    page: Page = await new_page()
    try:
        if not await _ensure_logged_in(page):
            return False

        search_url = (
            f"{OPENTABLE_URL}/s?dateTime={date}T{time}&covers={party_size}"
            f"&term={restaurant_name.replace(' ', '%20')}"
        )
        await page.goto(search_url, wait_until="domcontentloaded")
        await human_delay(2000, 4000)

        # Look for notify/alert button on the restaurant card
        notify_btn = page.locator(
            'button:has-text("Notify"), button:has-text("Alert me"), '
            '[data-test*="notify"], [class*="notify"]'
        )
        if await notify_btn.count() > 0:
            await notify_btn.first.click()
            await human_delay(1500, 2500)

            # Confirm if needed
            confirm = page.locator('button:has-text("Confirm"), button:has-text("Submit")')
            if await confirm.count() > 0:
                await confirm.first.click()
                await human_delay(1000, 2000)

            await save_state()
            logger.info("Subscribed to OpenTable notify for %s", restaurant_name)
            return True

        logger.warning("No notify button found on OpenTable for %s", restaurant_name)
        await take_screenshot(page, f"opentable_notify_missing_{restaurant_name[:20]}")
        return False
    except Exception:
        logger.exception("OpenTable notify subscription failed for %s", restaurant_name)
        await take_screenshot(page, f"opentable_notify_error_{restaurant_name[:20]}")
        return False
    finally:
        await page.close()
