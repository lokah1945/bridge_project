"""Base provider interface for bridge automation.

The contract is intentionally kept simple to satisfy the request that
providers expose execute(model_id, prompt, params) -> str. The gateway
converts the OpenAI messages[] into a single prompt string and can chunk
the returned string into an SSE stream.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from playwright.async_api import Page, BrowserContext

from client import browser_manager
from client.config import settings


class BaseProvider(ABC):
    """Abstract base class for all provider automations."""

    def __init__(self, session_data: Dict[str, Any]):
        self.session_data = session_data or {}
        self.cookies = self.session_data.get("cookies", [])
        self.user_agent = self.session_data.get(
            "user_agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36",
        )
        self.headers = self.session_data.get("headers", {})
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def _setup(self, url: str) -> Page:
        """Create a fresh page, inject session, and navigate to the provider URL."""
        self.context = await browser_manager.new_context(self.session_data)
        self.page = await self.context.new_page()
        await browser_manager._apply_stealth(self.page)

        await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            await self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        return self.page

    @abstractmethod
    async def list_models(self, **kwargs) -> List[str]:
        """Return a list of human-readable model names."""
        pass

    @abstractmethod
    async def execute(
        self, model_id: str, prompt: str, params: Dict[str, Any]
    ) -> str:
        """Execute a chat request and return the full response text."""
        pass

    async def cleanup(self) -> None:
        """Close the isolated browser context for this request."""
        if self.page:
            try:
                await self.page.close()
            except Exception:
                pass
            self.page = None
        if self.context:
            await browser_manager.close_context(self.context)
            self.context = None

    async def _safe_click(
        self,
        selector: str,
        timeout: float = 5000,
        fallback_text: Optional[str] = None,
    ) -> bool:
        """Try to click a selector; optionally fall back to text-based click."""
        page = self.page
        if page is None:
            return False

        try:
            await page.click(selector, timeout=timeout)
            return True
        except Exception as e:
            if settings.debug:
                print(f"[BaseProvider] click selector failed '{selector}': {e}")

        if fallback_text:
            try:
                await page.click(f'text="{fallback_text}"', timeout=timeout)
                return True
            except Exception as e:
                if settings.debug:
                    print(f"[BaseProvider] click fallback text failed '{fallback_text}': {e}")
        return False

    async def _fill_textarea(self, prompt: str) -> bool:
        """Find and fill the main chat textarea/input."""
        page = self.page
        if page is None:
            return False

        selectors = [
            "textarea[placeholder*='message']",
            "textarea[placeholder*='ask']",
            "textarea",
            "[contenteditable='true']",
            "input[type='text'][placeholder*='message']",
            "input[type='text']",
        ]
        for sel in selectors:
            try:
                el = await page.wait_for_selector(sel, timeout=3000, state="visible")
                if el is None:
                    continue
                tag = await el.evaluate("el => el.tagName.toLowerCase()")
                if tag == "textarea" or tag == "input":
                    await el.fill("")
                    await el.fill(prompt)
                else:
                    await el.fill("")
                    await el.fill(prompt)
                return True
            except Exception:
                continue
        return False
