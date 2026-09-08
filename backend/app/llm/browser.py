"""Persistent Playwright Chromium session for the tongyi web app.

Playwright's **sync API is bound to the thread that called
``sync_playwright().start()``**: touching a page from any other thread raises
a greenlet "cannot switch to a different thread" error.  The analysis
pipeline runs on a JobManager background thread while the login endpoints run
on FastAPI request threads, so this module pins EVERY Playwright/Page
operation to one long-lived "owner" thread.

The owner thread is a lazily created ``ThreadPoolExecutor(max_workers=1)``.
Importing this module (or creating the singleton) neither creates the
executor nor launches Chromium; the executor is spawned on first use and all
public methods merely submit their work to it and block for the outcome.
The stored state (``_pw`` / ``context`` / ``page``) is only ever read and
written from inside the owner thread.  The persistent user-data dir
(``settings.data_dir``) keeps the login state across runs.

If the user closes the Chromium window ("zombie" session) page operations
raise a closed-target ``playwright.sync_api.Error``; ``run_on_page`` /
``open_for_login`` recover from that by tearing the dead session down and
retrying the whole operation ONCE on a freshly launched browser.
"""
import concurrent.futures
import threading

from playwright.sync_api import Error as PlaywrightError, sync_playwright

from ..config import settings
from .selectors import SELECTORS, TONGYI_URL

# Error-message fragments meaning the page/context/browser was closed under
# us (user shut the Chromium window) — as opposed to a plain timeout.
_ZOMBIE_MARKERS = (
    "has been closed",  # "Target page, context or browser has been closed"
    "target closed",
    "page closed",
    "context closed",
    "browser closed",
    "connection closed",
    "connection terminated",
)


def is_zombie_error(exc: BaseException) -> bool:
    """True when ``exc`` means the Playwright target was closed (dead session)."""
    if not isinstance(exc, PlaywrightError):
        return False
    msg = str(exc).lower()
    return any(marker in msg for marker in _ZOMBIE_MARKERS)


class BrowserSession:
    """Persistent Chromium context dedicated to tongyi.

    Thread-safe facade: every public method marshals its work onto the
    single owner thread and blocks for the outcome, so callers on any
    thread (JobManager worker, FastAPI request thread, test runner, ...)
    safely share one Playwright session.
    """

    def __init__(self):
        self._pw = None
        self.context = None
        self.page = None
        self._executor = None  # the owner thread; created lazily on first use
        self._executor_lock = threading.Lock()
        self._owner_thread_id = None  # set by the owner-thread initializer

    # ------------------------------------------------------------------
    # owner-thread plumbing (Playwright objects are ONLY touched there)
    # ------------------------------------------------------------------
    def _mark_owner_thread(self):
        """Initializer of the executor's single worker: record its identity."""
        self._owner_thread_id = threading.get_ident()

    def _ensure_executor(self) -> concurrent.futures.ThreadPoolExecutor:
        with self._executor_lock:
            if self._executor is None:
                self._executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix="browser-owner",
                    initializer=self._mark_owner_thread,
                )
            return self._executor

    def _submit(self, fn, *args, **kwargs):
        """Run ``fn`` on the owner thread; block for and return its result.

        Exceptions raised inside ``fn`` propagate to the calling thread.
        If we already ARE the owner thread the callable runs inline, so a
        public method called from inside ``run_on_page`` cannot deadlock.
        """
        if (
            self._owner_thread_id is not None
            and threading.get_ident() == self._owner_thread_id
        ):
            return fn(*args, **kwargs)
        return self._ensure_executor().submit(fn, *args, **kwargs).result()

    # -- owner-thread-only internals -------------------------------------

    def _ensure_started_on_owner(self):
        """(owner thread) Launch the persistent context if not running yet."""
        if self.page is not None:
            return  # already started — simple idempotency guard
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

    def _reset_on_owner(self):
        """(owner thread) Best-effort teardown of a dead/closed session."""
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:
            pass  # already dead — that is exactly what we recover from
        finally:
            self._pw = None
            self.context = None
            self.page = None

    def _page_work(self, fn, *, relaunch_on_zombie: bool):
        """(any thread) Run ``fn(page)`` on the owner thread, with recovery.

        When the Chromium window was closed under us, the dead session is
        reset and the whole operation retried exactly ONCE on a freshly
        launched browser; a second failure propagates to the caller.
        """

        def _attempt():
            self._ensure_started_on_owner()
            return fn(self.page)

        try:
            return self._submit(_attempt)
        except PlaywrightError as exc:
            if not relaunch_on_zombie or not is_zombie_error(exc):
                raise
            # Zombie session: drop it, relaunch once, re-run fn from scratch.
            self._submit(self._reset_on_owner)
            return self._submit(_attempt)  # if this fails too, it propagates

    # ------------------------------------------------------------------
    # thread-safe public API (each submits its work to the owner thread)
    # ------------------------------------------------------------------
    def start(self):
        """Launch the persistent browser and open tongyi.  Idempotent."""
        self._submit(self._ensure_started_on_owner)

    def ensure_started(self):
        """Start the browser if it is not running yet (lazy entry point)."""
        self.start()

    def is_logged_in(self) -> bool:
        """True when the chat input is reachable.  Never raises.

        Fast path: when the browser has not been started the owner thread
        reports ``self.page is None`` and False is returned without any
        page work — no selector wait and, above all, no Chromium window.
        """

        def _check():
            if self.page is None:  # not started yet -> "not logged in"
                return False
            try:
                self.page.wait_for_selector(SELECTORS["chat_input"], timeout=3000)
                return True
            except PlaywrightError as exc:
                if is_zombie_error(exc):
                    # Window closed under us: drop the dead session, but do
                    # NOT relaunch — a status poll must never open a window.
                    self._reset_on_owner()
                return False
            except Exception:
                return False

        try:
            return self._submit(_check)
        except Exception:
            return False

    def open_for_login(self):
        """Open (or focus) the tongyi window so the user can log in manually."""

        def _focus(page):
            page.bring_to_front()
            page.goto(TONGYI_URL)

        self._page_work(_focus, relaunch_on_zombie=True)

    def run_on_page(self, fn):
        """Run ``fn(page)`` on the owner thread and return its result.

        The browser is started on demand and, if the window was closed in
        the meantime, relaunched with a single retry; ``fn``'s return value
        or exception is propagated back to the calling thread.
        """
        return self._page_work(fn, relaunch_on_zombie=True)


browser = BrowserSession()  # singleton; nothing runs until first use
