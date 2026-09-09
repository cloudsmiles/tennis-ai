"""通义千问登录态：查询 + 网页内手机号/短信验证码登录。

浏览器全程在后端无头运行（不弹独立窗口），终端用户只在我们自己的网页里
输入手机号和验证码。浏览器操作经单工作线程 marshal（见 app/llm/browser.py）。

登录态查询三态：logged_in=true/false 确知；busy=true 表示浏览器正在执行
分析等长任务、状态暂不可查（此时返回最近一次确知的缓存值），前端稍候重试，
绝不因查询而打断正在进行的分析。
"""
from fastapi import APIRouter, Query
from pydantic import BaseModel

from ..llm.browser import OwnerBusyError, browser

router = APIRouter()

BUSY_MESSAGE = "浏览器忙，正在自动恢复，请稍后重试"


class PhoneIn(BaseModel):
    phone: str


class CodeIn(BaseModel):
    code: str


@router.get("/api/llm/login-status")
def login_status(ensure: bool = Query(False)):
    """登录状态：{logged_in, busy}。

    ensure=false（默认，轻量轮询）：浏览器未启动直接 false，不拉起 Chromium；
    ensure=true（打开账号面板）：先确保浏览器启动再按持久 cookie 查真实态。
    owner 线程忙于分析时 busy=true，logged_in 取最近缓存（可能为 false），
    调用方应稍后重试而不是弹登录框。
    """
    busy = False
    if ensure:
        try:
            browser.ensure_started()
        except OwnerBusyError:
            busy = True  # 冷启动排队：浏览器确实在忙，不报错
        except Exception:
            busy = True
    status = browser.is_logged_in()
    if status is None:
        busy = True
        cached = browser.cached_logged_in()
        return {"logged_in": bool(cached), "busy": True}
    return {"logged_in": status, "busy": busy}


@router.post("/api/llm/login/start")
def login_start(body: PhoneIn):
    """填手机号并请求短信验证码。

    返回 {"status": code_sent | already_logged_in | captcha | error, ...}。
    """
    try:
        return browser.login_start(body.phone)
    except Exception:
        return {"status": "error", "message": BUSY_MESSAGE}


@router.post("/api/llm/login/verify")
def login_verify(body: CodeIn):
    """提交短信验证码完成登录。返回 {"status": ok | captcha | error, ...}。"""
    try:
        return browser.login_verify(body.code)
    except Exception:
        return {"status": "error", "message": BUSY_MESSAGE}
