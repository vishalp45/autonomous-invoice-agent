"""Browser tools (Playwright).each tool returns {"ok": bool, ...}."""
from pathlib import Path
from playwright.sync_api import sync_playwright

SHOTS = Path(__file__).resolve().parent.parent / "evidence"

class BrowserTools:
    def __init__(self, headless: bool = True):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=headless)
        self.page = self._browser.new_page()
        self.page.set_default_timeout(3000)  # fail fast so the agent can adapt
        SHOTS.mkdir(exist_ok=True)

    def open_page(self, url: str) -> dict:
        try:
            self.page.goto(url)
            return {"ok": True, "title": self.page.title(), "url": self.page.url}
        except Exception as e:
            return {"ok": False, "error": str(e).splitlines()[0]}

    def get_page_text(self) -> dict:
        """What a human would see: visible text of the page."""
        try:
            return {"ok": True, "text": self.page.inner_text("body")}
        except Exception as e:
            return {"ok": False, "error": str(e).splitlines()[0]}

    def fill(self, selector: str, value: str) -> dict:
        try:
            self.page.fill(selector, value)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e).splitlines()[0]}

    def click(self, selector: str) -> dict:
        try:
            self.page.click(selector)
            self.page.wait_for_load_state()
            return {"ok": True, "url": self.page.url}
        except Exception as e:
            return {"ok": False, "error": str(e).splitlines()[0]}

    def screenshot(self, name: str) -> dict:
        try:
            path = SHOTS / name
            self.page.screenshot(path=str(path))
            return {"ok": True, "path": str(path)}
        except Exception as e:
            return {"ok": False, "error": str(e).splitlines()[0]}

    def close(self):
        self._browser.close()
        self._pw.stop()
