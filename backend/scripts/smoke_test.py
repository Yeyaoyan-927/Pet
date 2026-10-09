"""冒烟测试脚本：不依赖 pytest，直接拉起 TestClient 走通核心链路。

用法（backend 目录）：
    python scripts/smoke_test.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, extra: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{(' -> ' + extra) if extra and not cond else ''}")


def _run_all(client: TestClient) -> int:
    print("== 1. 健康检查 ==")
    r = client.get("/health")
    check("GET /health", r.status_code == 200 and r.json()["code"] == 0)

    print("== 2. 鉴权 ==")
    r = client.post("/api/v1/auth/login", json={"username": "demo", "password": "123456"})
    check("宠主登录", r.status_code == 200 and r.json()["code"] == 0, r.text[:200])
    cust_token = r.json()["data"]["access_token"]
    cust_h = {"Authorization": f"Bearer {cust_token}"}

    r = client.post("/api/v1/auth/login", json={"username": "staff1", "password": "staff123"})
    check("店员登录", r.status_code == 200, r.text[:200])
    staff_h = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}

    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    check("店长登录", r.status_code == 200, r.text[:200])
    mgr_h = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}

    r = client.post("/api/v1/auth/login", json={"username": "demo", "password": "wrong"})
    check("错误密码被拒绝", r.status_code == 401, r.text[:120])

    r = client.get("/api/v1/auth/me", headers=cust_h)
    check("获取当前用户并脱敏手机号", r.json()["data"]["phone_masked"] == "138****1111",
          str(r.json()))

    r = client.get("/api/v1/pets", headers=cust_h)
    check("宠主宠物列表", r.status_code == 200 and len(r.json()["data"]) >= 2, r.text[:200])
    pets = r.json()["data"]
    pet_id = pets[0]["id"]

    print("== 3. 宠物档案 ==")
    r = client.post("/api/v1/pets", headers=cust_h, json={
        "name": "冒烟测试犬", "species": "dog", "breed": "泰迪", "gender": "male",
        "birthday": "2020-05-01", "weight": 6.5, "sterilized": 1, "stress_level": 1,
    })
    check("新增宠物档案", r.status_code == 200, r.text[:200])
    new_pet_id = r.json()["data"]["id"]

    r = client.post("/api/v1/pets", headers=cust_h, json={"name": "非法", "species": "tiger"})
    check("非法 species 被拦截", r.status_code == 422, r.text[:120])

    r = client.post(f"/api/v1/pets/{new_pet_id}/vaccines", headers=cust_h, json={
        "record_type": "vaccine", "name": "狂犬疫苗",
        "record_date": str(date.today()),
        "next_date": str(date.today() + timedelta(days=365)),
    })
    check("新增疫苗记录", r.status_code == 200, r.text[:200])

    print("== 4. 时段与预约 ==")
    # 使用随机远期日期，保证脚本可重复执行（同宠物同日会被去重规则正确拦截）
    import random

    rnd = random.Random()
    target = date.today() + timedelta(days=rnd.randint(5, 300))
    r = client.get(f"/api/v1/appointments/slots?appoint_date={target}", headers=cust_h)
    check("查询可预约时段", r.status_code == 200 and len(r.json()["data"]["slots"]) == 10,
          r.text[:200])

    idem = f"smoke-{int(datetime.now().timestamp())}"
    body = {"pet_id": pet_id, "service_type": "basic_bath",
            "appoint_date": str(target), "slot_time": "11:00",
            "remark": "冒烟测试", "idempotent_key": idem}
    r1 = client.post("/api/v1/appointments", headers=cust_h, json=body)
    check("提交预约", r1.status_code == 200, r1.text[:200])
    appt_id = r1.json()["data"]["id"]

    r2 = client.post("/api/v1/appointments", headers=cust_h, json=body)
    check("双入口幂等：重复提交不新增订单",
          r2.status_code == 200 and r2.json()["data"]["id"] == appt_id,
          f"{r2.status_code} {r2.text[:200]}")

    r = client.get("/api/v1/appointments", headers=cust_h)
    total = r.json()["data"]["total"]
    r3 = client.post("/api/v1/appointments", headers=cust_h, json={**body,
                                                                   "idempotent_key": idem + "-x"})
    check("同宠物同日重复预约被拦截", r3.status_code == 409, r3.text[:160])

    print("== 5. 状态机 ==")
    r = client.post(f"/api/v1/appointments/{appt_id}/status", headers=staff_h,
                    json={"status": "completed"})
    check("非法状态流转被拒绝（pending→completed）", r.status_code == 409, r.text[:160])

    r = client.post(f"/api/v1/appointments/{appt_id}/status", headers=staff_h,
                    json={"status": "confirmed"})
    check("pending→confirmed", r.status_code == 200, r.text[:160])
    r = client.post(f"/api/v1/appointments/{appt_id}/status", headers=staff_h,
                    json={"status": "arrived"})
    check("confirmed→arrived", r.status_code == 200, r.text[:160])
    r = client.post(f"/api/v1/appointments/{appt_id}/status", headers=staff_h,
                    json={"status": "arrived_give_up"})
    check("终止原因必填校验", r.status_code == 400, r.text[:160])
    r = client.post(f"/api/v1/appointments/{appt_id}/status", headers=staff_h,
                    json={"status": "arrived_give_up", "reason": "冒烟测试：宠主临时离开"})
    check("arrived→arrived_give_up", r.status_code == 200, r.text[:160])

    print("== 6. 风险判别 ==")
    # 用另一位宠主（刘先生）的旺财 —— 档案含攻击倾向 / 皮肤病 / 过敏史，必命中高风险
    r = client.post("/api/v1/auth/login", json={"username": "liu", "password": "123456"})
    check("宠主 liu 登录", r.status_code == 200, r.text[:160])
    liu_h = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
    liu_pets = client.get("/api/v1/pets", headers=liu_h).json()["data"]
    risk_pet = liu_pets[0]
    risk_date = target + timedelta(days=1)

    appt2 = client.post("/api/v1/appointments", headers=liu_h, json={
        "pet_id": risk_pet["id"],
        "service_type": "medicated_bath", "appoint_date": str(risk_date),
        "slot_time": "15:00", "idempotent_key": idem + "-risk",
    })
    check("风险预约创建", appt2.status_code == 200, appt2.text[:200])
    rid = appt2.json()["data"]["id"]
    r = client.get(f"/api/v1/risks/appointment/{rid}", headers=staff_h)
    ok_risk = r.status_code == 200
    check("获取风险报告", ok_risk, r.text[:200])
    if ok_risk:
        check("风险等级在合法枚举内",
              r.json()["data"]["risk_level"] in {"high", "low", "none"}, str(r.json()["data"]))
    r = client.get(f"/api/v1/appointments/{rid}", headers=cust_h)
    check("宠主无法查看他人预约（403）", r.status_code == 403, r.text[:160])
    r = client.post(f"/api/v1/risks/appointment/{rid}/confirm", headers=staff_h,
                    json={"handle_measure": "冒烟测试：已双人操作并佩戴防护"})
    check("店员复核确认", r.status_code == 200, r.text[:200])

    print("== 7. 门店配置校验 ==")
    r = client.put("/api/v1/settings", headers=mgr_h,
                   json={"setting_key": "default_slot_capacity", "setting_value": "2"})
    check("店长修改配置", r.status_code == 200, r.text[:200])
    r = client.put("/api/v1/settings", headers=mgr_h,
                   json={"setting_key": "default_slot_capacity", "setting_value": "999"})
    check("越界配置被拒绝", r.status_code == 400, r.text[:160])
    r = client.put("/api/v1/settings", headers=staff_h,
                   json={"setting_key": "default_slot_capacity", "setting_value": "3"})
    check("店员无配置权限（403）", r.status_code == 403, r.text[:160])
    client.put("/api/v1/settings", headers=mgr_h,
               json={"setting_key": "default_slot_capacity", "setting_value": "3"})

    print("== 8. 站内消息 ==")
    r = client.get("/api/v1/messages/unread-count", headers=cust_h)
    check("未读消息数", r.status_code == 200, r.text[:160])
    r = client.post("/api/v1/messages/read-all", headers=cust_h)
    check("全部已读", r.status_code == 200, r.text[:160])

    print("== 9. 报表 ==")
    r = client.get("/api/v1/report/summary", headers=mgr_h)
    ok_report = r.status_code == 200 and r.json()["code"] == 0
    check("报表概览", ok_report, r.text[:200])
    if ok_report:
        d = r.json()["data"]
        check("报表字段完整",
              all(k in d for k in ("total_orders", "no_show_rate", "repurchase_rate",
                                   "service_ratio", "staff_workload", "churn_pets")))
    r = client.get("/api/v1/report/export", headers=mgr_h)
    check("CSV 导出（店长）", r.status_code == 200 and len(r.content) > 50, r.text[:120])
    r = client.get("/api/v1/report/export", headers=staff_h)
    check("店员导出被拒绝（403）", r.status_code == 403)
    r = client.get("/api/v1/report/audit-logs", headers=mgr_h)
    check("审计日志查询", r.status_code == 200, r.text[:160])

    print("== 10. 越权防护 ==")
    me_id = client.get("/api/v1/auth/me", headers=cust_h).json()["data"]["id"]
    all_pets = client.get("/api/v1/pets", headers=staff_h).json()["data"]
    other_pets = [p for p in all_pets if p["user_id"] != me_id]
    if other_pets:
        r = client.get(f"/api/v1/pets/{other_pets[0]['id']}", headers=cust_h)
        check("宠主查看他人宠物被拒绝", r.status_code == 403, r.text[:160])
        r = client.put(f"/api/v1/pets/{other_pets[0]['id']}", headers=cust_h,
                       json={"name": "越权改名", "species": "dog", "gender": "male"})
        check("宠主修改他人宠物被拒绝", r.status_code == 403, r.text[:160])
    else:
        check("宠主越权访问防护（无他人宠物可测）", False, "测试数据不足")
    r = client.get("/api/v1/appointments", headers=cust_h)
    ids = {i["user_id"] for i in r.json()["data"]["items"]}
    check("宠主列表仅含本人预约", len(ids) <= 1 and (not ids or me_id in ids), str(ids))

    print("== 11. SLA 巡检 ==")
    r = client.post("/api/v1/appointments/sla/scan", headers=mgr_h)
    check("SLA 巡检可执行", r.status_code == 200, r.text[:160])

    print("== 12. 洗护记录 ==")
    r = client.get("/api/v1/wash-records", headers=staff_h)
    ok_wash = r.status_code == 200
    check("洗护记录列表", ok_wash, r.text[:200])
    r = client.get("/api/v1/wash-records/stats", headers=staff_h)
    check("洗护记录看板", r.status_code == 200 and "avg_minutes" in r.json()["data"], r.text[:200])
    r = client.get("/api/v1/wash-records", headers=cust_h)
    check("宠主可见自己的洗护记录", r.status_code == 200, r.text[:160])

    print("== 13. 排期视图 ==")
    r = client.get("/api/v1/schedule?days=3", headers=staff_h)
    ok_sched = r.status_code == 200 and len(r.json()["data"]["days"]) == 3
    check("排期视图（3 天 × 时段容量）", ok_sched, r.text[:200])
    if ok_sched:
        day = r.json()["data"]["days"][0]
        check("排期含时段与容量字段",
              all(k in day["slots"][0] for k in ("slot_time", "capacity", "used", "remain", "full")))
    r = client.get(f"/api/v1/schedule/staff-load?start={date.today()}&end={date.today() + timedelta(days=30)}",
                   headers=mgr_h)
    check("店员负载统计", r.status_code == 200, r.text[:160])

    print("== 14. 店长可见原始手机号 ==")
    r = client.get("/api/v1/users", headers=mgr_h)
    ok_users = r.status_code == 200
    check("店长用户列表", ok_users, r.text[:160])
    if ok_users:
        items = r.json()["data"]["items"]
        check("店长列表含原始手机号字段", any(i.get("phone") for i in items), str(items[:1]))
    r = client.get("/api/v1/users", headers=staff_h)
    check("店员访问用户列表被拒绝（403）", r.status_code == 403, r.text[:160])

    print("== 15. 多类型导出 ==")
    for export_type, label in (("summary", "经营概览"), ("appointments", "预约明细"),
                               ("wash", "洗护记录"), ("pets", "客户档案")):
        r = client.get(f"/api/v1/report/export?type={export_type}", headers=mgr_h)
        check(f"导出 {label}", r.status_code == 200 and len(r.content) > 30, r.text[:120])

    print("== 16. AI 对话助手（中心单 Agent + ReAct） ==")
    r = client.get("/api/v1/chat/capabilities", headers=cust_h)
    ok_cap = r.status_code == 200
    check("助手能力与工具清单", ok_cap, r.text[:200])
    if ok_cap:
        cap = r.json()["data"]
        check("宠主可见 13 个工具（含宠物之家 + 知识库检索）", len(cap["tools"]) == 13, str(len(cap["tools"])))
        check("架构声明为单 Agent + ReAct", "ReAct" in cap["architecture"])
    r = client.get("/api/v1/chat/capabilities", headers=mgr_h)
    check("店长可见 11 个工具（经营助理画像 + 知识库检索）", len(r.json()["data"]["tools"]) == 11, r.text[:160])

    def sse(message: str, headers: dict, session_id: int | None = None) -> list[dict]:
        import json as _json

        with client.stream("POST", "/api/v1/chat/message", headers=headers,
                           json={"content": message, "session_id": session_id}) as resp:
            events = []
            for line in resp.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload:
                    events.append(_json.loads(payload))
            return events

    # 使用独立会话，避免与其他用例共享「待确认动作」状态
    chat_session = client.post("/api/v1/chat/sessions", headers=cust_h,
                               json={"title": "冒烟会话"}).json()["data"]["id"]

    events = sse("明天还有哪些时段可以预约？", cust_h, chat_session)
    types = [e.get("type") for e in events]
    check("SSE 事件流包含 meta/intent/answer/end",
          "meta" in types and "intent" in types and "answer" in types and "end" in types,
          str(types[:12]))
    answer = "".join(e.get("delta", "") for e in events if e.get("type") == "answer")
    check("查时段返回中文回答", ("时段" in answer or "约满" in answer), answer[:120])
    check("SSE 结束后落库会话消息",
          client.get("/api/v1/chat/sessions", headers=cust_h).json()["data"].__len__() >= 1)

    events = sse(f"帮我给豆豆预约 {target} 11:00 洗澡", cust_h, chat_session)
    confirm_events = [e for e in events if e.get("type") == "confirm"]
    check("写操作进入二次确认闸门（不直接落库）", len(confirm_events) == 1,
          str([e.get("type") for e in events]))
    check("确认提示含宠物与时段",
          confirm_events and "豆豆" in confirm_events[0]["prompt"], str(confirm_events)[:200])

    created_before = client.get("/api/v1/appointments", headers=cust_h).json()["data"]["total"]
    events = sse("确认", cust_h, chat_session)
    created_after = client.get("/api/v1/appointments", headers=cust_h).json()["data"]["total"]
    answer = "".join(e.get("delta", "") for e in events if e.get("type") == "answer")
    check("确认后真正创建预约（走业务服务层）", created_after == created_before + 1,
          f"{created_before} -> {created_after}; {answer[:150]}")

    events = sse("取消预约 PG200001010000009999", cust_h, chat_session)
    answer = "".join(e.get("delta", "") for e in events if e.get("type") == "answer")
    check("不存在的单号在确认前就被友好拒绝", "没有找到" in answer and
          not any(e.get("type") == "confirm" for e in events), answer[:150])

    events = sse("你好呀", cust_h, chat_session)
    answer = "".join(e.get("delta", "") for e in events if e.get("type") == "answer")
    check("闲聊有友好回复", len(answer) > 5, answer[:120])

    r = client.get(f"/api/v1/chat/sessions/{chat_session}/messages", headers=cust_h)
    check("会话历史接口", r.status_code == 200 and len(r.json()["data"]["messages"]) >= 6, r.text[:160])
    r = client.delete(f"/api/v1/chat/sessions/{chat_session}", headers=cust_h)
    check("会话逻辑删除", r.status_code == 200)
    r = client.get(f"/api/v1/chat/sessions/{chat_session}/messages", headers=cust_h)
    check("已删除会话不可访问（404）", r.status_code == 404, r.text[:120])

    print("== 17. 敏感信息脱敏（日志层） ==")
    from app.utils.logger import mask_sensitive

    check("18 位预约单号不被误脱敏",
          "PG2026101411000033" in mask_sensitive("PG2026101411000033 已提交"),
          mask_sensitive("PG2026101411000033 已提交"))
    check("手机号脱敏为 138****5678",
          "138****5678" in mask_sensitive("联系电话 13812345678"),
          mask_sensitive("联系电话 13812345678"))
    check("身份证仅保留末位校验码可见",
          "11010119900307123*" in mask_sensitive("身份证 110101199003071234"),
          mask_sensitive("身份证 110101199003071234"))

    print("== 18. 洗护记录补录 ==")
    wash_list = client.get("/api/v1/wash-records", headers=staff_h).json()["data"]["items"]
    if not wash_list:
        # 库里可能没有历史洗护记录（演示数据被清理过）：自己造一笔「已完成」的预约 ——
        # 洗护记录在预约完成时归档（appointment_service._archive_wash_record）。
        # 用例只依赖自己造的数据，别依赖「库里恰好有已完成预约」。
        made = client.post("/api/v1/appointments", headers=cust_h, json={
            "pet_id": pet_id, "service_type": "basic_bath",
            "appoint_date": str(target), "slot_time": "10:00",
            "remark": "冒烟补录用例", "idempotent_key": f"{idem}-wash",
        })
        made_id = made.json()["data"]["id"] if made.status_code == 200 else None
        if made_id:
            for status in ("confirmed", "arrived", "in_service", "completed"):
                client.post(f"/api/v1/appointments/{made_id}/status", headers=staff_h,
                            json={"status": status})
            wash_list = client.get("/api/v1/wash-records", headers=staff_h).json()["data"]["items"]
    if wash_list:
        wid = wash_list[0]["id"]
        r = client.put(f"/api/v1/wash-records/{wid}", headers=staff_h, json={
            "skin_condition": "冒烟测试：洗后皮肤无泛红",
            "products": "低敏沐浴露",
            "staff_note": "配合度良好",
        })
        check("店员补录洗护记录", r.status_code == 200, r.text[:160])
        r = client.put(f"/api/v1/wash-records/{wid}", headers=cust_h, json={"products": "越权修改"})
        check("宠主修改洗护记录被拒绝（403）", r.status_code == 403, r.text[:160])
    else:
        check("洗护记录补录（无数据可测）", False, "缺少已完成预约")

    print("== 19. 排期与店长原始手机号 ==")
    r = client.get("/api/v1/schedule?days=2", headers=staff_h)
    check("排期接口返回 2 天", r.status_code == 200 and len(r.json()["data"]["days"]) == 2, r.text[:160])
    r = client.get("/api/v1/schedule?days=40", headers=staff_h)
    check("排期天数超上限被拒绝（422）", r.status_code == 422, r.text[:120])

    print("== 20. 多角色 Agent：工具画像与权限（V5） ==")
    r = client.get("/api/v1/chat/capabilities", headers=cust_h)
    check("宠主画像为「宠主自助助手」", r.json()["data"]["role_profile"] == "宠主自助助手",
          r.text[:160])
    r = client.get("/api/v1/chat/capabilities", headers=staff_h)
    ok_staff_cap = r.status_code == 200
    check("店员画像为「店员运营助理」", ok_staff_cap and r.json()["data"]["role_profile"] == "店员运营助理",
          r.text[:160])
    staff_tools = set(t["name"] for t in r.json()["data"]["tools"]) if ok_staff_cap else set()
    check("店员可见 11 个工具", len(staff_tools) == 11, str(sorted(staff_tools)))
    check("店员不可见店长专属工具（审计 / 改配置 / 启停账号）",
          not (staff_tools & {"query_audit_trail", "update_store_setting", "toggle_user_status"}),
          str(sorted(staff_tools)))

    r = client.get("/api/v1/chat/capabilities", headers=mgr_h)
    mgr_tools = set(t["name"] for t in r.json()["data"]["tools"])
    check("店长画像为「店长经营助理」", r.json()["data"]["role_profile"] == "店长经营助理", r.text[:160])
    check("店长可见 11 个工具", len(mgr_tools) == 11, str(sorted(mgr_tools)))
    check("店长可见店长专属工具",
          {"query_audit_trail", "update_store_setting", "toggle_user_status"} <= mgr_tools,
          str(sorted(mgr_tools)))

    r = client.get("/api/v1/chat/tool-profile", headers=mgr_h)
    check("工具画像查询（店长）", r.status_code == 200 and r.json()["data"]["pool_size"] == 30, r.text[:160])
    r = client.get("/api/v1/chat/tool-profile", headers=staff_h)
    check("工具画像查询店员被拒（403）", r.status_code == 403, r.text[:120])

    print("== 21. 多角色 Agent：越权拒绝 ==")
    mgr_chat = client.post("/api/v1/chat/sessions", headers=mgr_h, json={"title": "店长冒烟"}).json()["data"]["id"]
    staff_chat = client.post("/api/v1/chat/sessions", headers=staff_h, json={"title": "店员冒烟"}).json()["data"]["id"]

    events = sse("最近谁改过门店配置？", staff_h, staff_chat)
    answer = "".join(e.get("delta", "") for e in events if e.get("type") == "answer")
    check("店员请求审计日志被拒绝（无该工具）",
          not any(e.get("type") == "action" for e in events) or "权限" in answer, answer[:150])

    events = sse("把门店的时段接待容量改成 5", mgr_h, mgr_chat)
    confirm_events = [e for e in events if e.get("type") == "confirm"]
    check("店长改配置进入二次确认闸门", len(confirm_events) <= 1 and
          (bool(confirm_events) or "配置" in "".join(e.get("delta", "") for e in events
                                                    if e.get("type") == "answer")),
          str([e.get("type") for e in events]))

    print("== 22. 多角色 Agent：店员推进订单状态 ==")
    # 远期日期独立于上方用例：脚本重复执行时不会与既有预约抢占同一时段
    target2 = target + timedelta(days=400 + rnd.randint(0, 600))
    pet_for_staff = client.get("/api/v1/pets", headers=cust_h).json()["data"][0]["id"]
    created = client.post("/api/v1/appointments", headers=cust_h, json={
        "pet_id": pet_for_staff, "service_type": "basic_bath", "appoint_date": str(target2),
        "slot_time": "16:00", "idempotent_key": idem + "-v5advance",
    })
    ok_create = created.status_code == 200
    check("造一笔待确认预约", ok_create, created.text[:200])
    if ok_create:
        order_no = created.json()["data"]["order_no"]

        events = sse(f"{order_no} 这单确认一下", staff_h, staff_chat)
        check("推进状态先出确认卡（不直接改库）",
              any(e.get("type") == "confirm" for e in events),
              str([e.get("type") for e in events]))
        still = client.get(f"/api/v1/appointments/{created.json()['data']['id']}", headers=staff_h)
        check("未确认前订单状态未变化", still.json()["data"]["status"] == "pending",
              still.json()["data"]["status"])

        events = sse("确认", staff_h, staff_chat)
        answer = "".join(e.get("delta", "") for e in events if e.get("type") == "answer")
        after = client.get(f"/api/v1/appointments/{created.json()['data']['id']}", headers=staff_h)
        check("确认后状态真实变更为 confirmed", after.json()["data"]["status"] == "confirmed",
              f"{after.json()['data']['status']} | {answer[:120]}")

        logs = client.get("/api/v1/report/audit-logs?module=appointment", headers=mgr_h).json()["data"]
        check("状态变更写入审计日志", logs["total"] > 0, str(logs["total"]))

    print("== 23. 多角色 Agent：店长改配置范围校验 ==")
    before = client.get("/api/v1/settings", headers=mgr_h).json()["data"]
    cap_before = next(x["setting_value"] for x in before if x["setting_key"] == "default_slot_capacity")

    events = sse("把门店的时段接待容量改成 999", mgr_h, mgr_chat)
    answer = "".join(e.get("delta", "") for e in events if e.get("type") == "answer")
    confirmed = any(e.get("type") == "confirm" for e in events)
    if confirmed:
        events2 = sse("确认", mgr_h, mgr_chat)
        answer += "".join(e.get("delta", "") for e in events2 if e.get("type") == "answer")
    cap_after = next(x["setting_value"] for x in client.get("/api/v1/settings", headers=mgr_h).json()["data"]
                     if x["setting_key"] == "default_slot_capacity")
    check("越界配置被拒绝，配置值未变", cap_after == cap_before,
          f"{cap_before} -> {cap_after} | {answer[:150]}")

    print("== 24. 多角色 Agent：手机号可见性 ==")
    r = client.get("/api/v1/chat/capabilities", headers=staff_h)
    events = sse("帮我查一下客户张女士的档案", staff_h, staff_chat)
    answer = "".join(e.get("delta", "") for e in events if e.get("type") == "answer")
    if any(e.get("type") == "action" for e in events):
        check("店员查询客户档案返回脱敏手机号",
              "****" in answer or "138" not in answer, answer[:200])
    else:
        check("店员查询客户档案（降级为追问）", "客户" in answer or "档案" in answer, answer[:200])

    print("== 25. 代客预约契约（V5 修复回归） ==")
    r = client.post("/api/v1/appointments/staff", headers=staff_h, json={
        "phone": "13900002222", "pet_id": 0, "pet_name": "契约测试犬",
        "service_type": "basic_bath", "appoint_date": str(target2 + timedelta(days=1)),
        "slot_time": "11:00", "idempotent_key": idem + "-staff-pet0",
    })
    check("代客预约：无档案时 pet_id=0 可下单（原 422 已修复）", r.status_code == 200, r.text[:200])
    r = client.post("/api/v1/appointments/staff", headers=staff_h, json={
        "phone": "13900002222", "service_type": "basic_bath",
        "appoint_date": str(target2 + timedelta(days=2)), "slot_time": "11:00",
        "idempotent_key": idem + "-staff-neither",
    })
    check("代客预约：既无 pet_id 也无 pet_name 被拒绝（422）", r.status_code == 422, r.text[:200])

    r = client.delete(f"/api/v1/chat/sessions/{mgr_chat}", headers=mgr_h)
    client.delete(f"/api/v1/chat/sessions/{staff_chat}", headers=staff_h)

    print("== 26. V6：时段行锁（容量边界 + 并发防超卖） ==")
    # 把时段容量临时压到 1，最容易暴露 check-then-act 竞态
    client.put("/api/v1/settings", headers=mgr_h,
               json={"setting_key": "default_slot_capacity", "setting_value": "1"})
    lock_day = target2 + timedelta(days=60)

    first = client.post("/api/v1/appointments", headers=cust_h, json={
        "pet_id": pet_for_staff, "service_type": "basic_bath",
        "appoint_date": str(lock_day), "slot_time": "09:00",
        "idempotent_key": idem + "-lock-a",
    })
    second = client.post("/api/v1/appointments/staff", headers=staff_h, json={
        "phone": "13911110000", "pet_name": "边界犬", "service_type": "basic_bath",
        "appoint_date": str(lock_day), "slot_time": "09:00",
        "idempotent_key": idem + "-lock-b",
    })
    check("容量 1 时首单成功、次单被容量拒绝（409）",
          first.status_code == 200 and second.status_code == 409,
          f"{first.status_code}/{second.status_code} {second.text[:120]}")

    # 真并发：6 个不同客户抢同一时段的最后 1 个名额，必须恰好成功 1 单
    from concurrent.futures import ThreadPoolExecutor

    def _race(i: int):
        return client.post("/api/v1/appointments/staff", headers=staff_h, json={
            "phone": f"1392000{i:04d}", "pet_name": f"并发犬{i}", "service_type": "basic_bath",
            "appoint_date": str(lock_day), "slot_time": "10:00",
            "idempotent_key": idem + f"-race-{i}",
        }).status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        codes = list(pool.map(_race, range(6)))
    check("并发 6 单抢容量 1：恰好 1 单成功，其余全部 409（行锁生效）",
          codes.count(200) == 1 and codes.count(409) == 5, str(codes))

    client.put("/api/v1/settings", headers=mgr_h,
               json={"setting_key": "default_slot_capacity", "setting_value": "3"})

    print("== 27. V6：RAG 知识依据落库 ==")
    r = client.get(f"/api/v1/risks/appointment/{rid}", headers=staff_h)
    ok_kb = r.status_code == 200
    refs = (r.json()["data"].get("knowledge_refs") or []) if ok_kb else []
    check("风险报告带洗护安全知识依据", len(refs) > 0, str(refs)[:200])
    check("知识依据含可解释命中原因",
          bool(refs) and bool(refs[0].get("matched")), str(refs[:1])[:200])
    check("知识依据含正文与来源", bool(refs) and bool(refs[0].get("content"))
          and bool(refs[0].get("source")), str(refs[:1])[:160])

    print("== 28. V6：知识库接口权限 ==")
    r = client.get("/api/v1/knowledge", headers=staff_h)
    check("店员可读洗护安全知识库", r.status_code == 200 and r.json()["data"]["total"] >= 10,
          r.text[:160])
    r = client.get("/api/v1/knowledge", headers=cust_h)
    check("宠主访问知识库被拒（403）", r.status_code == 403, r.text[:120])
    r = client.get("/api/v1/knowledge/meta", headers=staff_h)
    staff_kb_meta = r.json().get("data") if r.status_code == 200 else {}
    check("店员可查看知识库状态且无管理权限",
          r.status_code == 200 and staff_kb_meta.get("can_manage") is False,
          r.text[:180])
    r = client.get("/api/v1/knowledge/meta", headers=mgr_h)
    manager_kb_meta = r.json().get("data") if r.status_code == 200 else {}
    check("店长拥有上传/删除/重建权限",
          r.status_code == 200 and manager_kb_meta.get("can_manage") is True
          and {"upload", "delete", "rebuild"}.issubset(
              set((manager_kb_meta.get("permissions") or {}).get("manager") or [])
          ), r.text[:220])
    r = client.get("/api/v1/knowledge/documents", headers=staff_h)
    check("店员可查看上传文档与任务", r.status_code == 200 and "items" in r.json()["data"], r.text[:160])
    r = client.post("/api/v1/knowledge/index/rebuild", headers=staff_h, json={})
    check("店员不能重建知识库索引（403）", r.status_code == 403, r.text[:140])
    r = client.post(
        "/api/v1/knowledge/documents/upload", headers=staff_h,
        files={"files": ("staff-forbidden.txt", b"forbidden", "text/plain")},
        data={"strategy": "fixed", "chunk_size": "500", "chunk_overlap": "50"},
    )
    check("店员不能上传知识文档（403）", r.status_code == 403, r.text[:140])

    print("== 29. V6：定时任务（清单 / 权限 / 手动触发） ==")
    r = client.get("/api/v1/tasks", headers=mgr_h)
    ok_tasks = r.status_code == 200
    check("店长可查看定时任务清单", ok_tasks and len(r.json()["data"]["items"]) == 7, r.text[:200])
    check("任务清单含 SLA 巡检与提醒类任务",
          ok_tasks and {"sla_scan", "vaccine_reminder", "repurchase_reminder"} <=
          {i["name"] for i in r.json()["data"]["items"]}, r.text[:200])
    r = client.get("/api/v1/tasks", headers=staff_h)
    check("店员访问任务清单被拒（403）", r.status_code == 403, r.text[:120])
    r = client.post("/api/v1/tasks/sla_scan/run", headers=mgr_h)
    check("手动触发 SLA 巡检成功", r.status_code == 200 and r.json()["data"]["status"] == "success",
          r.text[:200])
    r = client.post("/api/v1/tasks/not_exist/run", headers=mgr_h)
    check("触发不存在的任务被拒绝（404）", r.status_code == 404, r.text[:120])

    print("== 30. V6：疫苗临期提醒真实发送 + 当天去重 ==")
    due = date.today() + timedelta(days=3)
    r = client.post(f"/api/v1/pets/{pet_id}/vaccines", headers=cust_h, json={
        "record_type": "vaccine", "name": "狂犬疫苗", "record_date": str(date.today()),
        "next_date": str(due),
    })
    check("登记一条 3 天后到期的疫苗记录", r.status_code == 200, r.text[:160])
    vac_id = r.json()["data"]["id"]

    # 按「消息 id 集合」做差集，而不是数第 1 页里有多少条：
    # 列表按 id 倒序取前 50 条，新提醒进来会把最旧那条顶出窗口，
    # 反复跑冒烟后「窗口内数量」可能不变，从而假失败。
    def _remind_map():
        resp = client.get("/api/v1/messages?page=1&size=50", headers=cust_h)
        return {m["id"]: m.get("biz_id") for m in resp.json()["data"]["items"]
                if m.get("msg_type") == "vaccine_remind"}

    before_ids = set(_remind_map())
    r = client.post("/api/v1/tasks/vaccine_reminder/run", headers=mgr_h)
    ok_run = r.status_code == 200 and r.json()["data"]["status"] == "success"
    after_map = _remind_map()
    new_ids = set(after_map) - before_ids
    check("疫苗临期提醒任务真实发出站内信", ok_run and len(new_ids) == 1,
          f"{len(before_ids)} -> {len(after_map)} | {r.text[:160]}")
    check("新提醒指向刚登记的这条记录",
          len(new_ids) == 1 and after_map[next(iter(new_ids))] == vac_id,
          f"vac_id={vac_id} new={new_ids}")

    client.post("/api/v1/tasks/vaccine_reminder/run", headers=mgr_h)
    after_second_ids = set(_remind_map())
    check("同日重复执行不重复发送（幂等去重）", not (after_second_ids - after_map.keys()),
          f"{sorted(after_map.keys())} -> {sorted(after_second_ids)}")

    print("== 31. V6：复购回访提醒任务 ==")
    r = client.post("/api/v1/tasks/repurchase_reminder/run", headers=mgr_h)
    ok_re = r.status_code == 200 and r.json()["data"]["status"] == "success"
    check("复购回访任务可执行且带口径参数", ok_re and "churn_days" in r.json()["data"]["data"],
          r.text[:200])

    print("== 32. V6：会话清理与锁行清理任务 ==")
    r = client.post("/api/v1/tasks/session_cleanup/run", headers=mgr_h)
    check("AI 会话清理任务可执行", r.status_code == 200 and r.json()["data"]["status"] == "success",
          r.text[:160])
    r = client.post("/api/v1/tasks/lock_cleanup/run", headers=mgr_h)
    check("时段锁行清理任务可执行", r.status_code == 200 and r.json()["data"]["status"] == "success",
          r.text[:160])

    print("== 33. V7.1 寄养：前置数据 + 房型与字典 ==")
    # 寄养日期取近期（贴合真实场景）；同时用独立测试房避免与演示房 / 历史运行互相抢房
    board_base = rnd.randint(30, 120)
    board_in = (date.today() + timedelta(days=board_base)).isoformat()
    board_out = (date.today() + timedelta(days=board_base + 3)).isoformat()

    # 疫苗硬门槛：登记一条**覆盖入住日**的有效疫苗记录（校验口径就是「入住当天仍有效」）
    r = client.post(f"/api/v1/pets/{pet_id}/vaccines", headers=cust_h, json={
        "record_type": "vaccine", "name": "狂犬疫苗", "record_date": str(date.today()),
        "next_date": str(date.fromisoformat(board_in) + timedelta(days=60)),
    })
    check("寄养前置：登记覆盖入住日的疫苗记录", r.status_code == 200, r.text[:160])

    r = client.post("/api/v1/boarding/rooms", headers=mgr_h, json={
        "room_no": f"T{rnd.randint(1000, 9999)}", "room_type": "vip", "name": "回归测试套房",
        "species_limit": "all", "weight_limit": 40, "ratio_percent": 100, "capacity": 1,
    })
    check("店长新增测试房型（隔离测试数据）", r.status_code == 200, r.text[:200])
    test_room = r.json()["data"] if r.status_code == 200 else None
    r = client.get("/api/v1/boarding/rooms", headers=cust_h)
    ok_rooms = r.status_code == 200
    check("寄养房型列表可读", ok_rooms and len(r.json()["data"]) >= 5, r.text[:200])
    rooms = r.json()["data"] if ok_rooms else []
    standard = next((x for x in rooms if x["room_type"] == "standard"), None)
    vip = next((x for x in rooms if x["room_type"] == "vip"), None)
    check("房型含系数与房态标签",
          bool(standard) and standard["ratio_percent"] == 100 and "status_label" in standard,
          str(standard)[:200])

    r = client.get("/api/v1/boarding/meta", headers=staff_h)
    ok_meta = r.status_code == 200
    check("寄养字典含状态与定价规则",
          ok_meta and len(r.json()["data"]["order_status"]) == 11 and "min_nights" in r.json()["data"]["rules"],
          r.text[:200])

    print("== 34. V7.1 寄养：定价引擎（房型系数 / 长住折扣）==")
    quote_room_id = (test_room or standard)["id"]
    r = client.get(
        f"/api/v1/boarding/quote?pet_id={pet_id}&room_id={quote_room_id}"
        f"&check_in_date={board_in}&check_out_date={board_out}", headers=cust_h)
    ok_q = r.status_code == 200
    q = r.json()["data"] if ok_q else {}
    check("费用预估返回三要素与总额",
          ok_q and q.get("room_ratio_percent") == 100 and q.get("total_cents", 0) > 0, str(q)[:200])
    check("日费 × 晚数 = 小计", ok_q and q["daily_fee_cents"] * q["nights"] == q["subtotal_cents"],
          str(q)[:200])

    long_out = (date.fromisoformat(board_in) + timedelta(days=18)).isoformat()
    r = client.get(
        f"/api/v1/boarding/quote?pet_id={pet_id}&room_id={quote_room_id}"
        f"&check_in_date={board_in}&check_out_date={long_out}", headers=cust_h)
    ql = r.json()["data"]
    check("长住 18 晚触发折扣（90%）",
          ql["nights"] == 18 and ql["discount_percent"] == 90
          and ql["discounted_cents"] == ql["subtotal_cents"] * 90 // 100, str(ql)[:220])

    # 对比基准：找一间 ratio 200 的房（不能按 room_type 找 —— 回归测试房也是 vip 型）
    ratio200 = next((x for x in rooms if x["ratio_percent"] == 200), None)
    r = client.get(
        f"/api/v1/boarding/quote?pet_id={pet_id}&room_id={ratio200['id']}"
        f"&check_in_date={board_in}&check_out_date={board_out}", headers=cust_h)
    check("VIP 房型系数 200% 生效",
          r.json()["data"]["daily_fee_cents"] == q["daily_fee_cents"] * 2,
          f"{q['daily_fee_cents']} -> {r.json()['data']['daily_fee_cents']}")

    r = client.get(
        f"/api/v1/boarding/quote?pet_id={pet_id}&room_id={quote_room_id}"
        f"&check_in_date={board_in}&check_out_date={board_out}"
        f"&dropoff_method=pickup&pickup_back_method=return&feeding_plan=premium", headers=cust_h)
    qx = r.json()["data"]
    check("上门接 + 送宠到家两段费用都计入（可同时选）",
          qx["pickup_fee_cents"] > 0 and qx["return_fee_cents"] > 0
          and qx["shipping_fee_cents"] == qx["pickup_fee_cents"] + qx["return_fee_cents"],
          str(qx)[:220])
    check("接送费与升级粮加价计入总额",
          qx["shipping_fee_cents"] > 0 and qx["feeding_fee_cents"] > 0
          and qx["total_cents"] > q["total_cents"], str(qx)[:240])

    print("== 35. V7.1 寄养：下单硬门槛（疫苗 / 条款 / 晚数）==")
    # 现造一只「确定没有任何疫苗记录」的宠物，用它验证硬门槛（不能借用可能已有疫苗的宠物）
    r = client.post("/api/v1/pets", headers=cust_h, json={
        "name": "无疫苗犬", "species": "dog", "gender": "male", "weight": 8.0, "sterilized": 1,
    })
    nova_pet_id = r.json()["data"]["id"] if r.status_code == 200 else pet_id
    r = client.post("/api/v1/boarding/orders", headers=cust_h, json={
        "pet_id": nova_pet_id, "room_id": quote_room_id,
        "check_in_date": board_in, "check_out_date": board_out,
        "terms_confirmed": True, "idempotent_key": idem + "-board-nova",
    })
    check("无有效疫苗记录被拒绝（硬门槛）", r.status_code in (400, 422), r.text[:200])

    r = client.post("/api/v1/boarding/orders", headers=cust_h, json={
        "pet_id": pet_id, "room_id": quote_room_id,
        "check_in_date": board_in, "check_out_date": board_out,
        "terms_confirmed": False, "idempotent_key": idem + "-board-noterms",
    })
    check("未确认寄养条款被拒绝", r.status_code in (400, 422), r.text[:200])

    r = client.post("/api/v1/boarding/orders", headers=cust_h, json={
        "pet_id": pet_id, "room_id": quote_room_id,
        "check_in_date": board_in, "check_out_date": board_in,
        "terms_confirmed": True, "idempotent_key": idem + "-board-same",
    })
    check("离店不晚于入住被拒绝", r.status_code in (400, 422), r.text[:200])

    print("== 36. V7.1 寄养：下单 / 房态冲突 / 幂等 ==")
    body = {
        "pet_id": pet_id, "room_id": quote_room_id,
        "check_in_date": board_in, "check_out_date": board_out,
        "feeding_plan": "self", "dropoff_method": "pickup", "pickup_back_method": "return",
        "shipping_address": "幸福路 1 号", "shipping_slot": "10:00-12:00",
        "emergency_contact": "张女士", "emergency_phone": "13800001111",
        "medical_authorized": True, "terms_confirmed": True,
        "care_items": [
            {"item_type": "medication", "content": "关节营养片 1 粒", "frequency": "每日 1 次", "need_staff": True},
            {"item_type": "taboo", "content": "禁止与其他犬只同区活动", "need_staff": False},
        ],
        "idempotent_key": idem + "-board-1",
    }
    r = client.post("/api/v1/boarding/orders", headers=cust_h, json=body)
    ok_b = r.status_code == 200
    check("寄养下单成功（含接送与照护计划）", ok_b, r.text[:220])
    board_id = r.json()["data"]["id"] if ok_b else None
    board_no = r.json()["data"]["order_no"] if ok_b else ""
    check("下单返回费用明细与单号",
          ok_b and board_no.startswith("BG") and r.json()["data"]["total_amount"] > 0,
          r.text[:200])

    r2 = client.post("/api/v1/boarding/orders", headers=cust_h, json=body)
    check("同一幂等键重复提交返回同一单", r2.status_code == 200
          and r2.json()["data"]["id"] == board_id, r2.text[:160])

    r3 = client.post("/api/v1/boarding/orders", headers=cust_h, json={
        **body, "idempotent_key": idem + "-board-2",
    })
    check("同一房间同区间第二单被房态拒绝（409）", r3.status_code == 409, r3.text[:200])

    if board_id:
        r = client.get(f"/api/v1/boarding/orders/{board_id}", headers=cust_h)
        detail = r.json()["data"]
        check("详情含照护计划（用药 + 禁忌）", len(detail["care_plans"]) == 2, str(detail.get("care_plans"))[:200])

    print("== 37. V7.1 寄养：状态机全流程与房态联动 ==")
    if board_id:
        r = client.post(f"/api/v1/boarding/orders/{board_id}/status", headers=staff_h,
                        json={"target_status": "completed"})
        check("待确认直接跳到完成被拒绝（409）", r.status_code == 409, r.text[:160])

        for target, label in (("confirmed", "确认"), ("waiting_checkin", "待入住")):
            r = client.post(f"/api/v1/boarding/orders/{board_id}/status", headers=staff_h,
                            json={"target_status": target})
            check(f"店员推进到「{label}」", r.status_code == 200, r.text[:160])

        r = client.post(f"/api/v1/boarding/orders/{board_id}/status", headers=staff_h,
                        json={"target_status": "checked_in", "checkin_note": "健康初检正常，皮肤有无异常"})
        check("办理入住成功", r.status_code == 200, r.text[:160])

        r = client.get("/api/v1/boarding/rooms", headers=staff_h)
        my_room = next((x for x in r.json()["data"] if x["id"] == quote_room_id), {})
        check("入住后房态转为占用中", my_room.get("status") == "occupied", str(my_room)[:160])

        r = client.post(f"/api/v1/boarding/orders/{board_id}/care-logs", headers=staff_h, json={
            "eating": "正常，吃完", "drinking": "正常", "stool": "2 次正常",
            "spirit": "活泼", "activity": "遛放 3 次",
            "photos": ["/static/board/demo1.jpg"], "sop_checked": ["喂食", "换水", "拍照"],
        })
        check("填写照护日志（正常）", r.status_code == 200, r.text[:160])

        r = client.post(f"/api/v1/boarding/orders/{board_id}/care-logs", headers=staff_h, json={
            "eating": "偏少", "abnormal": True, "abnormal_note": "下午出现轻微呕吐，已观察并联系医生",
        })
        check("填写异常照护日志", r.status_code == 200, r.text[:160])
        r = client.get("/api/v1/messages?page=1&size=20", headers=cust_h)
        types = [m["msg_type"] for m in r.json()["data"]["items"]]
        check("照护日报与异常提醒均已推送宠主",
              "boarding_log" in types and "boarding_abnormal" in types, str(types)[:200])

        r = client.post(f"/api/v1/boarding/orders/{board_id}/status", headers=staff_h,
                        json={"target_status": "cancelled"})
        check("寄养中无法直接取消（409）", r.status_code == 409, r.text[:160])

        # V8.4.9 提前接回：宠主申请 → 店员/店长审核（不再由店员直接改状态）
        early_date = (date.today() + timedelta(days=1)).isoformat()
        r = client.post(f"/api/v1/boarding/orders/{board_id}/early-pickup", headers=cust_h,
                        json={"expect_pickup_date": early_date, "reason": "冒烟：行程有变"})
        early_id = r.json()["data"]["id"] if r.status_code == 200 else None
        check("宠主可申请提前接回", r.status_code == 200 and early_id, r.text[:160])
        r = client.post(f"/api/v1/boarding/orders/{board_id}/early-pickup", headers=cust_h,
                        json={"expect_pickup_date": early_date, "reason": "重复"})
        check("同单不允许重复申请（400）", r.status_code == 400, r.text[:160])
        r = client.get("/api/v1/boarding/early-pickups?status=pending", headers=staff_h)
        pend = [x for x in r.json()["data"] if x["order_id"] == board_id]
        check("店员能看到待审核的提前接回申请", len(pend) == 1, str(pend)[:160])
        # 先驳回：订单状态不变
        r = client.post(f"/api/v1/boarding/early-pickups/{early_id}/review", headers=staff_h,
                        json={"approve": False, "note": "当日接送已满"})
        check("驳回提前接回申请", r.status_code == 200 and r.json()["data"]["status"] == "rejected",
              r.text[:160])
        r = client.get(f"/api/v1/boarding/orders/{board_id}", headers=staff_h)
        check("驳回后订单状态不变", r.json()["data"]["status"] == "checked_in", r.text[:160])
        for target in ("waiting_pickup", "completed"):
            r = client.post(f"/api/v1/boarding/orders/{board_id}/status", headers=staff_h,
                            json={"target_status": target})
            check(f"推进到「{target}」", r.status_code == 200, r.text[:160])

        r = client.post(f"/api/v1/boarding/orders/{board_id}/status", headers=staff_h,
                        json={"target_status": "early_pickup", "reason": "已完成的单不可再变更"})
        check("终态不可再流转（409）", r.status_code == 409, r.text[:160])

        r = client.get("/api/v1/boarding/rooms", headers=staff_h)
        my_room = next((x for x in r.json()["data"] if x["id"] == quote_room_id), {})
        check("退房后房态转「清洁中」（待消杀）", my_room.get("status") == "cleaning", str(my_room)[:160])

        r = client.patch(f"/api/v1/boarding/rooms/{quote_room_id}/status", headers=mgr_h,
                         json={"status": "idle"})
        check("店长确认消杀后转空闲", r.status_code == 200 and r.json()["data"]["status"] == "idle",
              r.text[:160])

    print("== 38. V7.1 寄养：接送任务 / 延期 ==")
    if board_id:
        r = client.get("/api/v1/boarding/pickup-tasks", headers=staff_h)
        tasks = r.json()["data"]
        mine_tasks = [t for t in tasks if t["order_id"] == board_id]
        check("上门接 + 送宠到家各生成一条接送任务", len(mine_tasks) == 2,
              str([(t["task_type_label"], t["status"]) for t in mine_tasks])[:200])
        check("接送任务类型覆盖 pickup 与 return",
              {t["task_type"] for t in mine_tasks} == {"pickup", "return"}, str(mine_tasks)[:200])
        if tasks:
            tid = tasks[0]["id"]
            for expect in ("departed", "picked", "arrived"):
                r = client.post(f"/api/v1/boarding/pickup-tasks/{tid}/advance", headers=staff_h,
                                json={"sign_off_by": "张女士"} if expect == "arrived" else {})
                check(f"接送任务推进到「{expect}」",
                      r.status_code == 200 and r.json()["data"]["status"] == expect, r.text[:160])
            r = client.post(f"/api/v1/boarding/pickup-tasks/{tid}/advance", headers=staff_h, json={})
            check("接送任务终态不可再推进（409）", r.status_code == 409, r.text[:160])

    # 另造一单用于验证延期：再开一间独立测试房，避免与主用例抢同一房同一区间
    r = client.post("/api/v1/boarding/rooms", headers=mgr_h, json={
        "room_no": f"T{rnd.randint(1000, 9999)}", "room_type": "standard", "name": "回归测试房二",
        "species_limit": "all", "weight_limit": 40, "ratio_percent": 100, "capacity": 1,
    })
    room2 = r.json()["data"] if r.status_code == 200 else standard
    r = client.post("/api/v1/boarding/orders", headers=cust_h, json={
        "pet_id": pet_id, "room_id": room2["id"],
        "check_in_date": board_in, "check_out_date": board_out,
        "terms_confirmed": True, "idempotent_key": idem + "-board-extend",
    })
    ok_ext = r.status_code == 200
    check("再下一单用于延期验证", ok_ext, r.text[:200])
    if ok_ext:
        ext_id = r.json()["data"]["id"]
        r = client.post(f"/api/v1/boarding/orders/{ext_id}/extend", headers=cust_h, json={
            "check_out_date": (date.fromisoformat(board_out) + timedelta(days=3)).isoformat(),
        }, )
        check("延期成功且费用重算", r.status_code == 200 and r.json()["data"]["nights"] == 6,
              r.text[:200])
        r = client.post(f"/api/v1/boarding/orders/{ext_id}/extend", headers=cust_h, json={
            "check_out_date": board_in,
        })
        check("缩短日期被拒绝", r.status_code in (400, 422), r.text[:160])

        # 提前接回「通过」路径：用**独立房间**再开一单（不能动 room2，后面要用它验证房态冲突）
        r = client.post("/api/v1/boarding/rooms", headers=staff_h, json={
            "room_no": f"Z{rnd.randint(1000, 9999)}", "room_type": "standard", "name": "提前接回测试房",
            "species_limit": "all", "weight_limit": 20, "ratio_percent": 100, "capacity": 1,
        })
        room3 = r.json()["data"]
        r = client.post("/api/v1/boarding/orders", headers=cust_h, json={
            "pet_id": pet_id, "room_id": room3["id"],
            "check_in_date": board_in, "check_out_date": board_out,
            "terms_confirmed": True, "idempotent_key": idem + "-early",
        })
        early_oid = r.json()["data"]["id"] if r.status_code == 200 else None
        check("提前接回验证单已创建", r.status_code == 200 and early_oid, r.text[:200])
        for target in ("confirmed", "waiting_checkin", "checked_in"):
            client.post(f"/api/v1/boarding/orders/{early_oid}/status", headers=staff_h,
                        json={"target_status": target})
        early_date2 = (date.today() + timedelta(days=1)).isoformat()
        r = client.post(f"/api/v1/boarding/orders/{early_oid}/early-pickup", headers=cust_h,
                        json={"expect_pickup_date": early_date2, "reason": "冒烟：提前接回"})
        early2 = r.json()["data"]["id"] if r.status_code == 200 else None
        check("提前接回申请可再次提交", r.status_code == 200 and early2, r.text[:160])
        r = client.post(f"/api/v1/boarding/early-pickups/{early2}/review", headers=staff_h,
                        json={"approve": True, "note": "已安排接送"})
        check("店员通过提前接回申请", r.status_code == 200, r.text[:160])
        r = client.get(f"/api/v1/boarding/orders/{early_oid}", headers=staff_h)
        check("通过后订单转为 early_pickup", r.json()["data"]["status"] == "early_pickup", r.text[:160])

    print("== 39. V7.1 寄养：权限与看板 ==")
    if board_id:
        r = client.post(f"/api/v1/boarding/orders/{board_id}/care-logs", headers=cust_h, json={"eating": "正常"})
        check("宠主填写照护日志被拒（403）", r.status_code == 403, r.text[:160])
        r = client.get("/api/v1/boarding/orders", headers=staff_h)
        check("店员可看全部寄养订单", r.status_code == 200 and r.json()["data"]["total"] >= 2, r.text[:160])
        # 主用例的订单已走到「已完成」（房态已释放），重复下单本就该成功；
        # 因此这里针对**仍在占用中**的延期单房间（room2）验证房态冲突
        r = client.post("/api/v1/boarding/orders", headers=cust_h, json={
            "pet_id": pet_id, "room_id": room2["id"], "check_in_date": board_in,
            "check_out_date": board_out, "terms_confirmed": True, "idempotent_key": idem + "-x2",
        })
        check("同房间同区间重复下单被房态拒绝（409）", r.status_code == 409, r.text[:160])

    r = client.get("/api/v1/boarding/dashboard?start=2026-01-01&end=2027-12-31", headers=mgr_h)
    ok_dash = r.status_code == 200
    dash = r.json()["data"] if ok_dash else {}
    check("店长可看寄养看板", ok_dash and dash.get("orders", 0) >= 1, r.text[:200])
    check("看板含收入 / 客单价 / 入住率 / 异常率",
          ok_dash and all(k in dash for k in ("revenue", "avg_price", "occupancy_rate", "abnormal_rate")),
          str(dash)[:200])
    r = client.get("/api/v1/boarding/dashboard?start=2026-01-01&end=2027-12-31", headers=staff_h)
    check("店员访问寄养看板被拒（403）", r.status_code == 403, r.text[:160])

    print("== 40. V7.1 寄养：定时任务 ==")
    r = client.get("/api/v1/tasks", headers=mgr_h)
    names = {i["name"] for i in r.json()["data"]["items"]}
    check("任务清单含寄养巡检", "boarding_scan" in names, str(sorted(names)))
    r = client.post("/api/v1/tasks/boarding_scan/run", headers=mgr_h)
    check("寄养巡检任务可执行", r.status_code == 200 and r.json()["data"]["status"] == "success",
          r.text[:200])

    print("== 42. V7.2 用品：商品与安全标签 ==")
    r = client.post("/api/v1/auth/login", json={"username": "liu", "password": "123456"})
    liu_h = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
    liu_pets = client.get("/api/v1/pets", headers=liu_h).json()["data"]
    wangcai = next((x for x in liu_pets if x["name"] == "旺财"), None)
    check("演示宠主 liu 名下有旺财（过敏史：含燕麦）", bool(wangcai), str(liu_pets)[:160])

    r = client.get(f"/api/v1/goods/products?pet_id={wangcai['id']}", headers=liu_h)
    ok_gp = r.status_code == 200
    goods = (r.json()["data"]["items"] if ok_gp else [])
    check("商品列表可读且含安全标签", ok_gp and len(goods) >= 5, r.text[:200])
    oat = next((x for x in goods if "燕麦" in x["name"]), None)
    check("含燕麦商品被标记为不安全（过敏交叉校验）",
          bool(oat) and oat["unsafe"] is True and oat["conflicts"], str(oat)[:220])
    safe_choice = next((x for x in goods if not x["unsafe"] and x["total_stock"] > 0), None)
    check("存在无冲突商品（列表不会一片红）", bool(safe_choice), str(goods)[:200])

    r = client.get(f"/api/v1/goods/products/{oat['id']}?pet_id={wangcai['id']}", headers=liu_h)
    detail = r.json()["data"]
    check("商品详情给出冲突原因", detail["unsafe"] and detail["conflicts"], str(detail)[:220])
    check("冲突时给出同类替代建议", bool(detail.get("alternative")), str(detail.get("alternative"))[:160])
    check("SKU 含单位价（元/kg，便于比价）",
          any(s["unit_price"] for s in detail["skus"]), str(detail["skus"])[:200])

    print("== 43. V7.2 用品：购物车 ==")
    safe_sku = safe_choice["skus"][0]["id"]
    r = client.post("/api/v1/goods/cart", headers=liu_h,
                    json={"sku_id": safe_sku, "quantity": 2, "pet_id": wangcai["id"]})
    check("加入购物车（安全商品）", r.status_code == 200 and not r.json()["data"]["warnings"], r.text[:200])
    oat_sku = detail["skus"][0]["id"]
    r = client.post("/api/v1/goods/cart", headers=liu_h, json={"sku_id": oat_sku, "quantity": 1})
    check("加购过敏商品只警告不拦截（允许先看看）",
          r.status_code == 200, r.text[:200])
    r = client.get("/api/v1/goods/cart", headers=liu_h)
    cart = r.json()["data"]
    check("购物车小计与件数正确",
          cart["count"] >= 2 and cart["total"] > 0, str(cart)[:200])
    cart_id = cart["items"][0]["id"]
    r = client.patch(f"/api/v1/goods/cart/{cart_id}", headers=liu_h, json={"quantity": 3})
    check("修改购物车数量", r.status_code == 200 and r.json()["data"]["quantity"] == 3, r.text[:160])

    print("== 44. V7.2 用品：过敏硬拦截 + 库存占用 ==")
    r = client.get("/api/v1/goods/stock", headers=staff_h)
    stock_before = {i["sku_id"]: i["stock"] for i in r.json()["data"]["items"]}

    r = client.post("/api/v1/goods/orders", headers=liu_h, json={
        "items": [{"sku_id": oat_sku, "quantity": 1, "pet_id": wangcai["id"]}],
        "pickup_method": "self", "pet_id": wangcai["id"], "idempotent_key": idem + "-g-oat",
    })
    check("下单含过敏原商品被硬拦截（不允许落库）", r.status_code in (400, 422), r.text[:220])

    # 购物车里还躺着一件过敏商品 —— 直接结算必须被拦（比只测 items 更贴近真实链路）
    r = client.post("/api/v1/goods/orders", headers=liu_h, json={
        "pickup_method": "self", "pet_id": wangcai["id"],
        "idempotent_key": idem + "-g-cart-oat",
    })
    check("购物车含过敏商品时整单被拦截", r.status_code in (400, 422), r.text[:220])

    # 宠主删掉过敏商品后重新结算（真实操作路径）
    r = client.get("/api/v1/goods/cart", headers=liu_h)
    for item in r.json()["data"]["items"]:
        if "燕麦" in item["product_name"]:
            client.delete(f"/api/v1/goods/cart/{item['id']}", headers=liu_h)

    r = client.post("/api/v1/goods/orders", headers=liu_h, json={
        "pickup_method": "delivery", "address": "幸福路 9 号",
        "pet_id": wangcai["id"], "idempotent_key": idem + "-g-cart",
    })
    ok_go = r.status_code == 200
    check("从购物车下单成功（含配送费）", ok_go, r.text[:220])
    gorder = r.json()["data"] if ok_go else {}
    check("订单含核销码与明细", bool(gorder.get("pickup_code")) and len(gorder.get("items", [])) >= 1,
          str(gorder)[:220])
    check("配送费计入总额",
          gorder.get("delivery_fee", 0) > 0 and gorder.get("total_amount", 0) > 0, str(gorder)[:200])

    r = client.get("/api/v1/goods/stock", headers=staff_h)
    stock_after = {i["sku_id"]: i["stock"] for i in r.json()["data"]["items"]}
    check("下单即占用库存（库存减少）",
          stock_after.get(safe_sku, 0) < stock_before.get(safe_sku, 0),
          f"{stock_before.get(safe_sku)} -> {stock_after.get(safe_sku)}")
    r = client.get("/api/v1/goods/cart", headers=liu_h)
    check("下单后购物车已清空", r.json()["data"]["count"] == 0, r.text[:160])

    print("== 45. V7.2 用品：状态机 / 核销 / 取消回补 ==")
    go_id = gorder.get("id")
    if go_id:
        r = client.post(f"/api/v1/goods/orders/{go_id}/status", headers=staff_h,
                        json={"target_status": "completed"})
        check("待确认不能直接核销（409）", r.status_code == 409, r.text[:160])
        for target in ("confirmed", "ready"):
            r = client.post(f"/api/v1/goods/orders/{go_id}/status", headers=staff_h,
                            json={"target_status": target})
            check(f"店员推进到「{target}」", r.status_code == 200, r.text[:160])
        r = client.post("/api/v1/goods/pickup/verify", headers=staff_h,
                        json={"pickup_code": gorder["pickup_code"], "pay_status": "paid_offline"})
        check("核销取货成功（记录线下收款）",
              r.status_code == 200 and "核销成功" in r.json()["message"], r.text[:200])
        r = client.post("/api/v1/goods/pickup/verify", headers=staff_h,
                        json={"pickup_code": gorder["pickup_code"]})
        check("重复核销被拒绝", r.status_code in (400, 409), r.text[:160])

    # 取消回补库存
    r = client.post("/api/v1/goods/orders", headers=liu_h, json={
        "items": [{"sku_id": safe_sku, "quantity": 1}], "pickup_method": "self",
        "idempotent_key": idem + "-g-cancel",
    })
    cancel_id = r.json()["data"]["id"] if r.status_code == 200 else None
    check("再下一单用于验证取消", bool(cancel_id), r.text[:200])
    if cancel_id:
        r = client.get("/api/v1/goods/stock", headers=staff_h)
        after_order = {i["sku_id"]: i["stock"] for i in r.json()["data"]["items"]}
        r = client.post(f"/api/v1/goods/orders/{cancel_id}/cancel", headers=liu_h,
                        json={"target_status": "cancelled", "reason": "冒烟测试取消"})
        check("宠主取消订单成功", r.status_code == 200, r.text[:200])
        r = client.get("/api/v1/goods/stock", headers=staff_h)
        after_cancel = {i["sku_id"]: i["stock"] for i in r.json()["data"]["items"]}
        check("取消后库存自动回补",
              after_cancel.get(safe_sku, 0) > after_order.get(safe_sku, 0),
              f"{after_order.get(safe_sku)} -> {after_cancel.get(safe_sku)}")

    print("== 46. V7.2 用品：库存盘点 / 看板 / 权限 ==")
    r = client.patch(f"/api/v1/goods/skus/{safe_sku}/stock", headers=staff_h,
                     json={"stock": 50, "remark": "冒烟盘点"})
    check("库存盘点成功", r.status_code == 200 and r.json()["data"]["after"] == 50, r.text[:160])
    r = client.get("/api/v1/goods/stock?only_low=true", headers=staff_h)
    check("低库存筛选可用", r.status_code == 200, r.text[:160])
    r = client.get("/api/v1/goods/dashboard?start=2026-01-01&end=2027-12-31", headers=mgr_h)
    ok_gd = r.status_code == 200
    gd = r.json()["data"] if ok_gd else {}
    check("店长用品看板（收入/客单价/连带率/热销）",
          ok_gd and all(k in gd for k in ("revenue", "avg_price", "avg_items", "top_products")),
          str(gd)[:220])
    r = client.get("/api/v1/goods/dashboard?start=2026-01-01&end=2027-12-31", headers=staff_h)
    check("店员访问用品看板被拒（403）", r.status_code == 403, r.text[:160])
    r = client.post("/api/v1/goods/orders", headers=cust_h, json={
        "items": [{"sku_id": safe_sku, "quantity": 1}], "pickup_method": "self",
        "idempotent_key": idem + "-g-demo",
    })
    demo_gid = r.json()["data"]["id"] if r.status_code == 200 else None
    if demo_gid:
        r = client.get(f"/api/v1/goods/orders/{demo_gid}", headers=liu_h)
        check("宠主不能查看他人订单（403）", r.status_code == 403, r.text[:160])

    print("== 47. V7.3 实景：在住寄养单 + 设备在线 ==")
    # 造一间测试房 + 一张在住寄养单（实景只能看在住的自己的宠物）
    r = client.post("/api/v1/boarding/rooms", headers=mgr_h, json={
        "room_no": f"C{rnd.randint(1000, 9999)}", "room_type": "standard", "name": "实景回归房",
        "species_limit": "all", "weight_limit": 30, "ratio_percent": 100, "capacity": 1,
    })
    cam_room = r.json()["data"]
    r = client.post("/api/v1/camera/devices", headers=mgr_h, json={
        "room_id": cam_room["id"], "name": "实景回归摄像头",
        "provider_type": "local_webcam", "fps": 5, "resolution": "640x480",
    })
    device = r.json()["data"] if r.status_code == 200 else None
    check("店长给宠舍绑定摄像头", bool(device), r.text[:200])

    # 疫苗必须覆盖入住日（校验口径是「入住当天仍有效」）：先补一条长效记录
    live_in = (date.today() + timedelta(days=rnd.randint(200, 260))).isoformat()
    client.post(f"/api/v1/pets/{pet_id}/vaccines", headers=cust_h, json={
        "record_type": "vaccine", "name": "联苗（加强）", "record_date": str(date.today()),
        "next_date": str(date.fromisoformat(live_in) + timedelta(days=60)),
    })
    live_out = (date.today() + timedelta(days=rnd.randint(261, 300))).isoformat()
    r = client.post("/api/v1/boarding/orders", headers=cust_h, json={
        "pet_id": pet_id, "room_id": cam_room["id"],
        "check_in_date": live_in, "check_out_date": live_out,
        "terms_confirmed": True, "idempotent_key": idem + "-cam-order",
    })
    cam_order_id = r.json()["data"]["id"] if r.status_code == 200 else None
    check("造一张在住前的寄养单", bool(cam_order_id), r.text[:200])

    r = client.get("/api/v1/camera/live", headers=cust_h)
    live_list = r.json()["data"]
    check("未入住的订单不出现在可观看列表", not any(x["order_id"] == cam_order_id for x in live_list),
          str(live_list)[:200])

    if cam_order_id:
        for target in ("confirmed", "waiting_checkin", "checked_in"):
            client.post(f"/api/v1/boarding/orders/{cam_order_id}/status", headers=staff_h,
                        json={"target_status": target})
        r = client.post(f"/api/v1/camera/devices/{device['id']}/heartbeat", headers=staff_h)
        check("设备心跳上报（转在线）",
              r.status_code == 200 and r.json()["data"]["status"] == "online", r.text[:160])

        r = client.get("/api/v1/camera/live", headers=cust_h)
        mine = next((x for x in r.json()["data"] if x["order_id"] == cam_order_id), None)
        check("入住后出现在可观看列表", bool(mine), str(r.json()["data"])[:220])
        check("可观看状态与设备信息完整",
              bool(mine) and mine["can_watch"] and mine["device_status"] == "online", str(mine)[:220])

    print("== 48. V7.3 实景：凭证 / 推帧 / 拉流 / 留痕 ==")
    if cam_order_id:
        r = client.post("/api/v1/camera/sessions", headers=cust_h, json={"order_id": cam_order_id})
        ok_tok = r.status_code == 200
        tok = r.json()["data"] if ok_tok else {}
        check("签发观看凭证（短期 token）", ok_tok and len(tok.get("token", "")) >= 16, r.text[:220])
        check("凭证带有效期与浮水印", ok_tok and tok.get("expires_in", 0) > 0
              and bool(tok.get("watermark")), str(tok)[:200])

        r = client.post("/api/v1/camera/sessions", headers=liu_h, json={"order_id": cam_order_id})
        check("他人无法获取观看凭证（403）", r.status_code == 403, r.text[:160])

        # 门店端推一帧（用最小 JPEG 头尾即可，后端只校验非空与大小）
        fake_jpeg = b"\xff\xd8\xff\xe0" + b"0" * 128 + b"\xff\xd9"
        r = client.post(f"/api/v1/camera/frames/{tok['token']}", headers=staff_h, content=fake_jpeg)
        check("门店端推送画面帧", r.status_code == 200 and r.json()["data"]["bytes"] > 0, r.text[:200])
        r = client.post(f"/api/v1/camera/frames/{tok['token']}", headers=cust_h, content=fake_jpeg)
        check("宠主不能推帧（403）", r.status_code == 403, r.text[:160])

        # 单帧轮询端点（宠主端播放统一走这里）：推帧后必须回真实帧并标记 live
        r = client.get(f"/api/v1/camera/frame/{tok['token']}")
        check("单帧端点回真实帧（X-Frame-Mode: live）",
              r.status_code == 200 and r.headers.get("x-frame-mode") == "live"
              and (r.headers.get("content-type") or "").startswith("image/jpeg"),
              f"{r.status_code} {r.headers.get('x-frame-mode')}")
        r = client.get("/api/v1/camera/frame/not-a-valid-token")
        check("单帧端点凭证无效（404）", r.status_code == 404, r.text[:120])

        with client.stream("GET", f"/api/v1/camera/stream/{tok['token']}") as resp:
            check("MJPEG 拉流端点可用",
                  resp.status_code == 200
                  and "multipart/x-mixed-replace" in (resp.headers.get("content-type") or ""),
                  f"{resp.status_code} {resp.headers.get('content-type')}")

        r = client.post("/api/v1/camera/snapshots", headers=cust_h, json={
            "order_id": cam_order_id, "image_url": "/static/camera/demo-snap.jpg", "note": "冒烟抓拍",
        })
        check("一键抓拍存入相册", r.status_code == 200, r.text[:200])
        r = client.get("/api/v1/camera/snapshots", headers=cust_h)
        check("相册可读", r.status_code == 200 and len(r.json()["data"]) >= 1, r.text[:160])

        r = client.post(f"/api/v1/camera/sessions/{tok['session_id']}/end", headers=cust_h)
        check("结束观看并记录时长",
              r.status_code == 200 and "duration_seconds" in r.json()["data"], r.text[:160])

    print("== 49. V7.3 实景：看板 / 离线巡检 / 任务 ==")
    r = client.get("/api/v1/camera/stats?start=2026-01-01&end=2027-12-31", headers=mgr_h)
    ok_cs = r.status_code == 200
    cs = r.json()["data"] if ok_cs else {}
    check("店长实景看板（观看量/在线率/抓拍）",
          ok_cs and all(k in cs for k in ("watch_count", "online_rate", "snapshots")), str(cs)[:220])
    r = client.get("/api/v1/camera/stats?start=2026-01-01&end=2027-12-31", headers=staff_h)
    check("店员访问实景看板被拒（403）", r.status_code == 403, r.text[:160])
    r = client.get("/api/v1/camera/devices", headers=staff_h)
    check("店员可查设备列表", r.status_code == 200 and len(r.json()["data"]) >= 6, r.text[:160])

    # 宠舍管理（V8.4.8）：店员可增删改查，房号唯一，有订单引用的宠舍不能删
    from uuid import uuid4

    tag = uuid4().hex[:5].upper()
    r = client.post("/api/v1/boarding/rooms", headers=staff_h, json={
        "room_no": f"Z{tag}", "room_type": "standard", "name": f"冒烟房 {tag}",
        "species_limit": "all", "weight_limit": 10, "ratio_percent": 100, "capacity": 1,
    })
    ok_add = r.status_code == 200
    room_id = r.json()["data"]["id"] if ok_add else None
    check("店员可新增宠舍", ok_add, r.text[:160])
    r = client.post("/api/v1/boarding/rooms", headers=staff_h, json={
        "room_no": f"Z{tag}", "room_type": "standard", "name": "重复房号",
        "species_limit": "all", "ratio_percent": 100, "capacity": 1,
    })
    check("重复房号被拒绝（400）", r.status_code == 400, r.text[:160])
    r = client.post("/api/v1/boarding/rooms", headers=staff_h, json={
        "id": room_id, "room_no": f"Z{tag}", "room_type": "standard", "name": f"冒烟房 {tag}改",
        "species_limit": "all", "weight_limit": 12, "ratio_percent": 110, "capacity": 1,
    })
    check("店员可编辑宠舍", r.status_code == 200 and r.json()["data"]["ratio_percent"] == 110, r.text[:160])
    r = client.delete(f"/api/v1/boarding/rooms/{room_id}", headers=staff_h)
    check("店员可删除无订单宠舍", r.status_code == 200, r.text[:160])
    r = client.delete(f"/api/v1/boarding/rooms/{room_id}", headers=staff_h)
    check("删除不存在的宠舍（404）", r.status_code == 404, r.text[:160])
    r = client.get("/api/v1/camera/meta", headers=cust_h)
    check("实景字典含隐私说明与限制参数",
          r.status_code == 200 and "privacy" in r.json()["data"], r.text[:200])
    r = client.get("/api/v1/tasks", headers=mgr_h)
    names = {i["name"] for i in r.json()["data"]["items"]}
    check("任务清单含摄像头离线巡检", "camera_offline" in names, str(sorted(names)))
    r = client.post("/api/v1/tasks/camera_offline/run", headers=mgr_h)
    check("摄像头离线巡检可执行",
          r.status_code == 200 and r.json()["data"]["status"] == "success", r.text[:200])

    print("== 50. 回归：寄养日期与房型列表（本轮修复）==")
    # Bug 现象：选了宠物 + 日期后房型列表 400（内部误用 quote 校验最少晚数），导致怎么都约不上
    d0 = date.today() + timedelta(days=rnd.randint(150, 190))
    r = client.get(
        f"/api/v1/boarding/rooms?pet_id={pet_id}&check_in={d0}&check_out={d0 + timedelta(days=3)}",
        headers=cust_h)
    rooms_live = r.json()["data"] if r.status_code == 200 else []
    check("带日期查房型返回 200（原 400 已修复）", r.status_code == 200, r.text[:200])
    check("房型列表非空且带预估日费",
          len(rooms_live) >= 5 and all(x.get("est_daily_cents", 0) > 0 for x in rooms_live),
          str(rooms_live[:1])[:220])
    check("房型列表标注可订状态", any(x["available"] for x in rooms_live),
          str([(x["room_no"], x["available"]) for x in rooms_live])[:200])

    print("== 51. 回归：商品增删改查（本轮新增）==")
    r = client.get("/api/v1/goods/admin/products", headers=staff_h)
    ok_admin = r.status_code == 200
    check("店员可读商品维护列表（含下架）", ok_admin and r.json()["data"]["total"] >= 5, r.text[:200])

    new_name = f"回归测试猫砂{rnd.randint(1000, 9999)}"
    r = client.post("/api/v1/goods/products", headers=staff_h, json={
        "name": new_name, "brand": "回归品牌", "category": "daily", "species": "cat",
        "stage": "all", "size": "all", "status": "on", "sort_no": 99,
        "allergy_tags": "", "taboo_tags": "", "selling_points": "低尘,结团",
        "skus": [{"spec_name": "5L", "price_cents": 3900, "weight_g": 2500, "stock": 10}],
    })
    check("店员新增商品（含 SKU）", r.status_code == 200, r.text[:220])
    new_pid = r.json()["data"]["id"] if r.status_code == 200 else None

    if new_pid:
        r = client.get("/api/v1/goods/admin/products?keyword=" + new_name, headers=staff_h)
        items = r.json()["data"]["items"]
        check("新增商品可被检索到", len(items) == 1 and items[0]["skus"][0]["stock"] == 10,
              str(items)[:220])

        r = client.post("/api/v1/goods/products", headers=staff_h, json={
            "name": new_name, "brand": "回归品牌", "category": "daily", "species": "cat",
            "stage": "all", "size": "all", "status": "off", "sort_no": 99,
            "skus": [{"spec_name": "5L", "price_cents": 4200, "weight_g": 2500, "stock": 8}],
        })
        check("编辑商品（改价 + 改状态 + 改库存）", r.status_code == 200, r.text[:200])
        r = client.get("/api/v1/goods/admin/products?keyword=" + new_name, headers=staff_h)
        item = r.json()["data"]["items"][0]
        check("编辑结果已生效（下架 + 42 元 + 库存 8）",
              item["status"] == "off" and item["skus"][0]["price"] == 42 and item["skus"][0]["stock"] == 8,
              str(item)[:240])

        # 下架后宠主端看不到
        r = client.get(f"/api/v1/goods/products?keyword={new_name}", headers=cust_h)
        check("下架商品不出现在宠主端", len(r.json()["data"]["items"]) == 0, r.text[:200])

        r = client.delete(f"/api/v1/goods/products/{new_pid}", headers=staff_h)
        check("删除商品（含 SKU）", r.status_code == 200, r.text[:200])
        r = client.get("/api/v1/goods/admin/products?keyword=" + new_name, headers=staff_h)
        check("删除后列表不再返回该商品", len(r.json()["data"]["items"]) == 0, r.text[:200])

    print("== 52. 回归：菜单分组（主要功能 / 宠物之家）==")
    r = client.get("/api/v1/settings", headers=cust_h)
    check("菜单分组改造后权限接口未受影响", r.status_code == 200, r.text[:160])

    print("== 53. V8.2 寄养资格预检（疫苗可解释 + 提前拦截）==")
    near = (date.today() + timedelta(days=60)).isoformat()
    r = client.get(f"/api/v1/boarding/eligibility?pet_id={pet_id}&check_in={near}", headers=cust_h)
    ok_elig = r.status_code == 200
    elig = r.json()["data"] if ok_elig else {}
    check("寄养资格预检接口可用", ok_elig and "ok" in elig, r.text[:200])
    check("疫苗有效时返回 ok=true 且带有效期",
          elig.get("ok") is True and bool(elig.get("vaccine_until")), str(elig)[:200])

    far = (date.today() + timedelta(days=3650)).isoformat()
    r = client.get(f"/api/v1/boarding/eligibility?pet_id={pet_id}&check_in={far}", headers=cust_h)
    far_elig = r.json()["data"] if r.status_code == 200 else {}
    check("疫苗覆盖不到时 ok=false 且说明宠物与有效期",
          far_elig.get("ok") is False
          and "疫苗" in (far_elig.get("message") or "")
          and bool(far_elig.get("vaccine_until")), str(far_elig)[:240])
    check("资格预检返回体重与最少晚数等辅助信息",
          "weight_kg" in far_elig and "min_nights" in far_elig, str(far_elig)[:200])

    print("== 54. V8.2 宠主 Agent 新能力（建档案 / 寄养 / 用品 / 实景）==")
    r = client.get("/api/v1/chat/capabilities", headers=cust_h)
    caps = r.json()["data"] if r.status_code == 200 else {}
    names = {t["name"] for t in caps.get("tools", [])}
    want = {"create_pet_profile", "query_boarding_options", "create_boarding_order",
            "query_goods", "add_goods_to_cart", "submit_goods_order"}
    check("宠主可见工具含 4 类新能力（6 个工具）", want <= names, str(sorted(names))[:260])
    check("宠主工具画像已扩展到 13 个（含知识库检索）",
          len(caps.get("tools", [])) == 13, f"{len(caps.get('tools', []))}")

    # V8.3 Agent 内 RAG：问规范类问题应命中 search_knowledge，回答里带「依据 / 来源」
    with client.stream("POST", "/api/v1/chat/message", headers=cust_h,
                       json={"content": "疫苗打完多久可以洗澡？"}) as resp:
        rag_events = [json.loads(l[5:].strip()) for l in resp.iter_lines()
                      if l and l.startswith("data:") and l[5:].strip()]
    rag_intent = next((e.get("intent") for e in rag_events if e.get("type") == "intent"), None)
    rag_answer = "".join(e.get("delta", "") for e in rag_events if e.get("type") == "answer")
    rag_refs = next((e.get("items") for e in rag_events if e.get("type") == "refs"), None)
    check("规范类问题走知识库检索（search_knowledge）",
          rag_intent == "search_knowledge", f"intent={rag_intent}")
    # V8.4.5 起：回答由模型基于片段生成，片段单独以 refs 事件下发（前端折叠展示）
    check("知识问答下发检索片段（refs 事件带标题与来源）",
          bool(rag_refs) and bool(rag_refs[0].get("title")) and bool(rag_refs[0].get("source")),
          str(rag_refs)[:200])
    check("知识问答回答由模型生成（非模板清单）",
          len(rag_answer) >= 20 and not rag_answer.startswith("找到 "), rag_answer[:160])
    # 实景跳转：走真实 SSE，断言服务端会下发 navigate 事件（规则优先，不依赖 LLM）
    with client.stream("POST", "/api/v1/chat/message", headers=cust_h,
                       json={"content": "帮我看看宠物现在的状态"}) as resp:
        nav_events = []
        cam_events = []
        for line in resp.iter_lines():
            if not line.startswith("data:"):
                continue
            try:
                evt = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            cam_events.append(evt)
            if evt.get("type") == "navigate":
                nav_events.append(evt)
            if evt.get("type") in ("done", "end"):
                break
    # V8.4.9 起：实景先看在住宠物，有则跳到实景页并带上 order_id，没有则明确说明
    cam_answer = "".join(e.get("delta", "") for e in cam_events if e.get("type") == "answer")
    cam_ok = (
        bool(nav_events) and nav_events[0].get("path", "").startswith("/user/camera?order_id=")
    ) or ("寄养中" in cam_answer) or ("看不了" in cam_answer)
    check("「看看宠物状态」走实景流程（跳转带 order_id 或说明无在住宠物）",
          cam_ok, f"nav={nav_events[:1]} answer={cam_answer[:120]}")

    r = client.get("/api/v1/chat/tool-profile", headers=mgr_h)
    profiles = r.json()["data"]["profiles"]
    check("三角色画像数量符合约定（13 / 11 / 11）",
          profiles["customer"]["count"] == 13 and profiles["staff"]["count"] == 11
          and profiles["manager"]["count"] == 11,
          str({k: v["count"] for k, v in profiles.items()}))

    print("== 41. 测试数据清理（保持演示环境干净）==")
    # 冒烟会创建宠物与测试房舍：用完即清，否则演示数据会被测试残留污染（截图满屏「冒烟测试犬」）
    cleaned_pet, cleaned_room = 0, 0
    # 只清「本轮自建」的宠物（new_pet_id / nova_pet_id）；
    # pet_id 指向的是演示数据里的豆豆，**绝不能删**（踩过一次：清理把演示宠物删了）
    for pid in [locals().get("new_pet_id"), locals().get("nova_pet_id")]:
        if isinstance(pid, int) and client.delete(f"/api/v1/pets/{pid}", headers=cust_h).status_code == 200:
            cleaned_pet += 1
    for room in (locals().get("test_room"), locals().get("room2")):
        if isinstance(room, dict) and client.patch(
            f"/api/v1/boarding/rooms/{room['id']}/status", headers=mgr_h, json={"status": "maintenance"}
        ).status_code == 200:
            cleaned_room += 1
    check("清理本轮测试宠物档案", cleaned_pet >= 1, f"cleaned={cleaned_pet}")
    check("测试房舍转为维护中（不再出现在可选列表）", cleaned_room >= 1, f"cleaned={cleaned_room}")

    print("\n" + "=" * 56)
    print(f"冒烟结果：PASS {len(PASS)} / FAIL {len(FAIL)}")
    if FAIL:
        print("失败项：")
        for item in FAIL:
            print("  -", item)
    print("=" * 56)
    return 1 if FAIL else 0


def main() -> int:
    # 必须使用上下文管理器：保证 lifespan 与所有请求复用同一个事件循环，
    # 否则 aiomysql 连接池会跨事件循环复用而报 "Event loop is closed"。
    with TestClient(app) as client:
        return _run_all(client)


if __name__ == "__main__":
    raise SystemExit(main())
