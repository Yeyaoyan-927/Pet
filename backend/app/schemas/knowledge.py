"""知识库管理接口入参。"""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from app.config import settings
from app.constants import KnowledgeChunkStrategy


class KnowledgeChunkConfig(BaseModel):
    strategy: KnowledgeChunkStrategy = KnowledgeChunkStrategy.HEADING
    chunk_size: int = Field(default=settings.KB_DEFAULT_CHUNK_SIZE)
    chunk_overlap: int = Field(default=settings.KB_DEFAULT_CHUNK_OVERLAP, ge=0)

    @model_validator(mode="after")
    def validate_limits(self) -> "KnowledgeChunkConfig":
        if not settings.KB_MIN_CHUNK_SIZE <= self.chunk_size <= settings.KB_MAX_CHUNK_SIZE:
            raise ValueError(
                f"块大小须在 {settings.KB_MIN_CHUNK_SIZE}~{settings.KB_MAX_CHUNK_SIZE} 之间"
            )
        max_overlap = min(settings.KB_MAX_CHUNK_OVERLAP, self.chunk_size - 1)
        if self.chunk_overlap > max_overlap:
            raise ValueError(f"重叠长度须小于块大小，且不能超过 {settings.KB_MAX_CHUNK_OVERLAP}")
        return self


class KnowledgeSearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    limit: int = Field(default=5, ge=1, le=20)
