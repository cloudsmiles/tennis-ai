"""一次性诊断（第四轮）：附件菜单 + 历史对话回复 DOM + 未登录态登录方式。"""
import json

from playwright.sync_api import sync_playwright

from app.config import settings
from app.llm.browser import browser
from app.llm.selectors import TONGYI_URL


def in_logged_in(page):
    out = {}
    page.goto(TONGYI_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(6000)

    # 1) 单击「添加附件」，看弹层/文件输入
    page.click("button[aria-label='添加附件']")
    page.wait_for_timeout(1200)
    out["attach"] = page.evaluate(
        r"""() => ({
          fileInputs: [...document.querySelectorAll("input[type=file]")]
            .map(e => ({accept: e.accept, visible: e.offsetParent !== null})),
          menu: [...document.querySelectorAll('[role=menuitem],[role=dialog] *,'
            + "[class*='menu'] *,[class*='popover'] *,[class*='dropdown'] *")]
            .map(e => (e.innerText || '').trim())
            .filter(t => t && t.length < 12)
            .filter((v, i, a) => a.indexOf(v) === i).slice(0, 20),
        })"""
    )
    page.screenshot(path="/tmp/qw_attach_menu.png")
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)

    # 2) 打开一条历史对话，定位 assistant 回复容器
    page.click("text=点奶茶")
    page.wait_for_timeout(5000)
    out["reply_dom"] = page.evaluate(
        r"""() => {
          const res = {};
          const probes = ["div.message-assistant", "[class*='assistant']",
            "[class*='message']", "article", "[class*='chat-message']",
            "[class*='msg']", "[class*='bubble']", "[class*='answer']",
            "[class*='markdown']", "[class*='md']"];
          res.counts = Object.fromEntries(probes.map(s =>
            [s, document.querySelectorAll(s).length]));
          // 以"复制/重新生成"动作按钮为锚，回溯消息容器
          const actBtns = [...document.querySelectorAll('button,[role=button]')]
            .filter(e => /复制|重新生成|重试|赞|踩/.test(
              e.getAttribute('aria-label') || ''));
          res.actionLabels = actBtns.map(e => e.getAttribute('aria-label'))
            .slice(0, 10);
          if (actBtns.length) {
            let node = actBtns[0];
            const chain = [];
            for (let k = 0; k < 8 && node; k++) {
              chain.push({tag: node.tagName, role: node.getAttribute('role'),
                cls: (node.className || '').toString().slice(0, 100),
                dataAttrs: [...node.attributes].map(a => a.name)
                  .filter(n => n.startsWith('data-')).slice(0, 6)});
              node = node.parentElement;
            }
            res.ancestorChain = chain;
          }
          return res;
        }"""
    )
    page.screenshot(path="/tmp/qw_history.png")
    return out


def logged_out():
    """全新临时 context（不动持久 profile）：看登录方式。"""
    with sync_playwright() as pw:
        browser0 = pw.chromium.launch(headless=False)
        ctx = browser0.new_context()
        page = ctx.new_page()
        page.goto(TONGYI_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(7000)
        page.screenshot(path="/tmp/qw_loggedout.png")
        # 找登录入口
        info = page.evaluate(
            r"""() => [...document.querySelectorAll('button,a,[role=button],div,span')]
              .map(e => (e.innerText || '').trim())
              .filter(t => t && t.length < 8 &&
                /登录|登入|扫码|登陆/.test(t))
              .filter((v,i,a)=>a.indexOf(v)===i).slice(0,10)"""
        )
        clicked = False
        for sel in ["button:has-text('登录')", "text=登录"]:
            try:
                page.click(sel, timeout=2500)
                clicked = True
                break
            except Exception:
                pass
        page.wait_for_timeout(3000)
        form = None
        if clicked:
            form = page.evaluate(
                r"""() => ({
                  tabs: [...document.querySelectorAll('[role=tab],button,div,span')]
                    .map(e => (e.innerText||'').trim())
                    .filter(t => t && t.length < 10 &&
                      /验证码|扫码|密码|手机号|登录/.test(t))
                    .filter((v,i,a)=>a.indexOf(v)===i).slice(0,12),
                  inputs: [...document.querySelectorAll('input')].map(e =>
                    ({type: e.type, ph: e.placeholder,
                      name: e.getAttribute('name')})).slice(0, 10),
                })"""
            )
        page.screenshot(path="/tmp/qw_login.png")
        ctx.close()
        browser0.close()
        return {"entryTexts": info, "clicked": clicked, "form": form}


if __name__ == "__main__":
    result = {"logged_in": browser.run_on_page(in_logged_in)}
    try:
        result["logged_out"] = logged_out()
    except Exception as ex:
        result["logged_out_error"] = str(ex)[:300]
    print(json.dumps(result, ensure_ascii=False, indent=2))
