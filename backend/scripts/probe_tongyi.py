"""一次性诊断：持久 profile 打开通义首页，判断登录态与选择器是否匹配。

用法（backend/ 下）：PYTHONPATH=. .venv/bin/python scripts/probe_tongyi.py
输出 /tmp/tongyi_home.png 截图与 DOM 摘要（不修改任何状态）。
"""
import json

from app.llm.browser import browser
from app.llm.selectors import SELECTORS, TONGYI_URL

_JS = r"""
() => {
  const q = (sel) => [...document.querySelectorAll(sel)].map((e) => ({
    tag: e.tagName,
    type: e.getAttribute('type'),
    testid: e.getAttribute('data-testid'),
    aria: e.getAttribute('aria-label'),
    ph: e.getAttribute('placeholder'),
    visible: e.offsetParent !== null,
    disabled: e.disabled === true,
    cls: (e.className || '').toString().slice(0, 80),
  }));
  const texts = [...document.querySelectorAll('button,a,[role=button],span,div')]
    .map((e) => (e.childElementCount === 0 ? e.textContent.trim() : ''))
    .filter((t) => t && t.length <= 12 && /登录|扫码|登入|登陆|Log\s?in|Sign\s?in/i.test(t));
  return {
    url: location.href,
    title: document.title,
    cookieNames: document.cookie.split(';').map((c) => c.split('=')[0].trim()).filter(Boolean),
    textareas: q('textarea'),
    contentEditables: document.querySelectorAll('[contenteditable="true"]').length,
    fileInputs: q('input[type=file]'),
    sendLikeButtons: q("[data-testid='send'], button[aria-label*='发送']"),
    stopButtons: q("button[aria-label*='停止']"),
    replyBlocks: document.querySelectorAll('div.message-assistant').length,
    loginishTexts: [...new Set(texts)].slice(0, 15),
  };
}
"""


def diag(page):
    page.goto(TONGYI_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(8000)
    data = page.evaluate(_JS)
    page.screenshot(path="/tmp/tongyi_home.png", full_page=False)
    try:
        page.wait_for_selector(SELECTORS["chat_input"], timeout=3000)
        data["current_chat_input_selector"] = "MATCH"
    except Exception as ex:
        data["current_chat_input_selector"] = f"NO MATCH: {str(ex)[:120]}"
    return data


if __name__ == "__main__":
    print(json.dumps(browser.run_on_page(diag), ensure_ascii=False, indent=2))
