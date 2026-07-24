"""门店配置接口（店长专属写入）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps.auth import get_current_user, get_manager_user
from app.models import User
from app.schemas.common import ok
from app.schemas.setting import SettingUpdateIn
from app.services import setting_service
from app.services.audit_service import write_log

router = APIRouter(prefix="/settings", tags=["门店配置"])


@router.get("", summary="配置列表（全部角色可读，用于前端表单提示）")
async def list_settings(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """配置列表（全部角色可读，用于前端表单提示）。"""
    return ok(await setting_service.get_all_settings(db))


@router.put("", summary="修改配置（仅店长）")
async def update_setting(
    payload: SettingUpdateIn,
    request: Request,
    manager: User = Depends(get_manager_user),
    db: AsyncSession = Depends(get_db),
):
    """修改配置（仅店长）。"""
    before = await setting_service.get_value(db, payload.setting_key)
    row = await setting_service.update_setting(db, payload.setting_key, payload.setting_value, manager)
    await write_log(db, module="setting", action="update", user_id=manager.id, biz_id=row.id,
                    before={"setting_key": payload.setting_key, "setting_value": before},
                    after={"setting_key": payload.setting_key, "setting_value": row.setting_value},
                    request=request)
    await db.commit()
    return ok({"setting_key": row.setting_key, "setting_value": row.setting_value}, "配置已保存")


@router.post("/reset", summary="恢复默认值（仅店长）")
async def reset_settings(
    request: Request,
    manager: User = Depends(get_manager_user),
    db: AsyncSession = Depends(get_db),
):
    """恢复默认值（仅店长）。"""
    from app.constants.enums import SETTING_RULES

    for key, rule in SETTING_RULES.items():
        await setting_service.update_setting(db, key, rule.default, manager)
    await write_log(db, module="setting", action="reset", user_id=manager.id, request=request)
    await db.commit()
    return ok(None, "已恢复全部默认配置")
