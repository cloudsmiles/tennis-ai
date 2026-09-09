"""站内手机号 + 短信验证码登录千问（驱动无头页面里的 Havana 登录 iframe）。

登录表单在跨域 iframe ``passport.qianwen.com/havanaone/login/login.htm`` 中，
主文档只负责弹出它。本模块全部函数都在 browser-owner 线程上运行（经由
``browser.run_on_page``），入参是 Playwright ``Page``。

两步式（对应两个 HTTP 接口）：
- :func:`login_start`：打开登录模态 → 填手机号 → 勾协议 → 点「获取验证码」；
- :func:`login_verify`：填短信验证码 → 点「登录」→ 轮询登录成功。

两步之间浏览器页面与 iframe 由持久单例保持。阿里风控可能在任一步弹出滑块或
图形验证码（iframe 内隐藏的「图片验证码」input 即为此设），此时返回
``{"status": "captcha"}``，由上层告知用户（第三方风控，无法保证全自动通过）。
"""
import re

from playwright.sync_api import Error as PlaywrightError

from .selectors import (
    CAPTCHA_JS,
    LOGIN_FRAME_URL_PART,
    LOGIN_SELECTORS as LS,
    LOGIN_STATE_JS,
    TONGYI_URL,
)

_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")
_FRAME_WAIT_MS = 15000
_RESULT_WAIT_S = 4  # 点「获取验证码/登录」后观察结果的时长


def _login_frame(page, timeout_ms=_FRAME_WAIT_MS):
    """等待登录 iframe 挂载并返回其 Frame；超时/不存在返回 None。"""
    try:
        page.wait_for_function(
            "() => [...document.querySelectorAll('iframe')].some(f => "
            "(f.src || '').includes('passport.qianwen.com/havanaone'))",
            timeout=timeout_ms,
        )
    except Exception:
        return None
    for fr in page.frames:
        if LOGIN_FRAME_URL_PART in (fr.url or ""):
            return fr
    return None


def _state(page) -> str:
    try:
        return page.evaluate(LOGIN_STATE_JS)
    except Exception:
        return "unknown"


def _frame_captcha(frame) -> bool:
    """iframe 内是否出现图形验证码 input（可见）或滑块/验证文案。"""
    try:
        box = frame.locator(LS["image_code"]).first
        if box.count() and box.is_visible():
            return True
    except Exception:
        pass
    try:
        text = frame.locator("body").inner_text(timeout=2000)
    except Exception:
        text = ""
    return any(p in text for p in ("拖动", "滑块", "滑动", "安全验证", "图片验证码"))


def _page_captcha(page) -> bool:
    try:
        return bool(page.evaluate(CAPTCHA_JS))
    except Exception:
        return False


_ERROR_KW = (
    "验证码不正确",
    "验证码错误",
    "验证码已过期",
    "验证码失效",
    "图形验证",
    "操作频繁",
    "频繁",
    "手机号格式",
    "手机号不正确",
    "不正确",
    "错误",
)


def _frame_error(frame) -> str:
    try:
        text = frame.locator("body").inner_text(timeout=2000)
    except Exception:
        return ""
    for kw in _ERROR_KW:
        if kw in text:
            return kw
    return ""


def _open_modal(page):
    """确保登录 iframe 已打开；返回 Frame 或 None。"""
    state = _state(page)
    if state == "login_modal":
        return _login_frame(page)
    if state in ("logged_out", "unknown"):
        page.goto(TONGYI_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
    # 点击右上角文本恰为「登录」的叶子按钮
    clicked = page.evaluate(
        r"""() => {
          const cands = [...document.querySelectorAll('button,a,[role=button]')]
            .filter(e => e.offsetParent !== null && e.children.length === 0
              && (e.innerText || '').trim() === '登录');
          if (!cands.length) return false;
          cands.sort((a, b) => {
            const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
            return ra.y - rb.y || rb.x - ra.x;
          });
          cands[0].click();
          return true;
        }"""
    )
    if not clicked:
        return None
    return _login_frame(page)


def _agree(frame) -> None:
    """勾选用户协议复选框（自定义样式常盖住真实 input，用派发 click 最稳）。"""
    cb = frame.locator(LS["agree"]).first
    if not cb.count():
        return
    try:
        if cb.is_checked():
            return
    except Exception:
        pass
    try:
        cb.dispatch_event("click")
    except Exception:
        try:
            cb.click(force=True)
        except Exception:
            pass


def login_start(page, phone: str) -> dict:
    """打开登录模态、填手机号并请求短信验证码。结果状态见模块文档。"""
    phone = (phone or "").strip()
    if not _PHONE_RE.match(phone):
        return {"status": "error", "message": "请输入正确的 11 位手机号"}
    if _state(page) == "logged_in":
        return {"status": "already_logged_in"}

    frame = _open_modal(page)
    if frame is None:
        return {"status": "error", "message": "未能打开千问登录窗口，请稍后重试"}

    frame.locator(LS["phone"]).fill(phone)
    _agree(frame)
    frame.get_by_text(LS["get_code"], exact=True).first.click()

    # 观察「获取验证码」结果：风控弹窗 / 倒计时已开始 / 行内报错
    for _ in range(_RESULT_WAIT_S * 2):
        page.wait_for_timeout(500)
        if _frame_captcha(frame) or _page_captcha(page):
            return {
                "status": "captcha",
                "message": "千问要求完成滑块/图形安全验证，请稍后重试或在服务器上有头登录一次",
            }
        try:
            btn_text = frame.get_by_text(
                re.compile(r"\d+\s*s|重新获取|重新发送"), exact=False
            ).first
            if btn_text.count():
                return {"status": "code_sent"}
        except Exception:
            pass
        err = _frame_error(frame)
        if err:
            return {"status": "error", "message": f"获取验证码失败：{err}"}
    # 拿不到明确信号时乐观返回（部分版本按钮无倒计时文案）
    return {"status": "code_sent"}


def login_verify(page, code: str) -> dict:
    """填入短信验证码并提交，轮询登录结果。"""
    code = re.sub(r"\D", "", code or "")
    if len(code) != 6:
        return {"status": "error", "message": "请输入 6 位短信验证码"}

    frame = _login_frame(page, timeout_ms=6000)
    if frame is None:
        # iframe 已消失：很可能已经登录成功
        return (
            {"status": "ok"}
            if _state(page) == "logged_in"
            else {"status": "error", "message": "登录窗口已关闭，请重新获取验证码"}
        )

    frame.locator(LS["code"]).fill(code)
    frame.get_by_text(LS["submit"], exact=True).first.click()

    # 提交成功会 topRedirect 回 qianwen.com（iframe 卸载、页面重载），导航
    # 瞬间 evaluate 可能抛 Execution context destroyed —— 当作未完成继续轮询。
    for _ in range(24):  # 约 12s
        page.wait_for_timeout(500)
        try:
            if _login_frame(page, timeout_ms=500) is None and _state(page) == "logged_in":
                return {"status": "ok"}
        except PlaywrightError:
            continue
        try:
            if _frame_captcha(frame):
                return {
                    "status": "captcha",
                    "message": "千问要求完成滑块/图形安全验证，请稍后重试或在服务器上有头登录一次",
                }
            err = _frame_error(frame)
            if err:
                return {"status": "error", "message": f"登录失败：{err}"}
        except PlaywrightError:
            continue
    return {"status": "error", "message": "登录未完成，请确认验证码是否正确后重试"}
