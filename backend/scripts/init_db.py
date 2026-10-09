"""一键初始化脚本：创建数据库 → 执行 alembic 迁移 → 灌入演示数据。

用法（在 backend 目录下）：
    python scripts/init_db.py            # 初始化 / 增量迁移 + 幂等灌数据
    python scripts/init_db.py --reset    # 先清空业务表再灌数据（保留表结构）
"""
from __future__ import annotations

import argparse
import asyncio
import os
import random
import sys
from datetime import date, datetime, timedelta

import pymysql
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, update, func, select

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from app.config import settings  # noqa: E402
from app.constants import AppointmentStatus, ServiceType, UserRole  # noqa: E402
from app.database import AsyncSessionLocal, engine  # noqa: E402
from app.models import (  # noqa: E402
    Appointment,
    ChatMessage,
    ChatSession,
    Message,
    OperationLog,
    BoardingCareLog,
    CartItem,
    CameraDevice,
    CameraSession,
    CameraSnapshot,
    GoodsOrder,
    GoodsOrderItem,
    BoardingCarePlan,
    BoardingOrder,
    BoardingPickupTask,
    BoardingRoom,
    Pet,
    RiskReport,
    StoreSetting,
    User,
    VaccineRecord,
    WashRecord,
)
from app.services import (  # noqa: E402
    boarding_service,
    goods_service,
    knowledge_service,
    risk_service,
    setting_service,
)
from app.utils.crypto import encrypt_text, phone_hmac  # noqa: E402
from app.utils.datetime_util import gen_order_no  # noqa: E402
from app.utils.security import hash_password  # noqa: E402

random.seed(20261013)


def create_database() -> None:
    conn = pymysql.connect(
        host=settings.MYSQL_HOST, port=settings.MYSQL_PORT,
        user=settings.MYSQL_USER, password=settings.MYSQL_PASSWORD, charset="utf8mb4",
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{settings.MYSQL_DB}` "
                f"DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
            )
        conn.commit()
        print(f"[1/3] 数据库 `{settings.MYSQL_DB}` 就绪")
    finally:
        conn.close()


def run_migration() -> None:
    cfg = Config(os.path.join(BASE_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BASE_DIR, "alembic"))
    command.upgrade(cfg, "head")
    print("[2/3] alembic 迁移完成（upgrade head）")


async def _ensure_user(db, *, username, password, real_name, role, phone=None) -> User:
    user = (await db.execute(select(User).where(User.username == username))).scalars().first()
    if user:
        return user
    user = User(
        username=username,
        password_hash=hash_password(password),
        real_name=real_name,
        phone_encrypted=encrypt_text(phone),
        phone_hash=phone_hmac(phone),
        role=role,
    )
    db.add(user)
    await db.flush()
    return user


async def _ensure_pet(db, *, user, name, species, breed, gender, birthday, weight,
                      allergy=None, skin_disease=None, stress=0, aggressive=0,
                      sterilized=0, staff_id=None) -> Pet:
    pet = (await db.execute(select(Pet).where(Pet.name == name, Pet.user_id == user.id))).scalars().first()
    if pet:
        return pet
    pet = Pet(
        user_id=user.id, staff_id=staff_id, name=name, species=species, breed=breed,
        gender=gender, birthday=birthday, weight=weight, allergy=allergy,
        skin_disease=skin_disease, stress_level=stress, aggressive=aggressive,
        sterilized=sterilized, emergency_contact=user.real_name,
        emergency_phone=encrypt_text("13800001111"),
    )
    db.add(pet)
    await db.flush()
    return pet


async def _seed_cameras(db) -> int:
    """给每间房舍绑定一台门店摄像头（简版 provider=local_webcam），幂等按 room_id 判重。"""
    from app.models import BoardingRoom, CameraDevice

    rooms = (await db.execute(select(BoardingRoom))).scalars().all()
    exist = {
        r.room_id for r in (await db.execute(select(CameraDevice))).scalars().all()
    }
    added = 0
    for room in rooms:
        if room.id in exist:
            continue
        db.add(CameraDevice(
            room_id=room.id, name=f"{room.name} 摄像头", provider_type="local_webcam",
            status="offline", enabled=1, fps=5, resolution="640x480",
        ))
        added += 1
    if added:
        await db.flush()
    return added


async def _seed_demo_pet_house(db) -> None:
    """造一条演示用「在住寄养单」与一条「用品订单」，让宠物之家相关页面有内容可看。

    幂等：按固定幂等键判重；日期相对今天计算，重复执行不会叠加。
    """
    from app.constants import BoardingOrderStatus, GoodsOrderStatus, GoodsPayStatus, MessageType
    from app.models import Appointment, BoardingOrder, BoardingRoom, CartItem, GoodsOrder, GoodsOrderItem, Product, ProductSku
    from app.utils.datetime_util import gen_order_no

    demo = (await db.execute(select(User).where(User.username == "demo"))).scalars().first()
    pet = (await db.execute(select(Pet).where(Pet.name == "豆豆"))).scalars().first()
    room = (await db.execute(select(BoardingRoom).where(BoardingRoom.room_no == "A101"))).scalars().first()
    if not (demo and pet and room):
        return

    existed = (await db.execute(
        select(BoardingOrder).where(BoardingOrder.idempotent_key == "demo-boarding-1")
    )).scalars().first()
    if existed is None:
        today = date.today()
        order = BoardingOrder(
            order_no=gen_order_no(prefix="BG"), user_id=demo.id, pet_id=pet.id,
            room_id=room.id, room_type=room.room_type,
            status=BoardingOrderStatus.CHECKED_IN.value,
            check_in_date=today - timedelta(days=1), check_out_date=today + timedelta(days=4),
            nights=5, feeding_plan="self", food_note="每日 2 顿，每顿 120g，品牌随行粮",
            shipping_method="self", shipping_fee_cents=0,
            daily_fee_cents=4000, subtotal_cents=20000, discount_percent=100,
            extra_fee_cents=0, total_cents=20000,
            vaccine_ok=1, vaccine_note="演示数据：疫苗有效",
            emergency_contact="张女士", medical_authorized=1,
            terms_confirmed_at=datetime.now(), checkin_at=datetime.now() - timedelta(days=1),
            idempotent_key="demo-boarding-1", remark="演示：寄养中",
        )
        db.add(order)
        room.status = "occupied"
        await db.flush()
        db.add(BoardingCareLog(
            order_id=order.id, log_date=today - timedelta(days=1),
            eating="正常，吃完", drinking="正常", stool="2 次正常", spirit="活泼",
            activity="遛放 3 次共 60 分钟", abnormal=0,
            photos="/static/snapshots/demo-care.jpg", sop_checked="喂食,换水,遛放,拍照",
        ))
        await db.flush()

    goods_exist = (await db.execute(
        select(GoodsOrder).where(GoodsOrder.idempotent_key == "demo-goods-1")
    )).scalars().first()
    if goods_exist is None:
        sku = (await db.execute(
            select(ProductSku).join(Product, Product.id == ProductSku.product_id)
            .where(Product.name == "低敏无香洗护套装")
        )).scalars().first()
        if sku is not None:
            total = sku.price_cents * 2
            gorder = GoodsOrder(
                order_no=gen_order_no(prefix="GD"), user_id=demo.id,
                status=GoodsOrderStatus.PENDING.value, pay_status=GoodsPayStatus.UNPAID.value,
                item_count=2, total_cents=total, delivery_fee_cents=0,
                pickup_method="self", pickup_code="DEMO2026", pet_id=pet.id,
                idempotent_key="demo-goods-1", remark="演示：到店自提",
            )
            db.add(gorder)
            await db.flush()
            db.add(GoodsOrderItem(
                order_id=gorder.id, sku_id=sku.id, product_id=sku.product_id,
                product_name="低敏无香洗护套装", spec_name=sku.spec_name,
                price_cents=sku.price_cents, quantity=2, subtotal_cents=total,
            ))
            sku.stock = max(sku.stock - 2, 0)
            await db.flush()


async def seed_data(reset: bool = False) -> None:
    async with AsyncSessionLocal() as db:
        if reset:
            for model in (WashRecord, RiskReport, Message, Appointment, VaccineRecord,
                          Pet, OperationLog, ChatMessage, ChatSession,
                          # 寄养业务表（保留 boarding_room 房型与 knowledge_entry 知识库）
                          BoardingPickupTask, BoardingCareLog, BoardingCarePlan, BoardingOrder,
                          # 用品与实景业务表（保留 product / product_sku / camera_device）
                          GoodsOrderItem, GoodsOrder, CartItem, CameraSession, CameraSnapshot):
                await db.execute(delete(model))
            await db.commit()
            # 清掉历次冒烟 / 回归跑出来的测试残留（否则演示列表里全是「冒烟测试犬」）
            await db.execute(delete(Pet).where(
                Pet.name.like("冒烟测试%") | Pet.name.like("无疫苗%") | Pet.name.like("并发回归%")
                | Pet.name.like("回归测试%") | Pet.name.like("契约测试%") | Pet.name.like("边界犬%")
                | Pet.name.like("并发犬%") | Pet.name.like("v6race%") | Pet.name.like("v6same%")
                | Pet.name.like("v6sla%") | Pet.name.like("v6churn%") | Pet.name.like("v7board%")
                | Pet.name.like("v7vac%") | Pet.name.like("临时犬%") | Pet.name.like("T%犬")
                | Pet.name.like("寄养测试%")
            ))
            await db.execute(delete(BoardingRoom).where(BoardingRoom.room_no.like("T%")))
            # 自动化用例每跑一次建一台「实景回归摄像头」，从不清；设备表保留种子设备、
            # 清掉测试残留（否则店员端设备列表被几十台离线设备占满）
            await db.execute(delete(CameraDevice).where(
                CameraDevice.name.in_(("实景回归摄像头", "压测房 摄像头"))
            ))
            # 演示宠物若曾被测试「逻辑删除」，这里恢复，保证演示数据始终完整
            await db.execute(
                update(Pet).where(Pet.name.in_(["豆豆", "咪咪", "旺财"])).values(deleted_at=None)
            )
            print("     已清空业务表（保留账号与门店配置）")

        await setting_service.seed_defaults(db)
        # 洗护安全知识库（RAG 检索源）：幂等灌入，重置数据时保留
        kb_added = await knowledge_service.seed_defaults(db)
        # 寄养房型（V7.1）：幂等灌入，重置数据时保留
        room_added = await boarding_service.seed_rooms(db)
        # 宠物用品（V7.2）：种子商品与 SKU，幂等
        goods_added = await goods_service.seed_products(db)
        # 宠物实景（V7.3）：给每间房舍绑定一个门店摄像头设备
        cam_added = await _seed_cameras(db)
        await db.commit()
        # RAG 向量索引（V8.3）：知识落库后重建 Chroma，保证「问规范」能检索到最新内容
        index_result = await knowledge_service.reindex(db)
        if room_added:
            print(f"     已灌入寄养房型 {room_added} 间")
        if goods_added:
            print(f"     已灌入用品商品 {goods_added} 个")
        if cam_added:
            print(f"     已绑定摄像头设备 {cam_added} 台")
        if kb_added:
            print(f"     已灌入洗护安全知识 {kb_added} 条")
        print(f"     RAG 索引：{index_result.get('entries', 0)} 条知识 / "
              f"{index_result.get('chunks', 0)} 个切块（{index_result.get('space') or '未启用'}）")

        manager = await _ensure_user(db, username="admin", password="admin123",
                                     real_name="李店长", role=UserRole.MANAGER.value,
                                     phone="13700000001")
        staff1 = await _ensure_user(db, username="staff1", password="staff123",
                                    real_name="王小美", role=UserRole.STAFF.value,
                                    phone="13700000002")
        staff2 = await _ensure_user(db, username="staff2", password="staff123",
                                    real_name="陈阿强", role=UserRole.STAFF.value,
                                    phone="13700000003")
        cust1 = await _ensure_user(db, username="demo", password="123456",
                                   real_name="张女士", role=UserRole.CUSTOMER.value,
                                   phone="13800001111")
        cust2 = await _ensure_user(db, username="liu", password="123456",
                                   real_name="刘先生", role=UserRole.CUSTOMER.value,
                                   phone="13900002222")

        pets = [
            await _ensure_pet(db, user=cust1, name="豆豆", species="dog", breed="金毛寻回犬",
                              gender="male", birthday=date(2019, 4, 12), weight=28.5,
                              sterilized=1, staff_id=staff1.id),
            await _ensure_pet(db, user=cust1, name="咪咪", species="cat", breed="英国短毛猫",
                              gender="female", birthday=date(2022, 8, 3), weight=4.2,
                              sterilized=1, staff_id=staff1.id),
            await _ensure_pet(db, user=cust2, name="旺财", species="dog", breed="柯基",
                              gender="male", birthday=date(2021, 1, 20), weight=12.0,
                              allergy="对含燕麦成分的浴液过敏", skin_disease="季节性湿疹（左前肢）",
                              stress=2, aggressive=1, sterilized=0, staff_id=staff2.id),
        ]

        # 疫苗驱虫记录
        if not (await db.execute(select(func.count()).select_from(VaccineRecord))).scalar():
            db.add_all([
                VaccineRecord(pet_id=pets[0].id, record_type="vaccine", name="狂犬疫苗",
                              record_date=date.today() - timedelta(days=200),
                              next_date=date.today() + timedelta(days=165)),
                VaccineRecord(pet_id=pets[0].id, record_type="deworm_outer", name="体外驱虫-福来恩",
                              record_date=date.today() - timedelta(days=40),
                              next_date=date.today() + timedelta(days=20)),
                VaccineRecord(pet_id=pets[2].id, record_type="deworm_inner", name="体内驱虫-拜宠清",
                              record_date=date.today() - timedelta(days=70),
                              next_date=date.today() - timedelta(days=10)),
            ])
            await db.flush()

        # 演示宠物统一保证「有至少一年有效期的疫苗」：寄养是硬门槛，
        # 演示数据缺这条会让用户一进寄养页就被拦（V8.2 反馈的问题）。幂等：已有则跳过。
        for demo_pet in pets[:3]:
            has_long = await db.scalar(
                select(func.count()).select_from(VaccineRecord).where(
                    VaccineRecord.pet_id == demo_pet.id,
                    VaccineRecord.record_type == "vaccine",
                    VaccineRecord.next_date >= date.today() + timedelta(days=365),
                )
            )
            if not has_long:
                db.add(VaccineRecord(
                    pet_id=demo_pet.id, record_type="vaccine", name="狂犬疫苗（演示数据）",
                    record_date=date.today() - timedelta(days=30),
                    next_date=date.today() + timedelta(days=730),
                ))
        await db.flush()

        # 预约历史（近 30 天）用于报表演示
        exist_count = (await db.execute(select(func.count()).select_from(Appointment))).scalar() or 0
        if exist_count == 0:
            services = [s.value for s in ServiceType]
            staff_pool = [staff1.id, staff2.id]
            plan = [
                (AppointmentStatus.COMPLETED, 0.55),
                (AppointmentStatus.CANCELLED, 0.10),
                (AppointmentStatus.NO_SHOW, 0.06),
                (AppointmentStatus.ARRIVED_GIVE_UP, 0.04),
                (AppointmentStatus.WASH_INTERRUPT, 0.04),
                (AppointmentStatus.CONFIRMED, 0.11),
                (AppointmentStatus.PENDING, 0.10),
            ]
            slots = settings.slot_list()
            created = 0
            for offset in range(29, -1, -1):
                day = date.today() - timedelta(days=offset)
                for _ in range(random.randint(1, 4)):
                    status = random.choices([p[0] for p in plan], weights=[p[1] for p in plan])[0]
                    pet = random.choice(pets)
                    staff_id = random.choice(staff_pool)
                    appt = Appointment(
                        order_no=gen_order_no(),
                        user_id=pet.user_id,
                        pet_id=pet.id,
                        service_type=random.choice(services),
                        appoint_date=day,
                        slot_time=random.choice(slots),
                        status=status,
                        staff_id=staff_id if status != AppointmentStatus.PENDING else None,
                        created_by="form",
                        reschedule_times=random.choice([0, 0, 0, 1]),
                    )
                    if status in (AppointmentStatus.ARRIVED_GIVE_UP, AppointmentStatus.WASH_INTERRUPT):
                        appt.terminate_reason = (
                            "宠主临时有事，放弃本次洗护" if status == AppointmentStatus.ARRIVED_GIVE_UP
                            else "洗护中宠物强烈应激，经宠主同意中断"
                        )
                    if status == AppointmentStatus.CANCELLED:
                        appt.cancel_reason = "宠主行程变更"
                    if status == AppointmentStatus.NO_SHOW:
                        appt.terminate_reason = "预约时间未到店"
                    db.add(appt)
                    await db.flush()
                    await risk_service.assess_risk(db, appt, pet, use_llm=False)
                    if status == AppointmentStatus.COMPLETED:
                        db.add(WashRecord(
                            appointment_id=appt.id, pet_id=pet.id, staff_id=staff_id,
                            service_type=appt.service_type,
                            wash_start=datetime.combine(day, datetime.min.time()),
                            wash_end=datetime.combine(day, datetime.min.time()),
                            skin_condition="洗护后皮肤状况良好", hair_condition="毛发顺滑",
                            products="低敏沐浴露",
                        ))
                    created += 1

            # 今日 + 明日预约，便于演示状态机
            for day_offset, status in ((0, AppointmentStatus.PENDING),
                                       (1, AppointmentStatus.CONFIRMED)):
                day = date.today() + timedelta(days=day_offset)
                appt = Appointment(
                    order_no=gen_order_no(), user_id=cust1.id, pet_id=pets[0].id,
                    service_type=ServiceType.GROOMING.value, appoint_date=day,
                    slot_time="10:00", status=status,
                    staff_id=staff1.id if status == AppointmentStatus.CONFIRMED else None,
                    created_by="form",
                )
                db.add(appt)
                await db.flush()
                await risk_service.assess_risk(db, appt, pets[0], use_llm=False)
                created += 1

            # 一条高风险预约（旺财：攻击倾向 + 皮肤病 + 过敏），用于演示风险复核
            appt = Appointment(
                order_no=gen_order_no(), user_id=cust2.id, pet_id=pets[2].id,
                service_type=ServiceType.MEDICATED_BATH.value, appoint_date=date.today(),
                slot_time="14:00", status=AppointmentStatus.PENDING.value, created_by="form",
            )
            db.add(appt)
            await db.flush()
            await risk_service.assess_risk(db, appt, pets[2])
            created += 1
            print(f"     已生成预约 {created} 条")

        # 演示站内消息
        if not (await db.execute(select(func.count()).select_from(Message))).scalar():
            db.add_all([
                Message(user_id=cust1.id, title="欢迎使用宠物洗护预约系统",
                        content="您可以在此管理宠物档案、发起洗护预约并查看风险提示。",
                        msg_type="system"),
                Message(user_id=staff1.id, title="今日有 1 条待确认预约",
                        content="请及时确认宠主提交的洗护预约，超时将触发 SLA 升级提醒。",
                        msg_type="system"),
            ])

        await db.commit()
        await _seed_demo_pet_house(db)
        await db.commit()
        print("[3/3] 演示数据灌入完成")
        print("     账号：admin/admin123（店长） staff1/staff123（店员） demo/123456（宠主）")


async def main() -> None:
    parser = argparse.ArgumentParser(description="宠物洗护系统初始化")
    parser.add_argument("--reset", action="store_true", help="清空业务表后重新灌数据")
    parser.add_argument("--skip-migrate", action="store_true", help="跳过 alembic 迁移")
    args = parser.parse_args()

    create_database()
    if not args.skip_migrate:
        run_migration()
    await seed_data(reset=args.reset)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
