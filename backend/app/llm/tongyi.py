"""Qianwen web automation: single-image analysis flow + serial queue.

Drives the persistent headless browser session (``llm.browser``) on the
2026 qianwen.com site:

- 输入框是 ``div[contenteditable='true']``（不是 textarea）；
- 图片走「添加附件」按钮的两级菜单（菜单项「上传图片」触发原生文件选择器）；
- 生成中显示 ``button[aria-label='停止回答']``，完成后卸载；
- 回复正文在 ``.answer-common-card .qk-markdown``，完成态带 qk-markdown-complete；
- 阿里风控可能弹出滑块验证，此时抛 :class:`CaptchaRequiredError`。

所有定位常量集中在 ``llm.selectors``。整个对话流程在一次
``browser.run_on_page`` 内跑完（browser-owner 线程），sync API 的线程绑定
由此满足。
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
from .selectors import (
    CAPTCHA_JS,
    LOGIN_STATE_JS,
    REPLY_JS,
    SELECTORS as S,
    TONGYI_URL,
)


class NotLoggedInError(RuntimeError):
    """The qianwen session has no logged-in user; in-page login is required."""


class CaptchaRequiredError(RuntimeError):
    """qianwen popped a slider / security-check challenge the bot cannot pass."""


class LLMParseError(RuntimeError):
    """The qianwen reply could not be parsed as JSON.

    ``raw`` keeps the original reply text so the pipeline can store it as the
    action's ``raw_reply`` and the UI can still show the coach's prose.
    """

    def __init__(self, raw: str):
        super().__init__("qianwen reply is not parseable as json")
        self.raw = raw


def _require_login(page) -> None:
    """(owner thread) Raise unless qianwen is logged in.

    The contenteditable input exists even when logged out, so login state is
    read from the header「登录」button via ``LOGIN_STATE_JS``.  A closed-target
    error is re-raised untouched so ``run_on_page``'s zombie recovery runs.
    """
    try:
        page.wait_for_selector(S["chat_input"], timeout=30000)
        for _ in range(5):
            state = page.evaluate(LOGIN_STATE_JS)
            if state == "logged_in":
                browser._login_cache = True  # 分析中状态查询走缓存，不排队
                return
            if state in ("logged_out", "login_modal"):
                raise NotLoggedInError("qianwen not logged in")
            page.wait_for_timeout(1000)
        raise NotLoggedInError("qianwen login state unknown")
    except PlaywrightError as exc:
        if is_zombie_error(exc):
            raise  # window closed: let run_on_page relaunch and retry
        raise NotLoggedInError("qianwen not logged in") from exc


def _upload_image(page, image_path: Path) -> None:
    """(owner thread) 添加附件 → 上传图片；兼容文件选择器与隐藏 input 两种挂载。"""
    page.click(S["attach_button"])
    page.wait_for_timeout(700)
    try:
        with page.expect_file_chooser(timeout=4000) as fc:
            page.get_by_text(S["upload_image_item"], exact=True).first.click()
        fc.value.set_files(str(image_path))
    except Exception:
        # 部分版本在点菜单项后挂载隐藏 <input type=file>，不弹原生选择器
        page.get_by_text(S["upload_image_item"], exact=True).first.click()
        page.wait_for_timeout(700)
        inp = page.query_selector("input[type=file]")
        if inp is None:
            raise RuntimeError("找不到千问图片上传入口")
        inp.set_input_files(str(image_path))
    page.wait_for_timeout(2500)  # 等附件上传并出现预览


def _wait_reply(page, timeout_s: float = 180) -> str:
    """(owner thread) 等生成结束，返回最后一张回复卡片的文本。

    完成判据（同时满足）：停止按钮已消失 + 回复 markdown 带 complete 态 +
    文本连续两次轮询不再增长。滑块弹窗立即抛 :class:`CaptchaRequiredError`。
    """
    deadline = time.monotonic() + timeout_s
    saw_stop = False
    last_text, stable = "", 0
    while time.monotonic() < deadline:
        page.wait_for_timeout(1500)
        if page.locator(S["stop_button"]).count() > 0:
            saw_stop = True
            last_text, stable = "", 0
            continue
        if page.evaluate(CAPTCHA_JS):
            raise CaptchaRequiredError("qianwen captcha required")
        reply = page.evaluate(REPLY_JS)
        text, done = reply.get("text", ""), bool(reply.get("done"))
        if done and text:
            stable = stable + 1 if text == last_text else 1
            last_text = text
            # saw_stop 仅用于观察；回复极快错过停止按钮时，complete+稳定也成立
            if stable >= 2:
                return text
    raise TimeoutError("等待千问回复超时")


def analyze_image(image_path: Path, stroke_type: str | None = None) -> dict:
    """One full qianwen conversation: fresh chat -> upload -> prompt -> parse.

    The whole goto→upload→type→send→wait→grab-reply sequence runs in ONE
    ``browser.run_on_page`` call (browser-owner thread).

    stroke_type（手动模式用户标注的 forehand/backhand/serve）写进 prompt；
    None 时由模型自行分类。

    Raises ``NotLoggedInError`` / ``CaptchaRequiredError`` / ``LLMParseError``
    （后者在 ``.raw`` 携带原始回复）。
    """
    browser.ensure_started()
    prompt = analysis_prompt(stroke_type)

    def _conversation(page):
        # Runs on the browser-owner thread — drive the raw `page` here directly.
        page.goto(TONGYI_URL, wait_until="domcontentloaded")
        _require_login(page)
        if page.evaluate(CAPTCHA_JS):
            raise CaptchaRequiredError("qianwen captcha required")

        _upload_image(page, image_path)

        box = page.locator(S["chat_input"]).first
        box.click()
        page.keyboard.insert_text(prompt)
        page.wait_for_timeout(400)

        page.click(S["send_button"])
        text = _wait_reply(page)
        try:
            return parse_analysis(text)
        except ValueError:
            # Never lose the coach's prose: carry the raw reply back so the
            # pipeline can store it as raw_reply.
            raise LLMParseError(text)

    return browser.run_on_page(_conversation)


class LLMSerialQueue:
    """Serial (lock-guarded) queue that rate-limits qianwen calls."""

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
                except (NotLoggedInError, CaptchaRequiredError):
                    raise  # 登录缺失/滑块：重试无意义，直接上抛
                except LLMParseError as exc:
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
