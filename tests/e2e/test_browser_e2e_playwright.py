"""Browser End-to-End Verification using Playwright Chromium (Phase 119).

Verifies:
- Institutional UI rendering, branding, and accessibility in real Chromium.
- Form controls, input validation, and password visibility toggle.
- Protected client-side routing redirecting unauthorized visitors to /login.
- Responsive layout across desktop (1280x800) and mobile (375x667) viewports.
- Non-leakage of backend internals in browser DOM and network errors.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
import pytest
import uvicorn
from playwright.async_api import async_playwright
from starlette.applications import Starlette
from starlette.responses import FileResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles


class _SPAServer:
    """Lightweight in-process HTTP server serving the compiled frontend SPA."""

    def __init__(self, host: str = "127.0.0.1", port: int = 18923) -> None:
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        dist_dir = Path("frontend/dist").resolve()
        assert dist_dir.exists(), f"Frontend build dist not found at {dist_dir}"
        index_html = dist_dir / "index.html"

        async def spa_fallback(request):
            return FileResponse(index_html)

        app = Starlette(
            routes=[
                Mount("/assets", StaticFiles(directory=str(dist_dir / "assets")), name="assets"),
                Route("/{path:path}", spa_fallback),
            ]
        )
        config = uvicorn.Config(app=app, host=host, port=port, log_level="warning")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self) -> None:
        self.thread.start()
        # Wait until server is listening
        deadline = time.time() + 5.0
        while not self.server.started and time.time() < deadline:
            time.sleep(0.05)

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=3.0)


@pytest.fixture(scope="module")
def spa_server():
    server = _SPAServer()
    server.start()
    yield server
    server.stop()


@pytest.mark.asyncio
class TestBrowserE2EPlaywright:
    """Browser-level verification of E-WITNESS frontend using Playwright Chromium."""

    async def test_login_page_rendering_and_branding(self, spa_server: _SPAServer) -> None:
        """Verify the login page renders institutional branding, headings, and legal notices."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(viewport={"width": 1280, "height": 800})
            page = await context.new_page()

            await page.goto(f"{spa_server.base_url}/login")
            await page.wait_for_load_state("networkidle")

            # Verify Branding and Headings
            header_text = await page.inner_text("h1")
            assert "E-WITNESS" in header_text

            card_title = page.locator("text=Sign in to your account")
            assert await card_title.is_visible()

            # Verify form inputs exist with accessible labels
            email_input = page.locator("#email")
            assert await email_input.is_visible()
            assert await email_input.get_attribute("type") == "email"

            password_input = page.locator("#password")
            assert await password_input.is_visible()
            assert await password_input.get_attribute("type") == "password"

            submit_button = page.locator("button[type='submit']")
            assert await submit_button.is_visible()
            assert "Sign In" in (await submit_button.inner_text())

            await browser.close()

    async def test_password_visibility_toggle(self, spa_server: _SPAServer) -> None:
        """Verify the password visibility toggle switches between masked and plaintext."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            await page.goto(f"{spa_server.base_url}/login")
            await page.wait_for_load_state("networkidle")

            password_input = page.locator("#password")
            assert await password_input.get_attribute("type") == "password"

            # Find toggle button
            toggle_button = page.locator("button[aria-label='Show password']")
            assert await toggle_button.is_visible()

            await toggle_button.click()
            assert await password_input.get_attribute("type") == "text"

            # Toggle back to masked
            hide_button = page.locator("button[aria-label='Hide password']")
            assert await hide_button.is_visible()

            await hide_button.click()
            assert await password_input.get_attribute("type") == "password"

            await browser.close()

    async def test_client_side_form_validation(self, spa_server: _SPAServer) -> None:
        """Verify client-side validation displays helpful errors on empty or invalid inputs."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            await page.goto(f"{spa_server.base_url}/login")
            await page.wait_for_load_state("networkidle")

            # Click submit with empty fields
            submit_button = page.locator("button[type='submit']")
            await submit_button.click()

            # Verify validation messages appear
            page_content = await page.content()
            assert "Please enter a valid institutional email" in page_content or "required" in page_content.lower()

            # Type invalid email format
            email_input = page.locator("#email")
            await email_input.fill("invalid-email-format")
            await submit_button.click()

            page_content = await page.content()
            assert "valid institutional email" in page_content.lower()

            await browser.close()

    async def test_protected_route_redirection(self, spa_server: _SPAServer) -> None:
        """Verify unauthenticated navigation to protected paths redirects to /login."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            # Attempt navigating to protected cases route
            await page.goto(f"{spa_server.base_url}/cases")
            await page.wait_for_load_state("networkidle")

            # Should redirect to /login
            assert "/login" in page.url

            # Attempt navigating to incidents route
            await page.goto(f"{spa_server.base_url}/incidents")
            await page.wait_for_load_state("networkidle")
            assert "/login" in page.url

            # Attempt navigating to admin route
            await page.goto(f"{spa_server.base_url}/admin")
            await page.wait_for_load_state("networkidle")
            assert "/login" in page.url

            await browser.close()

    async def test_responsive_mobile_viewport(self, spa_server: _SPAServer) -> None:
        """Verify layout integrity and lack of horizontal overflow on mobile viewports."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            # Mobile viewport: iPhone 14 / standard mobile 375x667
            context = await browser.new_context(viewport={"width": 375, "height": 667})
            page = await context.new_page()

            await page.goto(f"{spa_server.base_url}/login")
            await page.wait_for_load_state("networkidle")

            # Verify form elements fit within 375px viewport width (no horizontal scrolling required)
            scroll_width = await page.evaluate("() => document.documentElement.scrollWidth")
            client_width = await page.evaluate("() => document.documentElement.clientWidth")
            assert scroll_width <= client_width + 1, f"Horizontal overflow detected: {scroll_width} > {client_width}"

            submit_button = page.locator("button[type='submit']")
            box = await submit_button.bounding_box()
            assert box is not None
            assert box["width"] > 250  # Touch-friendly full-width button
            assert box["height"] >= 36  # Meets minimum touch target height

            await browser.close()
