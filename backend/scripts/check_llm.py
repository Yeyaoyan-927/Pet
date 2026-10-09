"""LLM 接入探测脚本：验证阿里云百炼免费额度模型是否可用。

用法（backend 目录）：
    python scripts/check_llm.py
"""
from __future__ import annotations

import asyncio
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from app.agent.llm.client import bailian_client, probe_free_models  # noqa: E402
from app.config import settings  # noqa: E402


async def main() -> int:
    print("=" * 68)
    print("阿里云百炼（DashScope）免费额度模型接入检查")
    print("=" * 68)
    print(f"接入开关 LLM_ENABLED      : {settings.LLM_ENABLED}")
    print(f"服务商   LLM_PROVIDER     : {settings.LLM_PROVIDER}")
    print(f"端点     LLM_BASE_URL     : {settings.LLM_BASE_URL}")
    print(f"主模型   LLM_MODEL        : {settings.LLM_MODEL}")
    print(f"免费模型链                : {' -> '.join(settings.llm_model_chain)}")
    print(f"API Key 已配置            : {'是' if settings.DASHSCOPE_API_KEY.strip() else '否'}")
    print("-" * 68)

    if not settings.llm_available:
        print("[降级] 未配置 DASHSCOPE_API_KEY，LLM 增强关闭。")
        print("       系统行为：风险判别自动使用规则引擎，业务不受影响。")
        print()
        print("配置步骤：")
        print("  1. 打开 https://bailian.console.aliyun.com/ 开通百炼服务（有免费额度）")
        print("  2. 在「API-KEY 管理」创建 Key（形如 sk-xxxxxxxx）")
        print("  3. 对照「费用与配额 - 免费额度」页面确认可用模型，写入 backend/.env：")
        print("       DASHSCOPE_API_KEY=sk-xxxxxxxx")
        print("       LLM_MODEL=qwen-plus")
        print("       LLM_FALLBACK_MODELS=qwen3.7-flash")
        print("  4. 重新执行本脚本验证")
        print("=" * 68)
        return 0

    health = await bailian_client.health()
    print("状态:", health)
    print("-" * 68)
    print("逐个探测免费模型链 ...")
    results = await probe_free_models()
    for item in results:
        flag = "OK  " if item.get("ok") else "FAIL"
        extra = f"{item.get('latency_ms', 0)}ms" if item.get("ok") else str(item.get("error"))[:110]
        print(f"  [{flag}] {item['model']:<24} {extra}")
    ok_count = sum(1 for r in results if r.get("ok"))
    print("-" * 68)
    print(f"可用模型：{ok_count} / {len(results)}")
    if ok_count == 0:
        print("提示：请核对 API Key 有效性与模型名是否在免费额度清单内。")
    print("=" * 68)
    await bailian_client.close()
    return 0 if ok_count else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
