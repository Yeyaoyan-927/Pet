"""门店配置服务：类型 / 范围校验，非法值拒绝保存并回退默认值。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.enums import SETTING_RULES, SettingRule, SettingValueType
from app.models import StoreSetting, User
from app.utils.exceptions import BizError


def _rule(key: str) -> SettingRule:
    rule = SETTING_RULES.get(key)
    if rule is None:
        raise BizError(f"未知的配置项：{key}")
    return rule


def validate_value(key: str, value: str) -> str:
    """返回规范化后的字符串；非法则抛 BizError（由上层决定是否回退默认值）。"""
    rule = _rule(key)
    raw = (value or "").strip()
    if rule.value_type == SettingValueType.INT:
        if not raw.lstrip("-").isdigit():
            raise BizError(f"配置项 {key} 需要整数")
        num = int(raw)
        if rule.min is not None and num < rule.min:
            raise BizError(f"配置项 {key} 不能小于 {rule.min}")
        if rule.max is not None and num > rule.max:
            raise BizError(f"配置项 {key} 不能大于 {rule.max}")
        return str(num)
    if rule.value_type == SettingValueType.BOOL:
        low = raw.lower()
        if low in {"true", "1", "yes", "on"}:
            return "true"
        if low in {"false", "0", "no", "off"}:
            return "false"
        raise BizError(f"配置项 {key} 需要布尔值 true/false")
    return raw


async def seed_defaults(db: AsyncSession) -> int:
    """按 SETTING_RULES 补齐缺失配置项，返回新增数量。"""
    rows = (await db.execute(select(StoreSetting))).scalars().all()
    exist = {r.setting_key for r in rows}
    added = 0
    for key, rule in SETTING_RULES.items():
        if key in exist:
            continue
        db.add(
            StoreSetting(
                setting_key=key,
                setting_value=rule.default,
                value_type=rule.value_type.value,
                default_value=rule.default,
                setting_desc=rule.desc,
            )
        )
        added += 1
    await db.flush()
    return added


async def get_all_settings(db: AsyncSession) -> list[dict]:
    """全部配置项（含默认值、取值范围与说明），供门店配置页渲染。"""
    rows = (await db.execute(select(StoreSetting).order_by(StoreSetting.id))).scalars().all()
    result = []
    for row in rows:
        rule = SETTING_RULES.get(row.setting_key)
        result.append(
            {
                "id": row.id,
                "setting_key": row.setting_key,
                "setting_value": row.setting_value,
                "value_type": row.value_type,
                "default_value": row.default_value,
                "setting_desc": row.setting_desc,
                "min_value": rule.min if rule else None,
                "max_value": rule.max if rule else None,
            }
        )
    return result


async def _get_row(db: AsyncSession, key: str) -> StoreSetting | None:
    return (
        await db.execute(select(StoreSetting).where(StoreSetting.setting_key == key))
    ).scalars().first()


async def get_value(db: AsyncSession, key: str) -> str:
    """读取配置；缺失或非法时回退默认值，保证业务永不因配置脏数据崩溃。"""
    rule = SETTING_RULES.get(key)
    fallback = rule.default if rule else ""
    row = await _get_row(db, key)
    if row is None:
        return fallback
    try:
        return validate_value(key, row.setting_value)
    except BizError:
        return fallback


async def get_int(db: AsyncSession, key: str) -> int:
    """读整数配置；缺失或脏值回退默认值。"""
    return int(await get_value(db, key))


async def get_bool(db: AsyncSession, key: str) -> bool:
    """读布尔配置（true/false 归一化）。"""
    return (await get_value(db, key)).lower() == "true"


async def update_setting(db: AsyncSession, key: str, value: str, operator: User) -> StoreSetting:
    """更新配置：先按规则校验再落库。**只 flush 不 commit**，提交由调用方负责。"""
    rule = _rule(key)
    normalized = validate_value(key, value)
    row = await _get_row(db, key)
    if row is None:
        row = StoreSetting(
            setting_key=key,
            setting_value=normalized,
            value_type=rule.value_type.value,
            default_value=rule.default,
            setting_desc=rule.desc,
        )
        db.add(row)
    else:
        row.setting_value = normalized

    # 保存后二次校验，异常则回退默认值（防御性：任何情况下配置表不会存脏值）
    try:
        validate_value(key, row.setting_value)
    except BizError:
        row.setting_value = row.default_value
        raise
    await db.flush()
    return row
