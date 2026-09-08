"""Persistent Playwright Chromium session for the tongyi web app.

The browser is started LAZILY: importing this module (or creating the
singleton) never launches Chromium.  Call ``ensure_started()`` /
``open_for_login()`` when a session is actually needed.  The persistent
user-data dir (``settings.data_dir``) keeps the login state across runs.
"""
from playwright.sync_api import sync_playwright

from ..config import settings
from .selectors import SELECTORS, TONGYI_URL


class BrowserSession:
    """Persistent Chromium context dedicated to tongyi."""

    def __init__(self):
        self._pw = None
        self.context = None
        self.page = None

    def start(self):
        """Launch the persistent browser and open tongyi.  Idempotent."""
        if self.page is not None:
            return  # already started
        self._pw = sync_playwright().start()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.context = self._pw.chromium.launch_persistent_context(
            str(settings.data_dir),
            headless=False,
            accept_downloads=True,
            args=["--start-maximized"],
        )
        self.page = (
            self.context.pages[0] if self.context.pages else self.context.new_page()
        )
        self.page.goto(TONGYI_URL)

    def ensure_started(self):
        """Start the browser if it is not running yet (lazy entry point)."""
        if self.page is None:
            self.start()

    def is_logged_in(self) -> bool:
        """True when the chat input is reachable.  Never raises."""
        if self.page is None:
            return False  # not started yet -> report "not logged in" immediately
        try:
            self.page.wait_for_selector(SELECTORS["chat_input"], timeout=3000)
            return True
        except Exception:
            return False

    def open_for_login(self):
        """Open (or focus) the tongyi window so the user can log in manually."""
        self.ensure_started()
        self.page.bring_to_front()
        self.page.goto(TONGYI_URL)


browser = BrowserSession()  # singleton; NOT started at import time
