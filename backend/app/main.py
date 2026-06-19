"""FastAPI 应用入口。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.database import AsyncSessionLocal
from app.routers import (
    agent,
    appointment,
    auth,
    boarding,
    camera,
    chat,
    goods,
    knowledge,
    message,
    pet,
    report,
    risk,
    schedule,
    store_setting,
    tasks,
    user,
    wash,
)
from app.services import setting_service
from app.services import knowledge_ingest_service
from app.tasks import scheduler
from app.utils.exceptions import BizError
from app.utils.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时补齐门店配置默认值，保证业务参数永不缺失。"""
    try:
        async with AsyncSessionLocal() as db:
            added = await setting_service.seed_defaults(db)
            await db.commit()
        resumed_tasks = await knowledge_ingest_service.resume_unfinished_tasks()
        logger.info("startup", extra={"extra_fields": {"seeded_settings": added,
                                                       "resumed_knowledge_tasks": resumed_tasks,
                                                       "version": settings.APP_VERSION}})
    except Exception as exc:  # pragma: no cover - 数据库不可用时允许应用起来做健康检查
        logger.error("startup failed: %s", exc)
    # 内置定时任务调度器（SLA 巡检 / 临期提醒 / 复购回访 / 会话清理 / 锁行清理）
    scheduler.start()
    yield
    await scheduler.stop()
    logger.info("shutdown")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "宠物洗护门店预约与洗护档案智能体 —— V8（多角色 Agent + 定时任务 + RAG + 宠物之家；含并发防护与降级验收）。\n\n"
        "核心原则：**规则保证业务正确性，AI/RAG 提升业务效率；"
        "所有写操作绝不交由 LLM 直接执行，必须经过业务服务层。**"
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------- 全局异常处理：统一返回 {code, message, data} ----------------
@app.exception_handler(BizError)
async def biz_error_handler(request: Request, exc: BizError):
    return JSONResponse(
        status_code=exc.http_status,
        content={"code": exc.code, "message": exc.message, "data": None},
    )


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(x) for x in first.get("loc", [])[1:]) or "参数"
    msg = first.get("msg", "参数校验失败")
    return JSONResponse(
        status_code=422,
        content={"code": 4220, "message": f"{loc}：{msg}", "data": None},
    )


@app.exception_handler(StarletteHTTPException)
async def http_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code * 10, "message": str(exc.detail), "data": None},
    )


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):  # pragma: no cover
    logger.error("unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"code": 5000, "message": "服务内部错误，请稍后重试", "data": None},
    )


# 静态文件（抓拍图片等）；目录不存在时自动创建
_UPLOAD_DIR = Path("uploads")
_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_UPLOAD_DIR)), name="static")


# ---------------- 路由注册 ----------------
for router in (auth.router, user.router, pet.router, appointment.router,
               risk.router, message.router, store_setting.router, report.router,
               agent.router, chat.router, wash.router, schedule.router,
               tasks.router, knowledge.router, boarding.router,
               goods.router, camera.router):
    app.include_router(router, prefix=settings.API_PREFIX)


@app.get("/health", tags=["系统"], summary="健康检查")
async def health():
    return {"code": 0, "message": "ok",
            "data": {"status": "up", "version": settings.APP_VERSION, "app": settings.APP_NAME,
                     "llm_available": settings.llm_available,
                     "llm_model": settings.LLM_MODEL if settings.llm_available else None}}


@app.get("/", include_in_schema=False)
async def root():
    return {"code": 0, "message": "ok",
            "data": {"app": settings.APP_NAME, "version": settings.APP_VERSION,
                     "docs": "/docs", "api_prefix": settings.API_PREFIX}}
