"""Text chunking utilities for project-memory ingestion."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import re

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - optional dependency guard
    PdfReader = None

MAX_CHARS = 3200
OVERLAP_CHARS = 320


@dataclass
class Chunk:
    content: str
    source_kind: str
    category: str
    module: str | None = None


def _tail_with_overlap(text: str, overlap: int) -> str:
    if overlap <= 0 or not text:
        return ""
    clean = text.strip()
    if len(clean) <= overlap:
        return clean
    start = len(clean) - overlap
    while start > 0 and not clean[start - 1].isspace():
        start -= 1
    return clean[start:].strip()


def _looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if len(stripped) > 80:
        return False
    if stripped.endswith((".", "!", "?", ",")):
        return False
    alpha = [char for char in stripped if char.isalpha()]
    if not alpha:
        return False
    if stripped.isupper():
        return True
    title_ratio = sum(1 for word in stripped.split() if word[:1].isupper()) / max(len(stripped.split()), 1)
    return title_ratio >= 0.7


def _starts_structured_block(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if re.match(r"^([-*•]\s+|\d+[.)]\s+|\[[A-Z]+\])", stripped):
        return True
    return _looks_like_heading(stripped)


def split_pdf_blocks(text: str) -> list[str]:
    paragraphs = [
        " ".join(part.split())
        for part in re.split(r"\n\s*\n+", text)
        if part and part.strip()
    ]
    if len(paragraphs) > 1:
        return paragraphs

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    blocks: list[str] = []
    bucket: list[str] = []
    for line in lines:
        if bucket and _starts_structured_block(line):
            blocks.append(" ".join(bucket).strip())
            bucket = [line]
            continue
        bucket.append(line)

    if bucket:
        blocks.append(" ".join(bucket).strip())
    return [block for block in blocks if block]


def chunk_text_by_blocks(
    text: str,
    *,
    max_chars: int = MAX_CHARS,
    overlap: int = OVERLAP_CHARS,
    max_blocks_per_chunk: int = 2,
) -> list[str]:
    blocks = split_pdf_blocks(text)
    if not blocks:
        return chunk_text(text, max_chars=max_chars, overlap=overlap)

    chunks: list[str] = []
    current = ""
    block_count = 0
    for block in blocks:
        if len(block) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
                block_count = 0
            chunks.extend(chunk_text(block, max_chars=max_chars, overlap=overlap))
            continue

        candidate = block if not current else f"{current}\n\n{block}"
        should_finalize = (
            current
            and (
                len(candidate) > max_chars
                or block_count >= max_blocks_per_chunk
            )
        )
        if should_finalize:
            finalized = current.strip()
            if finalized:
                chunks.append(finalized)
            overlap_tail = _tail_with_overlap(finalized, overlap)
            current = f"{overlap_tail}\n\n{block}".strip() if overlap_tail else block
            block_count = 1 if block else 0
        else:
            current = candidate
            block_count += 1

    if current.strip():
        chunks.append(current.strip())

    if chunks:
        return chunks
    return chunk_text(text, max_chars=max_chars, overlap=overlap)


def chunk_text(text: str, max_chars: int = MAX_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    clean = text.strip()
    if not clean:
        return []
    if len(clean) <= max_chars:
        return [clean]

    chunks: list[str] = []
    start = 0
    while start < len(clean):
        end = min(start + max_chars, len(clean))
        chunks.append(clean[start:end].strip())
        if end == len(clean):
            break
        start = max(0, end - overlap)
    return [chunk for chunk in chunks if chunk]


def chunk_markdown_by_headings(path: Path, text: str) -> list[Chunk]:
    lines = text.splitlines()
    current_heading = path.name
    bucket: list[str] = []
    sections: list[tuple[str, str]] = []

    for line in lines:
        if line.startswith("#"):
            if bucket:
                sections.append((current_heading, "\n".join(bucket).strip()))
            current_heading = line.lstrip("#").strip() or path.name
            bucket = []
            continue
        bucket.append(line)

    if bucket:
        sections.append((current_heading, "\n".join(bucket).strip()))

    chunks: list[Chunk] = []
    for heading, body in sections:
        if not body:
            continue
        text_value = f"[{path}] {heading}\n\n{body}"
        for piece in chunk_text(text_value):
            chunks.append(Chunk(content=piece, source_kind="doc", category="documentation"))
    return chunks


def chunk_python_docstrings(path: Path, text: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return chunks

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        docstring = ast.get_docstring(node)
        if not docstring:
            continue
        if isinstance(node, ast.Module):
            module_name = path.stem
            label = f"module::{path}"
        elif isinstance(node, ast.ClassDef):
            module_name = node.name
            label = f"class::{path}::{node.name}"
        else:
            module_name = node.name
            label = f"function::{path}::{node.name}"

        content = f"[{label}]\n{docstring.strip()}"
        for piece in chunk_text(content):
            chunks.append(Chunk(content=piece, source_kind="code", category="code", module=module_name))
    return chunks


def chunk_python_code(path: Path, text: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        for piece in chunk_text(text):
            chunks.append(Chunk(content=f"[{path}]\n{piece}", source_kind="code", category="code"))
        return chunks

    file_lines = text.splitlines()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if not hasattr(node, "lineno") or not hasattr(node, "end_lineno"):
            continue
        start = max(node.lineno - 1, 0)
        end = max(node.end_lineno, start + 1)
        source = "\n".join(file_lines[start:end]).strip()
        if not source:
            continue
        label = f"{path}::{node.name}"
        for piece in chunk_text(source):
            chunks.append(Chunk(content=f"[{label}]\n{piece}", source_kind="code", category="code", module=node.name))

    if not chunks:
        for piece in chunk_text(text):
            chunks.append(Chunk(content=f"[{path}]\n{piece}", source_kind="code", category="code", module=path.stem))
    return chunks


def chunk_pdf_document(path: Path) -> list[Chunk]:
    if PdfReader is None:
        raise RuntimeError(
            "PDF ingestion requires 'pypdf'. Install it in the memory environment and retry."
        )

    reader = PdfReader(str(path))
    chunks: list[Chunk] = []
    for page_number, page in enumerate(reader.pages, start=1):
        page_text = (page.extract_text() or "").strip()
        if not page_text:
            continue
        page_label = f"{path}::page-{page_number}"
        pieces = chunk_text_by_blocks(page_text)
        for chunk_number, piece in enumerate(pieces, start=1):
            chunk_label = f"{page_label}::chunk-{chunk_number}"
            chunks.append(
                Chunk(
                    content=f"[{chunk_label}]\n{piece}",
                    source_kind="doc",
                    category="documentation",
                    module=f"page-{page_number}::chunk-{chunk_number}",
                )
            )

    if chunks:
        return chunks

    return [
        Chunk(
            content=f"[{path}]\n(No extractable text found in PDF.)",
            source_kind="doc",
            category="documentation",
        )
    ]


def chunk_file(path: Path, mode: str) -> list[Chunk]:
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return chunk_pdf_document(path)

    text = path.read_text(encoding="utf-8", errors="ignore")

    if suffix == ".py":
        if mode == "docstrings":
            return chunk_python_docstrings(path, text)
        if mode == "code-chunks":
            return chunk_python_code(path, text)
        if mode == "mixed":
            return chunk_python_docstrings(path, text) + chunk_python_code(path, text)

    if suffix in {".md", ".rst", ".txt"}:
        if mode in {"headings", "mixed"}:
            return chunk_markdown_by_headings(path, text)

    return [Chunk(content=f"[{path}]\n{piece}", source_kind="doc", category="documentation") for piece in chunk_text(text)]
