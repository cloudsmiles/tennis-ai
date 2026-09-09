"""Browser owner-thread marshaling — window-free, fully offline guarantees.

Playwright's sync API is thread-bound, so ``BrowserSession`` must marshal
every operation onto its single lazily-created owner thread.  These tests
prove the marshaling WITHOUT ever launching Chromium (no window, no network):
importing the modules forces nothing, ``is_logged_in()`` stays False, and
``_submit`` runs arbitrary callables on the owner thread, returning their
result (or re-raising their exception) to the calling thread.  The zombie
(closed-window) recovery is exercised against FAKE pages — still no browser.
"""
import subprocess
import sys
import threading
import types
from pathlib import Path

import pytest
from playwright.sync_api import Error as PlaywrightError

from app.llm.browser import BrowserSession, browser, is_zombie_error

BACKEND_DIR = Path(__file__).resolve().parent.parent


def test_import_forces_no_executor_or_browser():
    """A fresh interpreter import must stay completely dormant.

    Runs in a subprocess so it observes a pristine singleton regardless of
    what earlier tests in this process may have started.
    """
    code = (
        "import app.llm.browser as bm\n"
        "import app.llm.tongyi as tm\n"
        "assert bm.browser.page is None, 'page must start as None'\n"
        "assert bm.browser.context is None, 'context must start as None'\n"
        "assert bm.browser._executor is None, 'import must not spawn the executor'\n"
        "assert callable(tm.analyze_image) and tm.NotLoggedInError\n"
        "print('DORMANT-OK')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "DORMANT-OK" in proc.stdout


def test_is_logged_in_false_without_browser():
    """Fast path: not started -> False, with NO page work and NO window."""
    assert browser.is_logged_in() is False
    # still dormant: the probe must not have launched anything
    assert browser.page is None
    assert browser.context is None


def test_submit_marshals_onto_owner_thread():
    """``_submit`` runs fn on the owner thread and returns its result."""
    assert browser._submit(lambda: 6 * 7) == 42

    owner_name = browser._submit(lambda: threading.current_thread().name)
    assert owner_name != threading.current_thread().name
    assert "browser-owner" in owner_name  # our executor's single worker


def test_submit_propagates_exceptions():
    """Exceptions raised inside fn re-raise in the calling thread."""

    def boom():
        raise RuntimeError("boom-on-owner-thread")

    with pytest.raises(RuntimeError, match="boom-on-owner-thread"):
        browser._submit(boom)


def test_status_queued_behind_long_task_is_busy_without_kill(monkeypatch):
    """分析等长任务占用 owner 时：状态查询超时返回 None（忙），且绝不能
    触发浏览器强杀——否则会把正在正常进行的分析杀掉。"""
    import app.llm.browser as bm
    import time

    monkeypatch.setattr(bm, "OP_TIMEOUT_STATUS", 0.5)
    s = BrowserSession()
    s.page = object()  # 绕过"未启动"快路径，让 _check 真的排队
    release = threading.Event()
    killed = []
    monkeypatch.setattr(s, "_recover_from_hang", lambda: killed.append(1))

    long_task = s._ensure_executor().submit(lambda: release.wait(5))
    time.sleep(0.2)  # 等长任务占住 owner
    try:
        assert s.is_logged_in() is None
        assert killed == []  # 排队超时 ≠ 挂死，不得恢复/杀进程
    finally:
        release.set()
    assert long_task.result(5) is True  # 长任务安然跑完


def test_submit_timeout_triggers_recovery(monkeypatch):
    """A wedged owner-thread call raises after the timeout AND triggers the
    force-kill/recover path once (regression: evaluate used to hang forever,
    freezing login-status/login/analysis requests behind it)."""
    import concurrent.futures
    import time

    s = BrowserSession()  # own executor, never touched again after this test
    recovered = []
    monkeypatch.setattr(
        s, "_recover_from_hang", lambda: recovered.append("recover")
    )
    with pytest.raises(concurrent.futures.TimeoutError):
        s._submit(lambda: time.sleep(1.0), timeout=0.2)
    assert recovered == ["recover"]


def test_is_zombie_error_classification():
    """Only closed-target Playwright errors count as zombies."""
    assert is_zombie_error(
        PlaywrightError("Target page, context or browser has been closed")
    )
    assert is_zombie_error(PlaywrightError("Connection closed"))
    assert not is_zombie_error(PlaywrightError("Timeout 3000ms exceeded."))
    assert not is_zombie_error(
        RuntimeError("Target page, context or browser has been closed")
    )


class _FakePageDead:
    """A page whose every operation fails like a closed window."""

    def __init__(self, log):
        self._log = log

    def poke(self):
        self._log.append("dead")
        raise PlaywrightError("Target page, context or browser has been closed")


class _FakePageLive:
    def __init__(self, log):
        self._log = log

    def poke(self):
        self._log.append("live")
        return "page-alive"


def _stub_session(log, page_factory):
    """A BrowserSession whose 'launch' installs fake pages (no real browser)."""
    s = BrowserSession()

    def fake_ensure(_self):
        if _self.page is None:
            _self._pw = types.SimpleNamespace(stop=lambda: log.append("pw-stop"))
            _self.page = page_factory()

    s._ensure_started_on_owner = types.MethodType(fake_ensure, s)
    return s


def test_run_on_page_recovers_from_closed_window():
    """One closed-window failure -> reset + single relaunch retry -> success."""
    log = []
    first = {"used": False}

    def page_factory():
        if not first["used"]:
            first["used"] = True
            return _FakePageDead(log)
        return _FakePageLive(log)

    s = _stub_session(log, page_factory)
    assert s.run_on_page(lambda page: page.poke()) == "page-alive"
    assert log == ["dead", "pw-stop", "live"]  # exactly one relaunch


def test_run_on_page_propagates_after_failed_relaunch():
    """A zombie error that survives the single retry propagates to the caller."""
    log = []

    s = _stub_session(log, lambda: _FakePageDead(log))
    with pytest.raises(PlaywrightError):
        s.run_on_page(lambda page: page.poke())
    assert log == ["dead", "pw-stop", "dead"]  # attempt, reset, one retry
