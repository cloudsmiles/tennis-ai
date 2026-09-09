"""一次性诊断（第三轮）：真实走一遍 传图→发送→等回复，记录新 DOM 选择器。

用 expect_file_chooser 拦截原生文件框；发一句最简单的话，dump 生成中按钮与
回复消息容器结构。仅用于核对选择器，会真实调用一次千问。
"""
import json
import time
from pathlib import Path

from app.llm.browser import browser
from app.llm.selectors import TONGYI_URL

IMG = Path("/tmp/annotated6.jpg")


def probe(page):
    out = {}
    page.goto(TONGYI_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(6000)

    # 1) 添加附件（拦截系统文件选择框；若网页改为挂载隐藏 input 也兼容）
    try:
        with page.expect_file_chooser(timeout=4000) as fc:
            page.click("button[aria-label='添加附件']")
        fc.value.set_files(str(IMG))
        out["attach"] = "filechooser"
    except Exception:
        page.click("button[aria-label='添加附件']")
        page.wait_for_timeout(1000)
        inp = page.query_selector("input[type=file]")
        if inp:
            inp.set_input_files(str(IMG))
            out["attach"] = "hidden-input"
        else:
            out["attach"] = "UNKNOWN"
    page.wait_for_timeout(3000)
    page.screenshot(path="/tmp/qw_uploaded.png")

    # 2) 在 contenteditable 里输入一句话
    box = page.query_selector("div[contenteditable='true']")
    box.click()
    page.keyboard.type("这是一张测试图片，你能看到吗？请只回答：能看到", delay=20)
    page.wait_for_timeout(500)

    # 3) 发送并轮询按钮集合，找"停止/生成中"语义
    page.click("button[aria-label='发送消息']")
    labels_seen = set()
    reply_dump = None
    for _ in range(60):  # 最多 120s
        page.wait_for_timeout(2000)
        labels = page.evaluate(
            """() => [...document.querySelectorAll('button,[role=button]')]
               .map(e => e.getAttribute('aria-label'))
               .filter(Boolean)"""
        )
        for l in labels:
            labels_seen.add(l)
        stopish = [l for l in labels if l and any(
            k in l for k in ("停止", "暂停", "中止", "Stop"))]
        # 完成启发式：出现"复制/重新生成/赞"等消息动作按钮
        done = [l for l in labels if l and any(
            k in l for k in ("复制", "重新生成", "重试"))]
        if done and not stopish:
            reply_dump = page.evaluate(
                r"""() => {
                  const sels = ["div.message-assistant", "[class*='assistant']",
                    "[class*='message-item']", "article", "[data-role='assistant']",
                    "[class*='receive']", "[class*='answer']", "[class*='reply']",
                    "[class*='chat-item']", "[class*='msg-item']"];
                  const counts = Object.fromEntries(sels.map(s =>
                    [s, document.querySelectorAll(s).length]));
                  // 找页面上最长的可见文本块及其祖先链
                  let best = null;
                  for (const e of document.querySelectorAll('div,article,li')) {
                    const t = (e.innerText || '').trim();
                    if (t.length >= 4 && t.length < 400 &&
                        e.querySelector('div,article,li') === null) {
                      if (!best || t.length > best.t.length)
                        best = {t, cls: (e.className||'').toString().slice(0,120),
                                role: e.getAttribute('role'),
                                tag: e.tagName,
                                parentCls: (e.parentElement?.className||'')
                                  .toString().slice(0,120)};
                    }
                  }
                  return {counts, best};
                }""")
            out["done_label"] = done
            break
    out["labels_seen"] = sorted(labels_seen)
    out["reply"] = reply_dump
    page.screenshot(path="/tmp/qw_reply.png")
    return out


if __name__ == "__main__":
    print(json.dumps(browser.run_on_page(probe), ensure_ascii=False, indent=2))
