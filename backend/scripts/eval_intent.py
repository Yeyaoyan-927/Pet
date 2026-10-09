"""意图识别评测集：量化「LLM 可用 / 不可用」两种状态下的意图识别质量。

为什么需要它：
- 架构上 LLM 不可用时必须能降级到规则法（业务不能停），但**降级会损失多少准确率**以前没人量化过；
- 本脚本对同一批样本分别跑「规则法」与「LLM 法」，输出准确率、覆盖率与回退代价，
  为「要不要加规则」「要不要换模型」提供数据，而不是拍脑袋。

用法（backend 目录）：
    python scripts/eval_intent.py              # 规则法 + LLM 法
    python scripts/eval_intent.py --no-llm     # 只跑规则法（零额度消耗）
    python scripts/eval_intent.py --limit 10   # 只跑前 10 条样本

输出：逐条明细（仅打印错例）+ 汇总指标 + 结论。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from app.agent.react import AgentRunner  # noqa: E402
from app.config import settings  # noqa: E402
from app.agent.tools.registry import tool_manifest  # noqa: E402


@dataclass
class Sample:
    role: str
    text: str
    expect: str  # 期望意图；"smalltalk" 表示应判为闲聊/无法处理


# 样本集：每个意图 2 种问法，覆盖三角色 + 负样本（闲聊）
SAMPLES: list[Sample] = [
    # ---------------- 宠主 ----------------
    Sample("customer", "明天还有哪些时段可以预约？", "query_slots"),
    Sample("customer", "这周六几点有空位可以洗澡", "query_slots"),
    Sample("customer", "帮我看看豆豆的档案", "query_pet_profile"),
    Sample("customer", "咪咪的过敏史是什么", "query_pet_profile"),
    Sample("customer", "我最近的预约到哪一步了", "query_my_appointments"),
    Sample("customer", "我还有几单没洗", "query_my_appointments"),
    Sample("customer", "帮我给豆豆预约明天 15:00 洗澡", "create_appointment"),
    Sample("customer", "我要约周五 10:00 的药浴", "create_appointment"),
    Sample("customer", "取消预约 PG20261014123456", "cancel_appointment"),
    Sample("customer", "帮我把那笔预约退掉", "cancel_appointment"),
    # 知识问答路由（V8.4.2 回归）：三句曾分别误判为查档案（权限报错）/ 寒暄
    Sample("staff", "应激反应的三个等级", "search_knowledge"),
    Sample("staff", "安抚手法的步骤", "search_knowledge"),
    Sample("customer", "为什么必须先看后洗", "search_knowledge"),
    Sample("customer", "你好呀", "smalltalk"),
    Sample("customer", "今天天气不错", "smalltalk"),
    # ---------------- 店员 ----------------
    Sample("staff", "我今天有什么要处理的？", "query_todo"),
    Sample("staff", "交班前还有哪些事要做", "query_todo"),
    Sample("staff", "今天排了几单，哪个时段比较空", "query_day_schedule"),
    Sample("staff", "明天的预约安排给我看看", "query_day_schedule"),
    Sample("staff", "帮我查一下客户张女士的宠物档案", "query_customer_pets"),
    Sample("staff", "找一下「王先生」的档案", "query_customer_pets"),
    Sample("staff", "豆豆上次洗护有什么异常吗", "query_wash_history"),
    Sample("staff", "旺财的洗护历史给我看看", "query_wash_history"),
    Sample("staff", "PG20261014123456 这单确认一下", "advance_appointment"),
    Sample("staff", "这单客人到店了", "advance_appointment"),
    Sample("staff", "帮我给客户预约明天 15:00 洗澡", "create_appointment_for_customer"),
    Sample("staff", "客户要预约，代客下单", "create_appointment_for_customer"),
    Sample("staff", "你好", "smalltalk"),
    # ---------------- 店长 ----------------
    Sample("manager", "近 30 天经营情况怎么样？", "query_report_summary"),
    Sample("manager", "这个月做了多少单", "query_report_summary"),
    Sample("manager", "这周哪个时段还有空可以加单？", "query_capacity_analysis"),
    Sample("manager", "最近时段是不是很闲", "query_capacity_analysis"),
    Sample("manager", "有哪些客户该回访了？", "query_churn_list"),
    Sample("manager", "多久没来的宠物有哪些", "query_churn_list"),
    Sample("manager", "看看这个月店员的工作量对比", "query_staff_performance"),
    Sample("manager", "谁洗得最多", "query_staff_performance"),
    Sample("manager", "最近谁改过门店配置？", "query_audit_trail"),
    Sample("manager", "查一下操作日志", "query_audit_trail"),
    Sample("manager", "把流失预警天数从 90 改成 60", "update_store_setting"),
    Sample("manager", "门店的时段接待容量改成 4", "update_store_setting"),
    Sample("manager", "启用账号 staff2", "toggle_user_status"),
    Sample("manager", "把 liu 这个账号停用", "toggle_user_status"),
    Sample("manager", "跑一次 SLA 超时巡检", "run_sla_scan"),
    Sample("manager", "现在做一次超时巡检", "run_sla_scan"),
    Sample("manager", "你好，在吗", "smalltalk"),
]


class _FakeUser:
    """规则法只依赖 user.role，评测无需真实用户。"""

    def __init__(self, role: str) -> None:
        self.role = role


def _rule_runner(role: str) -> AgentRunner:
    runner = object.__new__(AgentRunner)
    runner.user = _FakeUser(role)  # type: ignore[assignment]
    return runner


def predict_by_rule(sample: Sample) -> str:
    """规则法（LLM 不可用时的降级路径）。

    注意必须走 `_interpret_by_rule`（完整链路：运营意图 + 宠主通用意图 + 槽位抽取），
    只调 `_operation_intent_by_rule` 会漏掉宠主的全部意图，得出虚低的准确率。
    """
    runner = _rule_runner(sample.role)
    return str(runner._interpret_by_rule(sample.text)["intent"])


async def predict_by_llm(sample: Sample) -> str:
    """LLM 法：直接复用生产提示词与工具画像，只做「意图识别」这一步。"""
    from app.agent.llm.client import bailian_client
    from app.agent.llm.prompts import INTENT_SYSTEM_PROMPT, ROLE_OPERATION_PROMPT

    from app.agent.tools.profiles import ROLE_PROMPT_HINT

    system = INTENT_SYSTEM_PROMPT
    extra = ROLE_OPERATION_PROMPT.get(sample.role)
    if extra:
        system = f"{system}\n\n{extra}"

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": (
            f"{ROLE_PROMPT_HINT.get(sample.role, '')}\n\n"
            f"【当前角色可用工具（intent 只能取其中之一或 smalltalk）】\n"
            f"{json.dumps(tool_manifest(sample.role), ensure_ascii=False)}\n"
            f"【今天日期】{date.today().isoformat()}\n"
            f"【用户说】{sample.text}"
        )},
    ]
    result = await bailian_client.chat_with_fallback(messages, json_mode=True, temperature=0.1)
    if not result.ok or not result.data:
        return "error"
    return str(result.data.get("intent") or "smalltalk")


def summarize(name: str, rows: list[tuple[Sample, str]]) -> dict:
    total = len(rows)
    correct = sum(1 for s, p in rows if p == s.expect)
    unknown = sum(1 for _, p in rows if p in ("smalltalk", "error"))
    wrong = [(s.role, s.text, s.expect, p) for s, p in rows if p != s.expect]
    return {
        "name": name,
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total * 100, 1) if total else 0.0,
        "fallback": round(unknown / total * 100, 1) if total else 0.0,
        "wrong": wrong,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description="意图识别评测")
    parser.add_argument("--no-llm", action="store_true", help="只跑规则法，不消耗模型额度")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条样本")
    args = parser.parse_args()

    samples = SAMPLES[: args.limit] if args.limit else SAMPLES
    print("=" * 64)
    print(f"意图识别评测：样本 {len(samples)} 条（覆盖宠主 / 店员 / 店长三角色）")
    print("=" * 64)

    rule_rows = [(s, predict_by_rule(s)) for s in samples]
    rule_stat = summarize("规则法（LLM 降级路径）", rule_rows)
    print(f"\n【{rule_stat['name']}】准确率 {rule_stat['accuracy']}%  "
          f"未识别/闲聊占比 {rule_stat['fallback']}%  （{rule_stat['correct']}/{rule_stat['total']}）")
    for role, text, expect, got in rule_stat["wrong"]:
        print(f"   ✗ [{role}] {text} → 期望 {expect}，实际 {got}")

    exit_code = 0
    if not args.no_llm:
        print("\n正在逐条调用模型（消耗免费额度）...")
        llm_rows = []
        for s in samples:
            llm_rows.append((s, await predict_by_llm(s)))
        llm_stat = summarize(f"LLM 法（{settings.LLM_MODEL}）", llm_rows)
        print(f"\n【{llm_stat['name']}】准确率 {llm_stat['accuracy']}%  "
              f"未识别/闲聊占比 {llm_stat['fallback']}%  （{llm_stat['correct']}/{llm_stat['total']}）")
        for role, text, expect, got in llm_stat["wrong"]:
            print(f"   ✗ [{role}] {text} → 期望 {expect}，实际 {got}")

        delta = round(llm_stat["accuracy"] - rule_stat["accuracy"], 1)
        print("\n" + "-" * 64)
        print(f"降级代价（LLM 不可用时损失）：{delta} 个百分点")
        if delta > 20:
            print("结论：规则法覆盖不足，建议补充关键词规则或提高规则优先级。")
        elif delta > 5:
            print("结论：规则法可支撑降级运行，LLM 主要在长尾表述上更好。")
        else:
            print("结论：两者接近，降级风险可控。")
        if llm_stat["accuracy"] < 85:
            print("提示：LLM 法准确率偏低，建议检查提示词或工具画像描述。")
            exit_code = 1
    print("=" * 64)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
