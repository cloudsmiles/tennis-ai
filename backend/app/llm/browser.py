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
import subprocess
import threading

from playwright.sync_api import Error as PlaywrightError, sync_playwright

from ..config import settings
from . import qianwen_login
from .selectors import LOGIN_STATE_JS, TONGYI_URL

# 调用侧超时（秒）。page.evaluate 没有自带超时，千问页面的渲染进程可能忙循环
# （实测 CPU 100%+ 不返回），不加时限会永久挂住唯一的 owner 线程，导致登录态
# 查询、登录、分析的所有请求一起排队卡死。
OP_TIMEOUT_START = 45  # 冷启动浏览器 + goto 首页
OP_TIMEOUT_STATUS = 6  # 登录态轮询（空闲时单次 evaluate <1s）
OP_TIMEOUT_LOGIN = 60  # 手机号/验证码登录流程
OP_TIMEOUT_WORK = 200  # 完整对话（回复等待内部上限 180s，属正常长任务）


class OwnerBusyError(RuntimeError):
    """提交到 owner 线程的任务还在排队（owner 正忙于另一个长任务，如分析）。

    与"执行中挂死"严格区分：排队超时绝不杀浏览器，否则会误杀正在正常进行
    的 LLM 分析。
    """

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
        # owner 线程疑似挂死时的恢复锁 + 会话世代号（废弃旧 executor 时失效
        # 残留在旧线程队列里的任务，防止它们在旧线程复活后启动第二个浏览器）
        self._hang_lock = threading.Lock()
        self._generation = 0
        # 最近一次确知的登录态（owner 忙于长任务时直接返回它，秒回不排队）；
        # None = 尚不知晓
        self._login_cache: bool | None = None

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

    def _submit(self, fn, *args, timeout=None, **kwargs):
        """Run ``fn`` on the owner thread; block for and return its result.

        Exceptions raised inside ``fn`` propagate to the calling thread.
        If we already ARE the owner thread the callable runs inline, so a
        public method called from inside ``run_on_page`` cannot deadlock.

        ``timeout`` bounds the wait on the caller side: Playwright's
        ``evaluate`` has no timeout of its own and a wedged qianwen tab can
        hang the owner thread forever. On timeout the browser is force-killed
        to unblock the owner thread, then the TimeoutError propagates.
        """
        if (
            self._owner_thread_id is not None
            and threading.get_ident() == self._owner_thread_id
        ):
            return fn(*args, **kwargs)

        # started 区分两种超时：fn 已开跑 = Playwright 调用挂死（恢复+杀浏览器）；
        # fn 仍在队列 = owner 在忙另一个正常长任务（取消本任务，绝不杀浏览器）。
        started = threading.Event()

        def _wrapped():
            started.set()
            return fn(*args, **kwargs)

        future = self._ensure_executor().submit(_wrapped)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            if started.is_set():
                self._recover_from_hang()
                raise
            future.cancel()  # 仍在单线程队列里：取消安全，不影响正在跑的任务
            raise OwnerBusyError("browser owner thread is busy")

    def _recover_from_hang(self) -> None:
        """A Playwright call exceeded its caller-side timeout — the single
        owner thread is presumed wedged (qianwen tab busy-looping).

        Force-kill the Chromium using our profile: the blocked call then
        fails with a closed-connection error and the owner thread is free
        again. Queue a reset on it (page=None → next call relaunches). If
        the owner thread does not come back within 20s, abandon the whole
        executor: the next call gets a fresh thread/browser. The stale
        generation invalidates any tasks still queued on the old thread so
        they cannot launch a second browser against the same profile.
        """
        if not self._hang_lock.acquire(blocking=False):
            return  # another caller is already recovering
        try:
            try:
                # "--" 结束选项解析：匹配串本身以 "--" 开头（macOS pkill 会误判）
                subprocess.run(
                    ["pkill", "-f", "--",
                     f"--user-data-dir={settings.data_dir}"],
                    capture_output=True,
                    timeout=10,
                )
            except Exception:
                pass  # pkill missing / already dead — fall through to reset
            if self._executor is not None:
                try:
                    self._executor.submit(self._reset_on_owner).result(timeout=20)
                    return
                except Exception:
                    pass  # owner thread still wedged: abandon it
            with self._executor_lock:
                old, self._executor = self._executor, None
                self._owner_thread_id = None
                self._pw, self.context, self.page = None, None, None
                self._generation += 1
            if old is not None:
                old.shutdown(wait=False)
        finally:
            self._hang_lock.release()

    # -- owner-thread-only internals -------------------------------------

    def _ensure_started_on_owner(self):
        """(owner thread) Launch the persistent context if not running yet."""
        if self.page is not None:
            return  # already started — simple idempotency guard
        self._pw = sync_playwright().start()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.context = self._pw.chromium.launch_persistent_context(
            str(settings.data_dir),
            headless=settings.headless,
            accept_downloads=True,
            viewport={"width": settings.viewport_width, "height": settings.viewport_height},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        self.page = (
            self.context.pages[0] if self.context.pages else self.context.new_page()
        )
        self.page.goto(TONGYI_URL, wait_until="domcontentloaded")
        self.page.wait_for_timeout(2500)  # 让头部「登录」按钮/头像渲染

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

    def _page_work(self, fn, *, relaunch_on_zombie: bool,
                  timeout: float = OP_TIMEOUT_WORK):
        """(any thread) Run ``fn(page)`` on the owner thread, with recovery.

        When the Chromium window was closed under us, the dead session is
        reset and the whole operation retried exactly ONCE on a freshly
        launched browser; a second failure propagates to the caller.
        """

        gen = self._generation

        def _attempt():
            # 排队期间会话可能已被 hang watchdog 废弃：拒绝在旧线程上操作
            if gen != self._generation:
                raise PlaywrightError("browser session reset by watchdog")
            self._ensure_started_on_owner()
            return fn(self.page)

        try:
            return self._submit(_attempt, timeout=timeout)
        except PlaywrightError as exc:
            if not relaunch_on_zombie or not is_zombie_error(exc):
                raise
            # Zombie session: drop it, relaunch once, re-run fn from scratch.
            self._submit(self._reset_on_owner, timeout=OP_TIMEOUT_START)
            return self._submit(_attempt, timeout=timeout)

    # ------------------------------------------------------------------
    # thread-safe public API (each submits its work to the owner thread)
    # ------------------------------------------------------------------
    def start(self):
        """Launch the persistent browser and open tongyi.  Idempotent.

        浏览器已启动时立即返回（跨线程读 page 引用，仅作快速判空），避免在
        owner 忙于分析时排队。
        """
        if self.page is not None:
            return
        self._submit(self._ensure_started_on_owner, timeout=OP_TIMEOUT_START)

    def ensure_started(self):
        """Start the browser if it is not running yet (lazy entry point)."""
        self.start()

    def is_logged_in(self) -> bool | None:
        """登录态三态：True/False 确知；None=浏览器忙暂不可查（返回缓存）。

        - 浏览器未启动 → False（owner 线程上空跑一次，不拉起 Chromium）；
        - owner 正忙于分析等长任务（排队超时）→ None，绝不杀浏览器、不打断分析；
        - evaluate 真挂死（开始执行后超时）→ watchdog 恢复，返回 None。

        只评估当前页，绝不导航（登录 iframe 流程进行中不能重载页面）。
        每次确知结论都写入 ``_login_cache``，忙的时候由调用方读缓存。
        """

        def _check():
            if self.page is None:  # not started yet -> "not logged in"
                return False
            try:
                result = False
                for _ in range(4):  # 头部未渲染时短等重试（约 3s）
                    state = self.page.evaluate(LOGIN_STATE_JS)
                    if state == "logged_in":
                        result = True
                        break
                    if state in ("logged_out", "login_modal"):
                        result = False
                        break
                    self.page.wait_for_timeout(1000)
                self._login_cache = result
                return result
            except PlaywrightError as exc:
                if is_zombie_error(exc):
                    # Window closed under us: drop the dead session, but do
                    # NOT relaunch — a status poll must never open a window.
                    self._reset_on_owner()
                return False
            except Exception:
                return False

        try:
            return self._submit(_check, timeout=OP_TIMEOUT_STATUS)
        except OwnerBusyError:
            return None  # owner 在忙正常长任务：调用方读缓存/稍后再查
        except Exception:
            return None  # 真挂死已由 watchdog 恢复，状态此刻不可知

    def cached_logged_in(self) -> bool | None:
        """最近一次确知的登录态（不触碰 owner 线程，分析中也能秒回）。"""
        return self._login_cache

    def login_start(self, phone: str) -> dict:
        """Open the in-page login modal and request an SMS code (owner thread)."""
        return self.run_on_page(
            lambda page: qianwen_login.login_start(page, phone),
            timeout=OP_TIMEOUT_LOGIN,
        )

    def login_verify(self, code: str) -> dict:
        """Submit the SMS code and wait for login success (owner thread)."""
        out = self.run_on_page(
            lambda page: qianwen_login.login_verify(page, code),
            timeout=OP_TIMEOUT_LOGIN,
        )
        if isinstance(out, dict) and out.get("status") == "ok":
            self._login_cache = True
        return out

    def open_for_login(self):
        """Open the qianwen home page (escape hatch for headed first-time login)."""

        def _goto(page):
            page.bring_to_front()
            page.goto(TONGYI_URL, wait_until="domcontentloaded")

        self._page_work(
            _goto, relaunch_on_zombie=True, timeout=OP_TIMEOUT_START
        )

    def run_on_page(self, fn, timeout: float = OP_TIMEOUT_WORK):
        """Run ``fn(page)`` on the owner thread and return its result.

        The browser is started on demand and, if the window was closed in
        the meantime, relaunched with a single retry; ``fn``'s return value
        or exception is propagated back to the calling thread.
        """
        return self._page_work(fn, relaunch_on_zombie=True, timeout=timeout)


browser = BrowserSession()  # singleton; nothing runs until first use
