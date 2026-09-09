"""一次性诊断（第二轮）：探明 qianwen 改版后的图片上传入口与消息 DOM。

在已登录的持久 profile 上：列出输入区所有按钮、点「+」与图片按钮观察
input[type=file] 的挂载方式，但不发送消息。
"""
import json

from app.llm.browser import browser
from app.llm.selectors import TONGYI_URL

_JS_BUTTONS = r"""
() => [...document.querySelectorAll('button, [role=button]')].map((e) => ({
  aria: e.getAttribute('aria-label'),
  text: (e.innerText || '').trim().slice(0, 20),
  testid: e.getAttribute('data-testid'),
  visible: e.offsetParent !== null,
})).filter((b) => b.visible && (b.aria || b.text))
"""

_JS_INPUT = r"""
() => [...document.querySelectorAll('input[type=file]')].map((e) => ({
  accept: e.accept, multiple: e.multiple,
  visible: e.offsetParent !== null,
  cls: (e.className || '').toString().slice(0, 60),
}))
"""


def probe(page):
    out = {"steps": []}
    page.goto(TONGYI_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(6000)

    ce = page.query_selector_all("div[contenteditable='true']")
    out["contenteditable"] = [
        (e.get_attribute("class") or "")[:100] for e in ce
    ]
    out["buttons_initial"] = page.evaluate(_JS_BUTTONS)
    out["file_inputs_initial"] = page.evaluate(_JS_INPUT)

    # 找「+」/添加类按钮并点击
    candidates = page.evaluate(
        """() => [...document.querySelectorAll('button,[role=button]')]
           .filter(e => e.offsetParent !== null)
           .map((e, i) => ({i, aria: e.getAttribute('aria-label'),
                           text: (e.innerText||'').trim().slice(0,10)}))"""
    )
    out["all_clickables"] = candidates

    plus = page.query_selector("button:has-text('+'), [role=button]:has-text('+')")
    if plus:
        plus.click()
        page.wait_for_timeout(1200)
        out["after_plus_file_inputs"] = page.evaluate(_JS_INPUT)
        out["after_plus_menu"] = page.evaluate(
            """() => [...document.querySelectorAll('[role=menuitem],li,div')]
               .map(e => (e.innerText||'').trim())
               .filter(t => t && t.length < 10 &&
                 /图片|文件|照片|上传|相册|图片/.test(t)).slice(0, 12)"""
        )
        page.screenshot(path="/tmp/qianwen_plus.png")
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)

    # 输入框附近含图片/相册语义的按钮（aria 或 title）
    imgbtns = page.evaluate(
        """() => [...document.querySelectorAll('button,[role=button]')]
           .filter(e => { const s = (e.getAttribute('aria-label')||'') +
             (e.getAttribute('title')||'') + (e.innerText||'');
             return /图片|相册|照片|上传|image|photo/i.test(s); })
           .map(e => ({aria: e.getAttribute('aria-label'),
                       title: e.getAttribute('title'),
                       text: (e.innerText||'').trim().slice(0,10)}))"""
    )
    out["image_semantic_buttons"] = imgbtns
    return out


if __name__ == "__main__":
    print(json.dumps(browser.run_on_page(probe), ensure_ascii=False, indent=2))
