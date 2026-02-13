from __future__ import annotations

import logging
import re

from playwright.async_api import Page

from automation.browser_manager import human_delay, new_page, save_state, take_screenshot
from config import settings

logger = logging.getLogger(__name__)


async def search_venue(restaurant_name: str, location: str = "new york") -> dict | None:
    """Search Resy for a venue by name and return venue_id + url_slug.

    Returns dict with venue_id, name, url_slug or None if not found.
    """
    page: Page = await new_page()
    try:
        search_url = f"https://resy.com/cities/{location.lower().replace(' ', '-')}"
        await page.goto(search_url, wait_until="domcontentloaded")
        await human_delay()

        # Use the search input
        search_input = page.locator('input[type="search"], input[placeholder*="Search"]')
        if await search_input.count() == 0:
            # Try the header search
            search_button = page.locator('[class*="search"], [data-test*="search"]')
            if await search_button.count() > 0:
                await search_button.first.click()
                await human_delay(500, 1000)
                search_input = page.locator('input[type="search"], input[placeholder*="Search"]')

        if await search_input.count() == 0:
            # Fallback: navigate to search directly
            await page.goto(
                f"https://resy.com/cities/{location.lower().replace(' ', '-')}?query={restaurant_name}",
                wait_until="domcontentloaded",
            )
            await human_delay(1500, 3000)
        else:
            await search_input.first.fill(restaurant_name)
            await human_delay(1000, 2000)

        # Look for search result links containing the restaurant name
        results = page.locator('a[href*="/cities/"]')
        count = await results.count()
        for i in range(min(count, 10)):
            text = await results.nth(i).text_content()
            if text and restaurant_name.lower() in text.lower():
                href = await results.nth(i).get_attribute("href")
                await results.nth(i).click()
                await human_delay(1500, 2500)

                # Extract venue_id from the page
                venue_id = await _extract_venue_id(page)
                url_slug = href.split("/")[-1] if href else ""
                return {
                    "venue_id": venue_id,
                    "name": text.strip(),
                    "url_slug": url_slug,
                }

        logger.warning("Venue '%s' not found in search results", restaurant_name)
        await take_screenshot(page, f"resy_search_fail_{restaurant_name[:20]}")
        return None
    except Exception:
        logger.exception("Venue search failed for '%s'", restaurant_name)
        await take_screenshot(page, f"resy_search_error_{restaurant_name[:20]}")
        return None
    finally:
        await page.close()


async def _extract_venue_id(page: Page) -> str | None:
    """Extract venue_id from Resy venue page via meta tags or embedded JSON."""
    # Try meta tag
    meta = page.locator('meta[property="resy:venue_id"]')
    if await meta.count() > 0:
        return await meta.get_attribute("content")

    # Try embedded script data
    scripts = await page.evaluate("""
        () => {
            const scripts = document.querySelectorAll('script');
            for (const s of scripts) {
                if (s.textContent.includes('venue_id')) {
                    const match = s.textContent.match(/"venue_id"\\s*:\\s*(\\d+)/);
                    if (match) return match[1];
                }
            }
            return null;
        }
    """)
    if scripts:
        return scripts

    # Try URL pattern: /cities/ny/venue-name?venue_id=12345 (unlikely but possible)
    url = page.url
    match = re.search(r"venue_id=(\d+)", url)
    if match:
        return match.group(1)

    return None


async def subscribe_to_notify(
    venue_id: str, restaurant_name: str, date: str, time: str, party_size: int
) -> bool:
    """Subscribe to Resy Notify for a specific venue/date/time.

    This requires browser automation as there's no known API endpoint.
    """
    page: Page = await new_page()
    try:
        # Ensure logged in
        if not await _ensure_logged_in(page):
            logger.error("Cannot subscribe to notify — not logged in to Resy")
            return False

        # Navigate to venue page
        venue_url = f"https://resy.com/cities/new-york-ny?venue_id={venue_id}&date={date}&seats={party_size}"
        await page.goto(venue_url, wait_until="domcontentloaded")
        await human_delay(2000, 3500)

        # Look for the Notify button
        notify_btn = page.locator(
            'button:has-text("Notify"), [class*="notify"], [data-test*="notify"]'
        )
        if await notify_btn.count() == 0:
            logger.info("No Notify button found — table may be available or page layout changed")
            await take_screenshot(page, f"resy_notify_missing_{venue_id}")
            return False

        await notify_btn.first.click()
        await human_delay(1000, 2000)

        # Handle the notify modal — may ask to confirm time preferences
        confirm_btn = page.locator(
            'button:has-text("Confirm"), button:has-text("Submit"), button:has-text("Done")'
        )
        if await confirm_btn.count() > 0:
            await confirm_btn.first.click()
            await human_delay(1000, 2000)

        logger.info(
            "Subscribed to Resy Notify: venue=%s date=%s time=%s party=%d",
            venue_id, date, time, party_size,
        )
        await save_state()
        return True
    except Exception:
        logger.exception("Notify subscription failed for venue %s", venue_id)
        await take_screenshot(page, f"resy_notify_error_{venue_id}")
        return False
    finally:
        await page.close()


async def _ensure_logged_in(page: Page) -> bool:
    """Check if logged in to Resy, login if not."""
    await page.goto("https://resy.com", wait_until="domcontentloaded")
    await human_delay()

    # Check for avatar/profile indicator (logged in)
    profile = page.locator('[class*="avatar"], [class*="profile"], [data-test*="user"]')
    if await profile.count() > 0:
        return True

    # Need to login
    if not settings.resy_email or not settings.resy_password:
        logger.error("Resy credentials not configured")
        return False

    login_link = page.locator('button:has-text("Log In"), a:has-text("Log In")')
    if await login_link.count() > 0:
        await login_link.first.click()
        await human_delay()

    # Fill email
    email_input = page.locator('input[name="email"], input[type="email"]')
    if await email_input.count() > 0:
        await email_input.first.fill(settings.resy_email)
        await human_delay(500, 1000)

    # Fill password
    pw_input = page.locator('input[name="password"], input[type="password"]')
    if await pw_input.count() > 0:
        await pw_input.first.fill(settings.resy_password)
        await human_delay(500, 1000)

    # Submit
    submit = page.locator(
        'button[type="submit"], button:has-text("Continue"), button:has-text("Log In")'
    )
    if await submit.count() > 0:
        await submit.first.click()
        await human_delay(2000, 4000)

    # Verify login success
    profile = page.locator('[class*="avatar"], [class*="profile"], [data-test*="user"]')
    if await profile.count() > 0:
        await save_state()
        return True

    logger.error("Resy login failed")
    await take_screenshot(page, "resy_login_fail")
    return False
