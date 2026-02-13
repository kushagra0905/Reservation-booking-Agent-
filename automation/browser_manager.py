from __future__ import annotations

import asyncio
import logging
import os
import random

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

logger = logging.getLogger(__name__)

STORAGE_DIR = os.path.join(os.path.dirname(__file__), "..", "browser_state")
SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), "..", "screenshots")

_playwright = None
_browser: Browser | None = None
_context: BrowserContext | None = None


async def get_browser() -> Browser:
    global _playwright, _browser
    if _browser and _browser.is_connected():
        return _browser

    _playwright = await async_playwright().start()
    _browser = await _playwright.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ],
    )
    return _browser


async def get_stealth_context() -> BrowserContext:
    """Create a browser context with anti-detection measures."""
    global _context
    if _context:
        try:
            # Test if context is still alive
            _context.pages  # noqa: B018
            return _context
        except Exception:
            _context = None

    browser = await get_browser()
    os.makedirs(STORAGE_DIR, exist_ok=True)
    storage_path = os.path.join(STORAGE_DIR, "state.json")

    context_opts = {
        "user_agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "viewport": {"width": 1440, "height": 900},
        "locale": "en-US",
        "timezone_id": "America/New_York",
    }
    if os.path.exists(storage_path):
        context_opts["storage_state"] = storage_path

    _context = await browser.new_context(**context_opts)

    # Inject stealth scripts to mask webdriver detection
    await _context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5]
        });
        window.chrome = { runtime: {} };
    """)
    return _context


async def new_page() -> Page:
    ctx = await get_stealth_context()
    return await ctx.new_page()


async def save_state():
    if _context:
        os.makedirs(STORAGE_DIR, exist_ok=True)
        await _context.storage_state(
            path=os.path.join(STORAGE_DIR, "state.json")
        )


async def human_delay(min_ms: int = 800, max_ms: int = 2500):
    await asyncio.sleep(random.randint(min_ms, max_ms) / 1000)


async def take_screenshot(page: Page, name: str) -> str:
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
    path = os.path.join(SCREENSHOTS_DIR, f"{name}.png")
    await page.screenshot(path=path, full_page=True)
    logger.info("Screenshot saved: %s", path)
    return path


async def close():
    global _browser, _context, _playwright
    if _context:
        await save_state()
        await _context.close()
        _context = None
    if _browser:
        await _browser.close()
        _browser = None
    if _playwright:
        await _playwright.stop()
        _playwright = None


def is_ready() -> bool:
    return _browser is not None and _browser.is_connected()
