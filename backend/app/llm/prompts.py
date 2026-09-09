STROKE_ZH = {"forehand": "正手", "backhand": "反手", "serve": "发球"}

_JSON_FORMAT = (
    "只返回一个 JSON 对象，不要输出任何其他文字，格式：\n"
    '{"stroke_type":"forehand 或 backhand 或 serve",'
    '"level":"2.0/2.5/3.0/3.5/4.0/4.5/5.0 之一",'
    '"level_note":"一两句定级理由（结合本次动作的稳定性、发力链与击球质量）",'
    '"strengths":["做得好的点1","做得好的点2"],'
    '"weaknesses":["需要改进的点1","需要改进的点2"],'
    '"advice":"一段可执行的训练建议（具体练习方法与纠正要点）"}\n'
    "评级参考（NTRP 风格，可给半级）：2.0 入门、2.5 初学者、3.0 初级进阶、"
    "3.5 中级、4.0 中高级、4.5 高级、5.0+ 专业级。"
)


def _phases(stroke_type: str | None) -> str:
    if stroke_type == "serve":
        # 发球拼六帧：站位 → 抛球起势 → 引拍上举(trophy) → 拍头下坠蓄力 → 击球 → 随挥
        return ("六个阶段：准备(站位)、抛球起势、引拍上举、蓄力(拍头下坠)、"
                "击球瞬间、随挥结束")
    if stroke_type in ("forehand", "backhand"):
        # 正反手拼六帧：准备 → 引拍后摆 → 引拍蓄力顶点 → 击球 → 随挥前送 → 随挥结束
        return ("六个阶段：准备(引拍开始)、引拍后摆、引拍蓄力(顶点)、"
                "击球瞬间、随挥前送、随挥结束(收拍过身)")
    # 自动模式（无标注）仍是四帧拼贴
    return "四个阶段：准备(引拍开始)、引拍蓄力、击球瞬间、随挥结束"


def _coach_body(zh: str | None, phases: str, type_instruction: str) -> str:
    return (
        "你是资深网球教练，正在依据一组关键帧对球员做技术诊断。"
        f"这张图从左到右是同一个{zh or '击球'}动作完整过程的{phases}。\n"
        "请从生物力学角度认真观察：站位与平衡、转体与发力链（腿—髋—躯干—肩—手臂—手腕）、"
        "击球点位置与拍面、重心转移、随挥完整性、节奏与放松程度等，"
        "结合你自己的网球教学经验自由点评，不要拘泥于固定条目。\n"
        "strengths 与 weaknesses 各给 2~4 条，每条一句话、具体到帧中可见的动作细节，"
        "不要空泛套话；确实没有明显优点/缺点时可少给，但两栏至少各 1 条。"
        "advice 给出可直接照做的练习或纠正方法（可包含 1~2 个具体训练动作）。\n"
        f"{type_instruction}\n"
        f"{_JSON_FORMAT}"
    )


def analysis_prompt(stroke_type: str | None = None) -> str:
    """构建点评 prompt。

    stroke_type 给定（手动模式，用户已标注动作类型）时，让模型直接据此诊断、
    不再承担分类职责（画面明显不符时在 level_note 中指出）；为 None（自动模式）
    时要求模型自行判断动作类型。
    """
    if stroke_type in STROKE_ZH:
        zh = STROKE_ZH[stroke_type]
        type_instruction = (
            f"动作类型已由用户标注为{zh}，请直接据此点评；"
            "若画面与该类型明显不符，在 level_note 开头指出。\n"
            f'stroke_type 请填 "{stroke_type}"。'
        )
        return _coach_body(zh, _phases(stroke_type), type_instruction)
    type_instruction = (
        "请先判断动作类型，stroke_type 只能是 forehand(正手)、backhand(反手)、"
        "serve(发球) 之一。"
    )
    return _coach_body(None, _phases(None), type_instruction)


# 向后兼容：自动模式（无标注）的默认 prompt
ANALYSIS_PROMPT = analysis_prompt(None)
