"""知识文档解析与可追溯文本切块（纯函数，不访问数据库）。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.constants import KnowledgeChunkStrategy
from app.schemas.knowledge import KnowledgeChunkConfig
from app.utils.exceptions import BizError


@dataclass(slots=True)
class ParsedBlock:
    text: str
    page_no: int | None = None
    paragraph_no: int | None = None
    heading: str | None = None
    heading_level: int | None = None


@dataclass(slots=True)
class _Span:
    start: int
    end: int
    block: ParsedBlock


def _decode_text(data: bytes, filename: str) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding).replace("\x00", "").strip()
        except UnicodeDecodeError:
            continue
    raise BizError(f"{filename}：文本编码无法识别，请另存为 UTF-8 后重试")


def text_blocks(text: str, *, markdown: bool) -> list[ParsedBlock]:
    blocks: list[ParsedBlock] = []
    buffer: list[str] = []
    paragraph_no = 0
    current_heading: str | None = None

    def flush() -> None:
        nonlocal paragraph_no
        value = "\n".join(buffer).strip()
        buffer.clear()
        if value:
            paragraph_no += 1
            blocks.append(ParsedBlock(value, paragraph_no=paragraph_no, heading=current_heading))

    for raw in text.splitlines():
        line = raw.strip()
        match = re.match(r"^(#{1,6})\s+(.+)$", line) if markdown else None
        if match:
            flush()
            paragraph_no += 1
            current_heading = match.group(2).strip()
            blocks.append(ParsedBlock(
                current_heading,
                paragraph_no=paragraph_no,
                heading=current_heading,
                heading_level=len(match.group(1)),
            ))
        elif not line:
            flush()
        else:
            buffer.append(line)
    flush()
    return blocks


def _parse_docx(path: Path) -> list[ParsedBlock]:
    try:
        from docx import Document as DocxDocument
    except ImportError as exc:  # pragma: no cover - 部署依赖缺失
        raise BizError("服务器缺少 Word 解析组件，请联系管理员安装 python-docx") from exc
    try:
        doc = DocxDocument(str(path))
    except Exception as exc:
        raise BizError(f"Word 文档解析失败：{str(exc)[:160]}") from exc
    blocks: list[ParsedBlock] = []
    current_heading: str | None = None
    paragraph_no = 0
    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        paragraph_no += 1
        style_name = (paragraph.style.name if paragraph.style else "") or ""
        match = re.search(r"Heading\s*(\d+)|标题\s*(\d+)", style_name, re.I)
        heading_level = int(next((x for x in (match.group(1), match.group(2)) if x), "1")) if match else None
        if heading_level:
            current_heading = text
        blocks.append(ParsedBlock(
            text,
            paragraph_no=paragraph_no,
            heading=current_heading,
            heading_level=heading_level,
        ))
    return blocks


def _looks_like_heading(text: str) -> bool:
    value = text.strip()
    return bool(
        2 <= len(value) <= 80
        and (re.match(r"^(第[一二三四五六七八九十\d]+[章节部分]|[一二三四五六七八九十\d]+[、.．])", value)
             or value.endswith(("须知", "规范", "流程", "说明", "要点", "注意事项")))
    )


def _parse_pdf(path: Path) -> list[ParsedBlock]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - 部署依赖缺失
        raise BizError("服务器缺少 PDF 解析组件，请联系管理员安装 pypdf") from exc
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:
                raise BizError("PDF 已加密，无法解析，请先解除密码保护") from exc
        blocks: list[ParsedBlock] = []
        paragraph_no = 0
        current_heading: str | None = None
        for page_no, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").replace("\x00", "").strip()
            raw_parts = re.split(r"\n\s*\n", text) if "\n\n" in text else text.splitlines()
            for raw in raw_parts:
                value = re.sub(r"\s+", " ", raw).strip()
                if not value:
                    continue
                paragraph_no += 1
                heading_level = 1 if _looks_like_heading(value) else None
                if heading_level:
                    current_heading = value
                blocks.append(ParsedBlock(
                    value,
                    page_no=page_no,
                    paragraph_no=paragraph_no,
                    heading=current_heading,
                    heading_level=heading_level,
                ))
        return blocks
    except BizError:
        raise
    except Exception as exc:
        raise BizError(f"PDF 解析失败：{str(exc)[:160]}") from exc


def parse_document(path: Path, ext: str, original_name: str) -> list[ParsedBlock]:
    if not path.exists():
        raise BizError(f"原始文件不存在：{original_name}")
    if ext in {"txt", "md", "markdown"}:
        text = _decode_text(path.read_bytes(), original_name)
        blocks = text_blocks(text, markdown=ext in {"md", "markdown"})
    elif ext == "docx":
        blocks = _parse_docx(path)
    elif ext == "pdf":
        blocks = _parse_pdf(path)
    else:
        raise BizError(f"不支持解析 .{ext} 文件")
    if not blocks or not any(block.text.strip() for block in blocks):
        hint = "；扫描版 PDF 请先做 OCR" if ext == "pdf" else ""
        raise BizError(f"{original_name}：没有提取到可用文字{hint}")
    return blocks


def _flatten_blocks(blocks: list[ParsedBlock]) -> tuple[str, list[_Span]]:
    parts: list[str] = []
    spans: list[_Span] = []
    cursor = 0
    for block in blocks:
        text = block.text.strip()
        if not text:
            continue
        if parts:
            parts.append("\n\n")
            cursor += 2
        start = cursor
        parts.append(text)
        cursor += len(text)
        spans.append(_Span(start, cursor, block))
    return "".join(parts), spans


def _fixed_segments(start: int, end: int, size: int, overlap: int) -> list[tuple[int, int]]:
    segments: list[tuple[int, int]] = []
    cursor = start
    while cursor < end:
        stop = min(cursor + size, end)
        segments.append((cursor, stop))
        if stop >= end:
            break
        cursor = max(cursor + 1, stop - overlap)
    return segments


def _paragraph_segments(text_len: int, spans: list[_Span], size: int, overlap: int) -> list[tuple[int, int]]:
    boundaries = sorted({span.end for span in spans})
    segments: list[tuple[int, int]] = []
    start = 0
    while start < text_len:
        target = min(start + size, text_len)
        eligible = [boundary for boundary in boundaries if start < boundary <= target]
        end = max(eligible) if eligible else target
        segments.append((start, end))
        if end >= text_len:
            break
        start = max(start + 1, end - overlap)
    return segments


def _heading_segments(text: str, spans: list[_Span], size: int, overlap: int) -> list[tuple[int, int, str | None]]:
    headings = [(span.start, span.block.heading or span.block.text) for span in spans if span.block.heading_level]
    if not headings:
        return [(a, b, None) for a, b in _paragraph_segments(len(text), spans, size, overlap)]
    sections: list[tuple[int, int, str | None]] = []
    first_start = headings[0][0]
    if first_start > 0:
        sections.extend((a, b, None) for a, b in _fixed_segments(0, first_start, size, overlap))
    for index, (start, title) in enumerate(headings):
        end = headings[index + 1][0] if index + 1 < len(headings) else len(text)
        sections.extend((a, b, title) for a, b in _fixed_segments(start, end, size, overlap))
    return sections


def chunk_blocks(
    blocks: list[ParsedBlock], *, original_name: str, config: KnowledgeChunkConfig
) -> tuple[list[dict], int]:
    text, spans = _flatten_blocks(blocks)
    if not text.strip():
        raise BizError(f"{original_name}：解析结果为空")
    if config.strategy == KnowledgeChunkStrategy.FIXED:
        segments = [(a, b, None) for a, b in _fixed_segments(0, len(text), config.chunk_size, config.chunk_overlap)]
    elif config.strategy == KnowledgeChunkStrategy.PARAGRAPH:
        segments = [(a, b, None) for a, b in _paragraph_segments(
            len(text), spans, config.chunk_size, config.chunk_overlap
        )]
    else:
        segments = _heading_segments(text, spans, config.chunk_size, config.chunk_overlap)

    chunks: list[dict] = []
    for start, end, explicit_title in segments:
        content = text[start:end].strip()
        if not content:
            continue
        touched = [span.block for span in spans if span.start < end and span.end > start]
        pages = [block.page_no for block in touched if block.page_no is not None]
        paragraphs = [block.paragraph_no for block in touched if block.paragraph_no is not None]
        title = explicit_title or next((block.heading for block in touched if block.heading), None)
        source_parts = [original_name]
        if pages:
            source_parts.append(f"第{min(pages)}页" if min(pages) == max(pages) else f"第{min(pages)}-{max(pages)}页")
        elif paragraphs:
            source_parts.append(
                f"第{min(paragraphs)}段" if min(paragraphs) == max(paragraphs)
                else f"第{min(paragraphs)}-{max(paragraphs)}段"
            )
        if title:
            source_parts.append(title[:80])
        chunks.append({
            "chunk_index": len(chunks),
            "section_title": title[:255] if title else None,
            "content": content,
            "page_start": min(pages) if pages else None,
            "page_end": max(pages) if pages else None,
            "paragraph_start": min(paragraphs) if paragraphs else None,
            "paragraph_end": max(paragraphs) if paragraphs else None,
            "char_start": start,
            "char_end": end,
            "source_label": " · ".join(source_parts)[:500],
        })
    if not chunks:
        raise BizError(f"{original_name}：切块结果为空，请调整块大小后重试")
    return chunks, len(text)
