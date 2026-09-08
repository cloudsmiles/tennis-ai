"""Tongyi web automation: single-image analysis flow + serial queue.

This is the integration layer that drives the persistent browser session
(``llm.browser``) to talk to tongyi.  All UI locators come from
``llm.selectors`` so a site redesign only requires updating that file.

Playwright's sync API is thread-bound, so the entire page conversation runs
inside ONE ``browser.run_on_page`` call — i.e. on the browser-owner thread —
no matter which thread called ``analyze_image`` (JobManager worker, FastAPI
request thread, test runner, ...).
"""
import random
import threading
import time
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError

from ..config import settings
from .browser import browser, is_zombie_error
from .parse import parse_analysis
from .prompts import analysis_prompt
from .selectors import SELECTORS, TONGYI_URL


class NotLoggedInError(RuntimeError):
    """The tongyi session has no logged-in user; manual login is required."""


class LLMParseError(RuntimeError):
    """The tongyi reply could not be parsed as JSON.

    ``raw`` keeps the original reply text so the pipeline can store it as the
    action's ``raw_reply`` and the UI can still show the coach's prose
    (spec §4: 解析失败时把原始文本一并保存，前端仍可展示原文).
    """

    def __init__(self, raw: str):
        super().__init__("tongyi reply is not parseable as json")
        self.raw = raw


def _wait_reply(page, timeout_s: float = 180) -> str:
    """Wait for the answer to finish generating, then return its text.

    The "stop generating" button appears when the model starts replying and
    detaches when it is done; the reply is the last assistant block.
    """
    try:
        page.wait_for_selector(SELECTORS["stop_button"], timeout=15000)
    except Exception:
        pass  # generation may already be over before we started watching
    page.wait_for_selector(
        SELECTORS["stop_button"], state="detached", timeout=timeout_s * 1000
    )
    blocks = page.query_selector_all(SELECTORS["reply_block"])
    return blocks[-1].inner_text() if blocks else ""


def _require_login(page) -> None:
    """(owner thread) Raise NotLoggedInError unless the chat input is present.

    Same 3s probe ``browser.is_logged_in`` uses.  A closed-window error is
    re-raised untouched so ``run_on_page``'s zombie recovery can relaunch.
    """
    try:
        page.wait_for_selector(SELECTORS["chat_input"], timeout=3000)
    except PlaywrightError as exc:
        if is_zombie_error(exc):
            raise  # window closed: let run_on_page relaunch and retry
        raise NotLoggedInError(
            "tongyi not logged in; call open_for_login() first"
        ) from exc


def analyze_image(image_path: Path, stroke_type: str | None = None) -> dict:
    """One full tongyi conversation: new chat -> upload -> prompt -> parse.

    The whole goto→upload→fill→click→wait→grab-reply sequence runs in ONE
    ``browser.run_on_page`` call (on the browser-owner thread); the result
    — or exception, e.g. ``NotLoggedInError`` — is propagated back to the
    calling thread.

    stroke_type（手动模式下用户标注的 forehand/backhand/serve）会写进 prompt，
    让模型据此点评；为 None 时由模型自行分类。

    Raises ``NotLoggedInError`` when the browser session is not logged in;
    raises ``LLMParseError`` (carrying the raw reply in ``.raw``) when the
    reply is unparseable.
    """
    browser.ensure_started()
    prompt = analysis_prompt(stroke_type)

    def _conversation(page):
        # NOTE: this runs on the browser-owner thread — drive the raw `page`
        # here; calling the browser.* public API would (harmlessly but
        # pointlessly) marshal straight back onto this same thread.
        _require_login(page)
        page.goto(TONGYI_URL)  # fresh conversation
        page.wait_for_selector(SELECTORS["chat_input"], timeout=30000)
        page.set_input_files(SELECTORS["upload_button"], str(image_path))
        page.wait_for_timeout(2000)  # let the upload settle
        page.fill(SELECTORS["chat_input"], prompt)
        page.click(SELECTORS["send_button"])
        text = _wait_reply(page)
        try:
            return parse_analysis(text)
        except ValueError:
            # Never lose the coach's prose: wrap as LLMParseError so the raw
            # reply travels with the exception back through
            # run_on_page/submit to the pipeline (stored as raw_reply).
            raise LLMParseError(text)

    return browser.run_on_page(_conversation)


class LLMSerialQueue:
    """Serial (lock-guarded) queue that rate-limits tongyi calls."""

    def __init__(self):
        self._lock = threading.Lock()

    def submit(self, image_path, stroke_type: str | None = None) -> dict:
        """Analyze one image; retries transient failures, keeps calls serial."""
        with self._lock:
            last_error = None
            for attempt in range(settings.llm_max_retries + 1):
                try:
                    result = analyze_image(Path(image_path), stroke_type)
                    # cool-down between consecutive LLM calls (held under the
                    # lock on purpose: it also paces the next queued task)
                    time.sleep(
                        random.uniform(
                            settings.llm_min_delay_s, settings.llm_max_delay_s
                        )
                    )
                    return result
                except NotLoggedInError:
                    raise  # retrying cannot fix a missing login
                except LLMParseError as exc:
                    # Keep the queue's existing retry pacing for parse
                    # failures (a fresh conversation may return valid JSON),
                    # but once the attempts are exhausted the LLMParseError
                    # itself — raw reply attached — must reach the caller
                    # unwrapped; the generic RuntimeError below would
                    # suppress its type (and lose .raw).
                    last_error = exc
                    if attempt < settings.llm_max_retries:
                        time.sleep(2.0)
                    else:
                        raise
                except Exception as exc:
                    last_error = exc
                    if attempt < settings.llm_max_retries:
                        time.sleep(2.0)
            raise RuntimeError(
                f"llm analysis failed after "
                f"{settings.llm_max_retries + 1} attempts: {last_error}"
            ) from last_error


llm_queue = LLMSerialQueue()  # singleton; browser stays unstarted until used
