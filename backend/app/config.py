"""全局配置：所有可变参数走环境变量 / .env，禁止硬编码密钥。"""
from __future__ import annotations

import base64
import hashlib
from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 目录类配置一律以本文件位置为锚点解析，不依赖进程 cwd。
# 曾经 CHROMA_DIR / KB_UPLOAD_DIR 写成相对路径，从项目根跑脚本就会在根目录
# 另建一份 data/，与 backend/data/ 分裂成两个向量库 / 两个上传目录（见 docs/01）。
_BACKEND_DIR = Path(__file__).resolve().parent.parent


def _anchor_dir(raw: str) -> str:
    """把目录配置锚定到 backend 目录：绝对路径原样保留，相对路径按 backend 解析。"""
    p = Path(raw)
    return str(p if p.is_absolute() else _BACKEND_DIR / p)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=True
    )

    # ---------- 应用 ----------
    APP_NAME: str = "宠物洗护门店预约与洗护档案智能体"
    # 与路线图版本对齐：当前实现覆盖到 V4（中心单 Agent + 全量 UI）
    APP_VERSION: str = "8.6.2"
    DEBUG: bool = True
    API_PREFIX: str = "/api/v1"

    # ---------- MySQL ----------
    MYSQL_HOST: str = "127.0.0.1"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = "yeyaoyan"
    MYSQL_DB: str = "pet_groom"

    # ---------- JWT ----------
    JWT_SECRET: str = "pet-groom-dev-secret-change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120   # Access-Token 2h
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7       # Refresh-Token 7d

    # ---------- 敏感数据加密（手机号 AES 可逆加密） ----------
    # Fernet key（32 字节 urlsafe base64）。留空则从 JWT_SECRET 派生，便于本地开发。
    PHONE_AES_KEY: str = ""

    # ---------- CORS ----------
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173"

    # ---------- LLM（阿里云百炼 / DashScope，OpenAI 兼容模式） ----------
    # 模型来源：百炼控制台「费用与配额 - 免费额度」页面。
    # 免费额度模型清单会随活动调整，因此这里做成**可配置的免费模型链**，
    # 不把型号硬编码在业务代码里；用 scripts/check_llm.py 探测实际可用性。
    LLM_ENABLED: bool = True
    LLM_PROVIDER: str = "bailian"
    DASHSCOPE_API_KEY: str = ""
    LLM_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    # 主模型：qwen3.7-max（2026-10-28 起；qwen-max 免费额度已用尽且不再使用）
    # 经验：意图识别在主链路、延迟敏感，但可用性优先——先保证能跑通，再谈快不快。
    LLM_MODEL: str = "qwen3.7-max-2026-06-08"
    # 备选链（均为百炼 OpenAI 兼容端点）：
    #   glm-5.1                 4.3~5.7s，JSON 可用 —— 跨厂商兜底
    # 已排除：qwen-max（免费额度用尽，403）、glm-5.2（HTTP 200 但 content 恒为空，
    #         tokens 全落在 reasoning 上）、glm-5（10.1s）、qwen3.7-plus（8.4s）、
    #         qwen3.7-flash（3~6s，v8.3 起已不用）、qwen-flash（额度将尽）、qwen-turbo（429）
    LLM_FALLBACK_MODELS: str = "glm-5.1"
    LLM_TIMEOUT_SECONDS: int = 30
    LLM_MAX_RETRIES: int = 1
    LLM_TEMPERATURE: float = 0.2

    # ---------- RAG：LlamaIndex + Chroma（V8.4 起参照参考项目写法）----------
    # embedding 实测（2026-10-20，兼容模式 /embeddings）：
    #   text-embedding-v4          ✅ 336ms / 1024 维（最快，默认主模型）
    #   qwen3.7-text-embedding     ✅ 742ms / 1024 维（备选）
    #   qwen3-vl-embedding         ❌ 兼容模式不支持（多模态需原生接口）
    #   text-embedding-async-v1/v2 ❌ 兼容模式不支持（异步批量接口）
    EMBED_MODEL: str = "text-embedding-v4"
    EMBED_FALLBACK_MODELS: str = "qwen3.7-text-embedding"
    EMBED_TIMEOUT_SECONDS: int = 15
    # 向量库持久化目录（相对 backend 运行目录）；索引可随时用 scripts/index_knowledge.py 重建
    CHROMA_DIR: str = "data/chroma"
    # 召回后重排（可选）：qwen3-rerank / qwen3-vl-rerank / gte-rerank-v2 实测均可用（0.3~0.6s）
    RERANK_ENABLED: bool = True
    RERANK_MODEL: str = "qwen3-rerank"
    RERANK_URL: str = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
    RERANK_TIMEOUT_SECONDS: int = 10

    # ---------- 知识库文档上传与切块（店长管理、店员只读） ----------
    KB_UPLOAD_DIR: str = "data/knowledge_uploads"
    KB_ALLOWED_EXTENSIONS: str = "pdf,docx,txt,md,markdown"
    KB_MAX_FILE_MB: int = 20
    KB_MAX_BATCH_FILES: int = 5
    KB_DEFAULT_CHUNK_STRATEGY: str = "heading"
    KB_DEFAULT_CHUNK_SIZE: int = 500
    KB_DEFAULT_CHUNK_OVERLAP: int = 50
    KB_MIN_CHUNK_SIZE: int = 100
    KB_MAX_CHUNK_SIZE: int = 4000
    KB_MAX_CHUNK_OVERLAP: int = 1000
    KB_MAX_CONCURRENT_TASKS: int = 2

    LLM_MAX_TOKENS: int = 1024
    # ReAct 单轮最大工具调用轮次（防死循环）
    AGENT_MAX_STEPS: int = 6

    # ---------- 会话级并发锁（V8）----------
    # 同一会话的并发消息串行化，避免两条 ReAct 循环各自跑一遍写工具
    CHAT_SESSION_LOCK_ENABLED: bool = True
    CHAT_SESSION_LOCK_WAIT_SECONDS: int = 20   # 后到消息最多等多久，超时回友好提示

    # ---------- 定时任务调度（进程内置调度器；生产可换 arq，任务函数不变） ----------
    TASK_SCHEDULER_ENABLED: bool = True
    TASK_SLA_INTERVAL_MINUTES: int = 15       # 店员确认 SLA 巡检
    TASK_REMINDER_INTERVAL_MINUTES: int = 720  # 疫苗临期 / 复购回访提醒
    TASK_CLEANUP_INTERVAL_MINUTES: int = 1440  # 会话清理 / 锁行清理

    # ---------- 业务默认值（兜底，正式值以 store_setting 表为准） ----------
    DEFAULT_SLOT_START_HOUR: int = 9
    DEFAULT_SLOT_END_HOUR: int = 19
    SLOT_MINUTES: int = 60

    @property
    def database_url(self) -> str:
        return (
            f"mysql+aiomysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DB}?charset=utf8mb4"
        )

    @property
    def sync_database_url(self) -> str:
        """alembic 迁移用同步驱动。"""
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DB}?charset=utf8mb4"
        )

    @property
    def fernet_key(self) -> bytes:
        if self.PHONE_AES_KEY:
            return self.PHONE_AES_KEY.encode()
        digest = hashlib.sha256(self.JWT_SECRET.encode()).digest()
        return base64.urlsafe_b64encode(digest)

    @property
    def phone_hmac_secret(self) -> bytes:
        return hashlib.sha256(("hmac:" + self.JWT_SECRET).encode()).digest()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def llm_model_chain(self) -> list[str]:
        """免费模型链：主模型优先，其后为备选，去重保序。"""
        chain = [self.LLM_MODEL.strip()]
        chain += [m.strip() for m in self.LLM_FALLBACK_MODELS.split(",") if m.strip()]
        seen: set[str] = set()
        return [m for m in chain if m and not (m in seen or seen.add(m))]

    @property
    def embed_fallback_models(self) -> list[str]:
        """embedding 备选（去重、去空）。"""
        return [m.strip() for m in self.EMBED_FALLBACK_MODELS.split(",") if m.strip()]

    @property
    def knowledge_allowed_extensions(self) -> set[str]:
        """知识库允许上传的扩展名（小写、不含点）。"""
        return {ext.strip().lower().lstrip(".") for ext in self.KB_ALLOWED_EXTENSIONS.split(",") if ext.strip()}

    @property
    def llm_available(self) -> bool:
        """未配置 API Key 时自动降级：风险判别走规则引擎，Agent 对话入口关闭。"""
        return bool(self.LLM_ENABLED and self.DASHSCOPE_API_KEY.strip())

    def slot_list(self) -> list[str]:
        return [
            f"{h:02d}:00"
            for h in range(self.DEFAULT_SLOT_START_HOUR, self.DEFAULT_SLOT_END_HOUR)
        ]

    @model_validator(mode="after")
    def _anchor_directories(self) -> "Settings":
        """目录类配置锚定到 backend 目录，避免 cwd 不同导致向量库 / 上传目录分裂。"""
        self.CHROMA_DIR = _anchor_dir(self.CHROMA_DIR)
        self.KB_UPLOAD_DIR = _anchor_dir(self.KB_UPLOAD_DIR)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
