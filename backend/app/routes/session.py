"""通义千问登录态：查询 / 打开登录窗口（浏览器操作在专用工作线程上执行）。"""
from fastapi import APIRouter

from ..llm.browser import browser

router = APIRouter()


@router.get("/api/llm/login-status")
def login_status():
    return {"logged_in": browser.is_logged_in()}


@router.post("/api/llm/login")
def login():
    browser.open_for_login()
    return {"ok": True}
