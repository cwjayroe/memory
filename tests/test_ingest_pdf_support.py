from __future__ import annotations

from pathlib import Path

from memory_core import chunking as chunking_module
import ingest as ingest_module
import pytest


class _FakePdfPage:
    def __init__(self, text: str):
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _FakePdfReader:
    def __init__(self, _path: str):
        self.pages = [
            _FakePdfPage("Discounts PRD\nEligibility rules and constraints."),
            _FakePdfPage("Acceptance criteria and rollout notes."),
        ]


def test_chunk_file_pdf_extracts_text(monkeypatch, tmp_path: Path):
    pdf_path = tmp_path / "discounts-prd.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test")

    monkeypatch.setattr(chunking_module, "PdfReader", _FakePdfReader)

    chunks = ingest_module.chunk_file(pdf_path, mode="headings")

    assert chunks
    assert all(chunk.category == "documentation" for chunk in chunks)
    assert any("page-1" in (chunk.module or "") for chunk in chunks)
    assert any("Eligibility rules" in chunk.content for chunk in chunks)


def test_chunk_file_pdf_requires_pypdf(monkeypatch, tmp_path: Path):
    pdf_path = tmp_path / "discounts-prd.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test")

    monkeypatch.setattr(chunking_module, "PdfReader", None)

    with pytest.raises(RuntimeError, match="pypdf"):
        ingest_module.chunk_file(pdf_path, mode="headings")
