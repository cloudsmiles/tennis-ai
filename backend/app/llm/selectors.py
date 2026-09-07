# 通义千问网页选择器。网页改版时只需修改此处。
# 占位选择器在手动登录后用浏览器 DevTools 核对并填准。
TONGYI_URL = "https://www.tongyi.com"

SELECTORS = {
    "upload_button": "input[type=file]",
    "chat_input":   "textarea",
    "send_button":  "button[data-testid='send']",
    "stop_button":  "button[aria-label*='停止']",
    "reply_block":  "div.message-assistant",
    "new_chat":     "button:has-text('新对话')",
}
