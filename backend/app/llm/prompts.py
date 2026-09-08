STROKE_ZH = {"forehand": "正手", "backhand": "反手", "serve": "发球"}

_JSON_FORMAT = (
    "只返回一个 JSON 对象，不要输出任何其他文字，格式：\n"
    '{"stroke_type":"forehand 或 backhand 或 serve",'
    '"scores":{"准备":0-10整数,"击球点":0-10整数,"随挥":0-10整数},'
    '"overall":0-10的数字,'
    '"issues":["问题1","问题2"],'
    '"advice":"一段改进建议"}\n'
)


def analysis_prompt(stroke_type: str | None = None) -> str:
    """构建点评 prompt。

    stroke_type 给定（手动模式，用户已标注动作类型）时，让模型直接据此评分
    纠错、不再承担分类职责（画面明显不符时在 advice 中指出）；为 None（自动
    模式）时要求模型自行判断动作类型。
    """
    if stroke_type in STROKE_ZH:
        zh = STROKE_ZH[stroke_type]
        return (
            f"你是专业网球教练。这张图从左到右是同一个{zh}击球动作的三个阶段："
            "准备(引拍)、击球瞬间、随挥。动作类型已由用户标注为"
            f"{zh}，请直接据此评分与纠错；若画面与该类型明显不符，在 advice 里指出。\n"
            f"{_JSON_FORMAT}"
            f'stroke_type 请填 "{stroke_type}"。'
        )
    return (
        "你是专业网球教练。这张图从左到右是同一个击球动作的三个阶段："
        "准备(引拍)、击球瞬间、随挥。请判断动作类型并给出技术纠错。\n"
        f"{_JSON_FORMAT}"
        "stroke_type 只能是 forehand(正手)、backhand(反手)、serve(发球) 之一。"
    )


# 向后兼容：自动模式（无标注）的默认 prompt
ANALYSIS_PROMPT = analysis_prompt(None)
