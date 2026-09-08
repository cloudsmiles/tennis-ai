"""Tongyi web automation: single-image analysis flow + serial queue.

This is the integration layer that drives the persistent browser session
(``llm.browser``) to talk to tongyi.  All UI locators come from
``llm.selectors`` so a site redesign only requires updating that file.
"""
import random
import threading
import time
from pathlib import Path

from ..config import settings
from .browser import browser
from .parse import parse_analysis
from .prompts import ANALYSIS_PROMPT
from .selectors import SELECTORS, TONGYI_URL


class NotLoggedInError(RuntimeError):
    """The tongyi session has no logged-in user; manual login is required."""


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


def analyze_image(image_path: Path) -> dict:
    """One full tongyi conversation: new chat -> upload -> prompt -> parse.

    Raises ``NotLoggedInError`` when the browser session is not logged in;
    raises ValueError (from ``parse_analysis``) when the reply is unparseable.
    """
    browser.ensure_started()
    if not browser.is_logged_in():
        raise NotLoggedInError("tongyi not logged in; call open_for_login() first")

    page = browser.page
    page.goto(TONGYI_URL)  # fresh conversation
    page.wait_for_selector(SELECTORS["chat_input"], timeout=30000)
    page.set_input_files(SELECTORS["upload_button"], str(image_path))
    page.wait_for_timeout(2000)  # let the upload settle
    page.fill(SELECTORS["chat_input"], ANALYSIS_PROMPT)
    page.click(SELECTORS["send_button"])
    text = _wait_reply(page)
    return parse_analysis(text)


class LLMSerialQueue:
    """Serial (lock-guarded) queue that rate-limits tongyi calls."""

    def __init__(self):
        self._lock = threading.Lock()

    def submit(self, image_path) -> dict:
        """Analyze one image; retries transient failures, keeps calls serial."""
        with self._lock:
            last_error = None
            for attempt in range(settings.llm_max_retries + 1):
                try:
                    result = analyze_image(Path(image_path))
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
                except Exception as exc:
                    last_error = exc
                    if attempt < settings.llm_max_retries:
                        time.sleep(2.0)
            raise RuntimeError(
                f"llm analysis failed after "
                f"{settings.llm_max_retries + 1} attempts: {last_error}"
            ) from last_error


llm_queue = LLMSerialQueue()  # singleton; browser stays unstarted until used
