"""合规风控守卫：横切所有 Agent 的**回答出口**校验。

为什么是规则而不是一个 Agent：
合规是**确定性要求**——「不能下诊断」「不能给处方剂量」「不能淡化急症」这几条
必须每次都判得一样。再叫一次模型来判，只会引入随机性、多一次延迟，还多一个失败点。
所以它是出口上的一道规则闸门，不是第 10 个 LLM 角色。

三条红线（对应 `03-Agent架构设计.md` 的合规约定）：
1. **急症不得淡化**：命中抽搐 / 大出血 / 呼吸困难 / 中毒 / 尿闭等，回答前必须置顶就医提示。
2. **不得给诊断结论与处方剂量**：命中「确诊」「就是 XX 病」「剂量」「mg/kg」「抗生素名」，
   回答后追加免责声明。
3. **不得推荐有毒食物**：命中「可以吃巧克力 / 葡萄 / 洋葱」这类肯定表述，直接改成警告。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 急症信号：出现即置顶「立刻就医」，不允许只给居家建议
EMERGENCY_SIGNS: tuple[str, ...] = (
    "抽搐", "大出血", "流血不止", "呼吸困难", "呼吸急促", "舌头发紫", "舌色发绀",
    "中毒", "误食", "昏迷", "瘫软", "尿不出", "尿闭", "无法排尿", "腹胀如鼓",
    "胃扭转", "高烧不退", "持续呕吐", "便血", "吐血",
)

# 诊断 / 处方类表述：不允许以肯定语气出现
DIAGNOSIS_WORDS: tuple[str, ...] = (
    "确诊", "可以确定是", "就是得了", "肯定是", "百分之百是",
    "处方药", "抗生素", "激素", "地塞米松", "阿莫西林", "头孢", "甲硝唑",
    "剂量", "mg/kg", "毫克每公斤", "每次一片", "每次半片",
    # 用药建议：出现即追加「需兽医面诊」，防止模型顺口给出「喂点药就好」
    # 注意不要收「可以吃 / 吃点」这类泛词——正常食物建议也会命中，造成满屏免责
    "喂点药", "用点药", "自行用药", "人用药", "吃点药",
)

# 有毒食物：命中「推荐吃」的句式才报警，单纯列举禁忌不算
TOXIC_FOODS: tuple[str, ...] = ("巧克力", "葡萄", "葡萄干", "洋葱", "大蒜", "木糖醇", "夏威夷果")

# 「推荐 / 可以吃」这类肯定句式
RECOMMEND_WORDS: tuple[str, ...] = ("可以吃", "能吃", "建议喂", "推荐喂", "喂点", "给它吃")

# 健康语境词：出现在回答里就说明这是一条健康相关建议，应统一附免责
HEALTH_CONTEXT: tuple[str, ...] = (
    "就医", "医院", "就诊", "症状", "诊断", "吃药", "用药", "喂药", "疾病", "感染",
    "发炎", "炎症", "疼痛", "异常", "观察一下", "转诊",
)

DISCLAIMER = "以上为通用护理参考，不构成医疗诊断；症状持续或加重请及时到宠物医院面诊。"
EMERGENCY_PREFIX = "⚠️ 你描述的情况可能属于急症，请**立刻送宠物医院**，不要在家观察。"


@dataclass
class ComplianceVerdict:
    """一次出口校验的结果。`flags` 用于日志与可观测，`prefix/suffix` 用于改写回答。"""

    flags: list[str] = field(default_factory=list)
    prefix: str = ""
    suffix: str = ""

    @property
    def triggered(self) -> bool:
        return bool(self.flags)


def review_answer(text: str, *, intent: str | None = None) -> ComplianceVerdict:
    """校验一条准备发给用户的回答（纯函数，不改状态、不调模型）。

    只对「知识问答 / 健康相关」的回答生效：闲聊、槽位追问、确认卡不做过期打扰。
    """
    verdict = ComplianceVerdict()
    content = text or ""
    if not content:
        return verdict

    # 只校验知识 / 医疗相关回答：其他 intent 的文本（确认卡、追问、权限提示）不处理。
    # intent 缺失时按知识问答处理（保守），但要求文本足够长，避免误伤短提示。
    knowledge_like = intent in (None, "search_knowledge", "query_risk_report", "confirm_risk")
    if not knowledge_like:
        return verdict

    # 1) 急症：置顶就医提示（这条最重要，宁可多提醒）
    hit_emergency = [w for w in EMERGENCY_SIGNS if w in content]
    if hit_emergency:
        verdict.flags.append("emergency:" + ",".join(hit_emergency[:3]))
        if "立刻送" not in content and "立即就医" not in content:
            verdict.prefix = EMERGENCY_PREFIX

    # 2) 诊断 / 处方：追加免责
    hit_diagnosis = [w for w in DIAGNOSIS_WORDS if w in content]
    if hit_diagnosis:
        verdict.flags.append("diagnosis:" + ",".join(hit_diagnosis[:3]))
        if "不构成医疗诊断" not in content:
            verdict.suffix = DISCLAIMER

    # 2.1) 健康语境兜底：只要回答在谈症状 / 就医 / 用药，就统一附免责。
    # 只看「有没有命中诊断词」会漏——「门店不做诊断、请带去医院」这类正确表述同样属于健康建议。
    if not verdict.suffix and "不构成医疗诊断" not in content:
        hit_health = [w for w in HEALTH_CONTEXT if w in content]
        if hit_health:
            verdict.flags.append("health_context:" + ",".join(hit_health[:3]))
            verdict.suffix = DISCLAIMER

    # 3) 有毒食物被当成推荐：优先级最高，直接改写为警告
    hit_toxic = [w for w in TOXIC_FOODS if w in content]
    if hit_toxic and any(w in content for w in RECOMMEND_WORDS):
        verdict.flags.append("toxic_food:" + ",".join(hit_toxic[:3]))
        verdict.prefix = (
            f"⚠️ 请注意：{'、'.join(hit_toxic[:3])} 对犬猫有明确毒性，任何情况下都不要喂食。"
        )

    return verdict


def apply_verdict(text: str, verdict: ComplianceVerdict) -> str:
    """把校验结论落成最终文本（前置提醒 + 正文 + 后置声明）。"""
    if not verdict.triggered:
        return text
    body = text
    if verdict.prefix:
        body = f"{verdict.prefix}\n\n{body}"
    if verdict.suffix:
        body = f"{body}\n\n{verdict.suffix}"
    return body
