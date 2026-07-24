"""统计报表接口（全部参数化查询）。"""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import UserRole  # noqa: F401
from app.database import get_db
from app.deps.auth import get_current_user, get_manager_user
from app.models import User
from app.schemas.common import ok
from app.services import appointment_service, pet_service, stats_service, wash_service
from app.services.audit_service import write_log
from app.utils.crypto import decrypt_text

router = APIRouter(prefix="/report", tags=["统计报表"])


@router.get("/summary", summary="运营概览统计")
async def summary(
    start: date | None = Query(None, description="开始日期，默认近 30 天"),
    end: date | None = Query(None, description="结束日期，默认今天"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """运营概览统计。"""
    default_start, default_end = stats_service.default_range()
    start = start or default_start
    end = end or default_end
    if end < start:
        start, end = end, start
    data = await stats_service.summary(db, start, end)
    return ok(data)


@router.get("/export", summary="导出 CSV（仅店长，记录审计日志）")
async def export(
    request: Request,
    type: str = Query("summary", description="导出类型：summary 经营概览 / appointments 预约明细 / wash 洗护记录 / pets 客户档案"),
    start: date | None = Query(None),
    end: date | None = Query(None),
    manager: User = Depends(get_manager_user),
    db: AsyncSession = Depends(get_db),
):
    """导出 CSV（仅店长，记录审计日志）。"""
    default_start, default_end = stats_service.default_range()
    start = start or default_start
    end = end or default_end
    export_type = (type or "summary").strip().lower()

    buffer = io.StringIO()
    writer = csv.writer(buffer)

    if export_type == "appointments":
        items, _ = await appointment_service.list_appointments(
            db, manager, page=1, size=5000, appoint_date=None
        )
        items = [i for i in items if start <= i["appoint_date"] <= end]
        writer.writerow(["预约单号", "宠物", "宠主", "联系电话", "服务", "到店日期", "时段",
                         "状态", "风险等级", "改期次数", "取消/终止原因", "创建时间"])
        for i in items:
            writer.writerow([
                i["order_no"], i["pet_name"] or "-", i["owner_name"] or "-", i["owner_phone"] or "-",
                i["service_type_label"], i["appoint_date"], i["slot_time"], i["status_label"],
                i["risk_level"] or "-", i["reschedule_times"],
                i["cancel_reason"] or i["terminate_reason"] or "-",
                str(i["created_at"] or "")[:19],
            ])
        filename = f"预约明细_{start}_{end}.csv"

    elif export_type == "wash":
        records, _ = await wash_service.list_wash_records(db, manager, page=1, size=5000,
                                                          start=str(start), end=str(end))
        writer.writerow(["预约单号", "宠物", "宠主", "服务", "到店日期", "时段",
                         "洗护开始", "洗护结束", "皮肤状况", "毛发状况", "使用产品", "店员记录"])
        for r in records:
            writer.writerow([
                r["order_no"] or "-", r["pet_name"] or "-", r["owner_name"] or "-",
                r["service_type_label"], r["appoint_date"] or "-", r["slot_time"] or "-",
                str(r["wash_start"] or "-")[:19], str(r["wash_end"] or "-")[:19],
                r["skin_condition"] or "-", r["hair_condition"] or "-",
                r["products"] or "-", r["staff_note"] or "-",
            ])
        filename = f"洗护记录_{start}_{end}.csv"

    elif export_type == "pets":
        pets = await pet_service.list_pets(db, manager)
        writer.writerow(["档案ID", "宠物名", "类型", "品种", "性别", "生日", "体重(kg)",
                         "绝育", "应激等级", "攻击倾向", "过敏史", "皮肤病史", "应急联系人", "应急电话"])
        species_map = {"dog": "犬", "cat": "猫", "other": "其他"}
        gender_map = {"male": "公", "female": "母"}
        for p in pets:
            writer.writerow([
                p.id, p.name, species_map.get(p.species, p.species), p.breed or "-",
                gender_map.get(p.gender, p.gender), p.birthday or "-", p.weight or "-",
                "已绝育" if p.sterilized else "未绝育", p.stress_level,
                "有" if p.aggressive else "无",
                p.allergy or "-", p.skin_disease or "-",
                p.emergency_contact or "-", decrypt_text(p.emergency_phone) or "-",
            ])
        filename = f"客户档案_{start}_{end}.csv"

    else:
        data = await stats_service.summary(db, start, end)
        export_type = "summary"
        writer.writerow(["统计区间", f"{data['range_start']} ~ {data['range_end']}"])
        writer.writerow([])
        writer.writerow(["指标", "数值"])
        writer.writerow(["订单量（已确认及以上）", data["total_orders"]])
        writer.writerow(["已完成", data["completed_orders"]])
        writer.writerow(["已取消", data["cancelled_orders"]])
        writer.writerow(["爽约", data["no_show_orders"]])
        writer.writerow(["爽约率(%)", data["no_show_rate"]])
        writer.writerow(["复购率(%)", data["repurchase_rate"]])
        writer.writerow(["高风险报告数", data["risk_high_count"]])
        writer.writerow([])
        writer.writerow(["服务占比", "占比(%)"])
        for row in data["service_ratio"]:
            writer.writerow([row["label"], row["value"]])
        writer.writerow([])
        writer.writerow(["店员工作量", "已完成单数"])
        for row in data["staff_workload"]:
            writer.writerow([row["staff_name"], row["finished_count"]])
        writer.writerow([])
        writer.writerow(["流失预警宠物", "最后洗护日期", "空闲天数"])
        for row in data["churn_pets"]:
            writer.writerow([row["pet_name"], row["last_wash_date"] or "-", row["idle_days"] or "-"])
        filename = f"经营概览_{start}_{end}.csv"

    await write_log(db, module="report", action="export_csv", user_id=manager.id, request=request,
                    detail=f"type={export_type} {start}~{end}")
    await db.commit()

    content = "\ufeff" + buffer.getvalue()
    from urllib.parse import quote

    disposition = f"attachment; filename*=UTF-8''{quote(filename)}"
    return StreamingResponse(
        iter([content.encode("utf-8")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": disposition},
    )


@router.get("/churn", summary="流失预警名单")
async def churn(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """流失预警名单。"""
    today = date.today()
    data = await stats_service.summary(db, today - timedelta(days=365), today)
    return ok({"churn_days": data["churn_days"], "items": data["churn_pets"]})


@router.get("/audit-logs", summary="审计日志（仅店长）")
async def audit_logs(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    module: str | None = None,
    manager: User = Depends(get_manager_user),
    db: AsyncSession = Depends(get_db),
):
    """审计日志（仅店长）。"""
    from app.services import audit_service

    items, total = await audit_service.list_logs(db, module=module, page=page, size=size)
    return ok({"items": items, "total": int(total), "page": page, "size": size,
               "note": "手机号等敏感字段已在日志层脱敏，不返回明文快照"})


__all__ = ["UserRole"]
