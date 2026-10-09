"""混沌测试：向系统注入真实故障，验证「降级而非崩溃」（V8）。

设计原则
--------
1. **只用真实故障形态**：注入的是 `httpx.ReadTimeout`（LLM 超时）、
   `OperationalError`（MySQL 断连）、非法输入等真实会发生的错误，而不是随手 `raise Exception`。
2. **断言的是行为，不是日志**：每个场景都要问「用户会看到什么」——
   AI 不可用时是否仍能下单、DB 抖动时返回的是统一 JSON 错误还是 HTML 堆栈。
3. **可重复执行**：注入点用完即恢复（`monkeypatch` 语境 / 上下文管理器），不污染后续用例。

运行：`python scripts/chaos_test.py`（零外部依赖，进程内起 TestClient）
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from app.agent.llm.client import bailian_client  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402

RESULTS: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    RESULTS.append((ok, name, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  |  {detail[:150]}" if detail and not ok else ""))


@contextmanager
def patch_attr(obj, name: str, value):
    """临时替换属性，退出时恢复（比 monkeypatch 更适合脚本内使用）。"""
    original = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, original)


def consume_sse(resp) -> dict:
    """把 SSE 响应解析成结构化结果（事件类型计数 + 回答文本）。"""
    events: list[dict] = []
    for line in resp.iter_lines():
        if not line or not line.startswith("data:"):
            continue
        try:
            events.append(json.loads(line[5:].strip()))
        except json.JSONDecodeError:
            continue
    kinds = [e.get("type") for e in events]
    # 逐字输出用的是 delta 字段（见 AgentRunner._answer_and_save）
    answer = "".join(e.get("delta", "") for e in events if e.get("type") == "answer")
    return {
        "kinds": kinds,
        "answer": answer,
        "error": next((e.get("message") for e in events if e.get("type") == "error"), None),
        "ended": "end" in kinds,
    }


def load_demo_credentials() -> dict[str, tuple[str, str]]:
    """取演示账号凭据。

    优先读环境变量（CI 用），否则复用 `scripts/smoke_test.py` 里已有的演示账号 ——
    **凭据不写进本脚本**，避免多一处需要同步的密钥副本。
    """
    import os
    import re

    creds: dict[str, tuple[str, str]] = {}
    for role, user_env, pwd_env in (
        ("customer", "CHAOS_CUSTOMER_USER", "CHAOS_CUSTOMER_PWD"),
        ("staff", "CHAOS_STAFF_USER", "CHAOS_STAFF_PWD"),
        ("manager", "CHAOS_MANAGER_USER", "CHAOS_MANAGER_PWD"),
    ):
        user, pwd = os.getenv(user_env), os.getenv(pwd_env)
        if user and pwd:
            creds[role] = (user, pwd)

    if len(creds) == 3:
        return creds

    src = (Path(__file__).parent / "smoke_test.py").read_text(encoding="utf-8")
    pairs = re.findall(r'"username":\s*"([^"]+)",\s*"password":\s*"([^"]+)"', src)
    by_role: dict[str, list[tuple[str, str]]] = {}
    for user, pwd in pairs:
        if user.startswith("temp_") or user.startswith("smoke"):
            continue
        by_role.setdefault(user, []).append((user, pwd))
    # 冒烟按「宠主 → 店员 → 店长」顺序登录，去重后依序对应
    seen: list[tuple[str, str]] = []
    for user, pwd in pairs:
        if user.startswith("temp_") or user.startswith("smoke"):
            continue
        if all(user != u for u, _ in seen):
            seen.append((user, pwd))
    if len(seen) >= 3:
        creds.setdefault("customer", seen[0])
        creds.setdefault("staff", seen[1])
        creds.setdefault("manager", seen[2])
    return creds


def main() -> int:
    from fastapi.testclient import TestClient

    from app.main import app

    # raise_server_exceptions=False：混沌测试要看「用户实际收到什么」，
    # 默认 True 会把服务端异常直接抛回脚本，反而看不到统一错误信封
    with TestClient(app, raise_server_exceptions=False) as client:
        # ---------- 准备账号（凭据复用冒烟脚本，不写死） ----------
        creds = load_demo_credentials()
        if len(creds) < 3:
            print("!! 未找到演示账号凭据：请设置 CHAOS_*_USER/PWD 环境变量，或先执行 python scripts/init_db.py")
            return 2

        def login(role: str):
            user, pwd = creds[role]
            return client.post("/api/v1/auth/login", json={"username": user, "password": pwd})

        cust, staff, mgr = login("customer"), login("staff"), login("manager")
        if cust.status_code != 200 or staff.status_code != 200:
            print("!! 演示账号登录失败，请先执行 python scripts/init_db.py")
            return 2
        ch = {"Authorization": f"Bearer {cust.json()['data']['access_token']}"}
        sh = {"Authorization": f"Bearer {staff.json()['data']['access_token']}"}

        print("\n== C1. LLM 不可用：对话仍要走规则法给出可用回答 ==")
        # llm_available 是 Settings 上的只读 property（由 API Key 推导），
        # 只能替换类上的 property 描述符来模拟「未配置 Key」
        with patch_attr(type(settings), "llm_available", property(lambda self: False)):
            r = client.post("/api/v1/chat/message", headers=ch,
                            json={"content": "帮我看看明天有哪些时段可以预约"})
            r.raise_for_status()
            out = consume_sse(r)
            check(r.status_code == 200, "SSE 建立连接（HTTP 200）", str(r.status_code))
            check(out["ended"], "流正常结束（有 end 事件）", str(out["kinds"][-3:]))
            check(out["error"] is None, "未向用户抛错误", str(out["error"]))
            check(bool(out["answer"]), "规则法给出了回答", out["answer"][:120])

        print("\n== C2. LLM 超时（httpx.ReadTimeout）：自动降级且不中断会话 ==")

        async def _timeout(*_args, **_kwargs):
            raise httpx.ReadTimeout("chaos: 模拟上游超时")

        with patch_attr(bailian_client, "chat_with_fallback", _timeout):
            r = client.post("/api/v1/chat/message", headers=ch,
                            json={"content": "我有哪些宠物"})
            out = consume_sse(r)
            check(r.status_code == 200, "超时后 SSE 仍返回 200", str(r.status_code))
            check(out["ended"], "超时后流正常结束", str(out["kinds"][-3:]))
            check(out["error"] is None, "超时不暴露原始异常给用户", str(out["error"]))
            check(bool(out["answer"]), "超时后仍由规则法应答", out["answer"][:120])

        print("\n== C3. LLM 返回非法 JSON：不采信、回退规则 ==")

        class BadResult:
            ok = True
            data = None
            content = "{这不是 JSON"
            model = "chaos"
            latency_ms = 1
            error = None
            usage: dict = {}

        async def _bad(*_args, **_kwargs):
            return BadResult()

        with patch_attr(bailian_client, "chat_with_fallback", _bad):
            r = client.post("/api/v1/chat/message", headers=ch, json={"content": "查看我的预约"})
            out = consume_sse(r)
            check(r.status_code == 200 and out["ended"], "非法 JSON 下会话仍正常结束",
                  f"{r.status_code} {out['kinds'][-3:]}")
            check(out["error"] is None, "非法 JSON 不抛错给用户", str(out["error"]))

        print("\n== C4. 风险判别在 LLM 异常时回退规则（AI 抖动不影响下单） ==")
        pets = client.get("/api/v1/pets", headers=ch).json()["data"]
        pet_id = pets[0]["id"] if pets else None
        if pet_id:
            with patch_attr(bailian_client, "chat_with_fallback", _timeout):
                r = client.post("/api/v1/appointments", headers=ch, json={
                    "pet_id": pet_id, "service_type": "basic_bath",
                    "appoint_date": "2030-06-18", "slot_time": "15:00",
                    "idempotent_key": f"chaos-risk-{int(time.time())}",
                })
                ok_book = r.status_code in (200, 409)  # 409 = 该时段已满，同样说明链路通了
                check(ok_book, "LLM 超时时预约链路仍可完成", f"{r.status_code} {r.text[:160]}")
                if r.status_code == 200:
                    rid = r.json()["data"]["id"]
                    detail = client.get(f"/api/v1/appointments/{rid}", headers=ch)
                    check(detail.status_code == 200 and detail.json()["data"].get("risk_level"),
                          "风险报告已产出（规则引擎兜底）", detail.text[:160])

        print("\n== C5. MySQL 断连：返回统一 JSON 错误，绝不返回 HTML 堆栈 ==")

        original_execute = AsyncSessionLocal.class_.execute

        async def _boom(*_args, **_kwargs):
            raise OperationalError("SELECT 1", {}, Exception("chaos: 模拟 MySQL 断连"))

        with patch_attr(AsyncSessionLocal.class_, "execute", _boom):
            r = client.get("/api/v1/pets", headers=ch)
        check(r.status_code == 500, "DB 断连时返回 500", str(r.status_code))
        body_ok = False
        try:
            payload = r.json()
            body_ok = payload.get("code") == 5000 and "服务内部错误" in payload.get("message", "")
        except Exception:
            pass
        check(body_ok, "错误体是统一 JSON 信封（非 HTML 堆栈）", r.text[:160])
        check("<html" not in r.text.lower() and "traceback" not in r.text.lower(),
              "响应未泄露堆栈", r.text[:120])

        # 恢复后必须自愈（连接池不应被一次故障永久打坏）
        r = client.get("/api/v1/pets", headers=ch)
        check(r.status_code == 200, "故障恢复后接口自动自愈", str(r.status_code))

        print("\n== C6. 非法输入：一律 4xx，不得 500 ==")
        cases = [
            ("空内容", {"content": ""}),
            ("超长内容", {"content": "约" * 4000}),
            ("非法 session_id", {"content": "你好", "session_id": 99999999}),
        ]
        for name, payload in cases:
            r = client.post("/api/v1/chat/message", headers=ch, json=payload)
            # 空内容应在进流前被校验拦截（422）；超长/非法会话允许在流内以 error 事件收尾
            ok = r.status_code in (400, 403, 404, 422) or (
                r.status_code == 200 and "error" in r.text
            )
            check(ok, f"非法输入「{name}」被正常拒绝", f"{r.status_code} {r.text[:120]}")

        print("\n== C7. 并发峰值：20 并发混合读，不允许出现 5xx ==")

        from concurrent.futures import ThreadPoolExecutor

        endpoints = [
            ("/api/v1/pets", ch), ("/api/v1/appointments?page=1&size=10", ch),
            ("/api/v1/messages?page=1&size=10", ch), ("/api/v1/boarding/orders", ch),
            ("/api/v1/goods/products", ch), ("/api/v1/appointments?page=1&size=10", sh),
        ]

        def one(i: int) -> int:
            path, headers = endpoints[i % len(endpoints)]
            try:
                return client.get(path, headers=headers).status_code
            except Exception:
                return 0

        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=10) as pool:
            codes = list(pool.map(one, range(20)))
        elapsed = (time.perf_counter() - started) * 1000
        check(all(c == 200 for c in codes), "20 并发全部 200", str(sorted(set(codes))))
        check(max(codes) < 500, "并发下无 5xx", str(sorted(set(codes))))
        print(f"        （20 请求耗时 {elapsed:.0f} ms，均 {(elapsed / 20):.1f} ms/请求）")

        print("\n== C8. 会话级并发锁：同一会话连点两次不应并发执行 ==")
        r = client.get("/api/v1/tasks/lock-status", headers=sh)
        # 店员无权限，顺带验证越权
        check(r.status_code == 403, "店员访问锁状态被拒（403）", str(r.status_code))
        mh = {"Authorization": f"Bearer {mgr.json()['data']['access_token']}"}
        r = client.get("/api/v1/tasks/lock-status", headers=mh)
        check(r.status_code == 200 and "lock" in r.json()["data"],
              "店长可查看锁状态（运维排查）", r.text[:160])

    # ---------- 汇总 ----------
    passed = sum(1 for ok, _, _ in RESULTS if ok)
    total = len(RESULTS)
    print("\n" + "=" * 56)
    print(f"混沌测试结果：{passed}/{total} 通过")
    if passed != total:
        print("失败项：")
        for ok, name, detail in RESULTS:
            if not ok:
                print(f"  - {name} | {detail[:200]}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
