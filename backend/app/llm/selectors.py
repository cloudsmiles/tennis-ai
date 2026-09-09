# 通义千问网页（www.qianwen.com，2026 改版后）选择器与页面脚本。
# 网页改版时只需修改此处。
#
# 已知结构（探测确认）：
# - 登录态：未登录时右上角有文本恰为「登录」的黑色按钮；已登录时该按钮消失、
#   左下角为用户头像。contenteditable 输入框在未登录时也存在，不能用作登录判据。
# - 登录表单在跨域 iframe：passport.qianwen.com/havanaone/login/login.htm。
# - 输入框是 contenteditable div；附件走「添加附件」按钮的两级菜单（上传图片）。
# - 回复正文在 .answer-common-card 内的 .qk-markdown，生成完成带 qk-markdown-complete。
TONGYI_URL = "https://www.qianwen.com"

SELECTORS = {
    "chat_input": "div[contenteditable='true']",
    "send_button": "button[aria-label='发送消息']",
    "stop_button": "button[aria-label='停止回答']",
    "attach_button": "button[aria-label='添加附件']",
    # 菜单项文本（get_by_text(name, exact=True) 使用）
    "upload_image_item": "上传图片",
    "reply_card": ".answer-common-card",
    "reply_markdown": ".answer-common-card .qk-markdown",
}

# 登录 iframe（阿里 Havana 统一登录）内的控件
LOGIN_FRAME_URL_PART = "passport.qianwen.com/havanaone"
LOGIN_SELECTORS = {
    "phone": "input[placeholder='请输入手机号']",
    "code": "input[placeholder='请输入验证码']",
    # 触发风控时才出现的图形验证码（初始 hidden）
    "image_code": "input[placeholder='图片验证码']",
    "agree": "input[type='checkbox']",
    "get_code": "获取验证码",
    "submit": "登录",
}

# 风控/验证弹窗文本（主文档与登录 iframe 通用）
CAPTCHA_PATTERNS = (
    "拖动",
    "滑块",
    "滑动",
    "安全验证",
    "完成验证",
    "图片验证码",
    "点击下方",
)

# (主文档) 读取登录状态。返回：
#   "logged_in"   —— 右上角「登录」按钮不存在
#   "logged_out"  —— 存在「登录」按钮且登录 iframe 未打开
#   "login_modal" —— 登录 iframe 已打开（登录流程进行中，一律视为未登录）
#   "unknown"     —— 页面尚未渲染出任何判据（调用方可短等后重试）
LOGIN_STATE_JS = r"""
() => {
  const loginFrame = [...document.querySelectorAll('iframe')]
    .some(f => (f.src || '').indexOf('passport.qianwen.com/havanaone') >= 0);
  if (loginFrame) return 'login_modal';
  const leafs = [...document.querySelectorAll('button,a,[role=button]')]
    .filter(e => e.offsetParent !== null && e.children.length === 0)
    .map(e => (e.innerText || '').trim());
  if (leafs.includes('登录')) return 'logged_out';
  const ce = document.querySelector("div[contenteditable='true']");
  if (ce) return 'logged_in';
  return 'unknown';
}
"""

# (主文档) 是否出现滑块/安全验证弹窗。用带语境的组合匹配，避免模型回复正文里
# 恰好出现「滑动/拖动」等词时误报。
CAPTCHA_JS = r"""
() => {
  const t = document.body ? (document.body.innerText || '') : '';
  return /拖动.{0,10}(滑块|验证)|滑块.{0,8}(完成|验证|拖动)|请.{0,6}(滑动|拖动).{0,10}验证|安全验证|完成验证/.test(t);
}
"""

# (主文档) 取最后一张回复卡片文本与完成态。
# JSON 优先取代码块 pre code 的 textContent：innerText 只反映「可见渲染」结果，
# 千问代码块经语法高亮拆成多 span（且可能含隐藏原始层），流式/重渲染时实测会
# 丢掉 ":" 等字符（"weaknesses": [ → "weaknesses [）；textContent 取 DOM 原文
# 不受影响。无代码块时才回退 markdown 容器的 innerText（保留换行供展示）。
REPLY_JS = r"""
() => {
  const cards = [...document.querySelectorAll('.answer-common-card')];
  const card = cards[cards.length - 1];
  if (!card) return {text: '', done: false};
  const mds = [...card.querySelectorAll('.qk-markdown')];
  if (!mds.length) return {text: '', done: false};
  const codes = [...card.querySelectorAll('pre code')]
    .map(c => c.textContent || '');
  const jsonish = codes.filter(t => t.indexOf('{') >= 0);
  const text = (jsonish.length
    ? jsonish[jsonish.length - 1]
    : mds.map(m => m.innerText || '').join('\n')).trim();
  const done = mds.some(m => /qk-markdown-complete/.test(m.className || ''));
  return {text, done};
}
"""
