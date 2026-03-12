from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import chunking as chunking_module
import ingest as ingest_module


class _FakeMemory:
    def __init__(self):
        self.deleted: list[str] = []
        self.add_calls: list[dict] = []

    def delete(self, memory_id: str):
        self.deleted.append(memory_id)

    def add(self, content: str, **kwargs):
        self.add_calls.append({"content": content, **kwargs})
        return {
            "results": [
                {
                    "id": f"stored-{len(self.add_calls)}",
                    "memory": content,
                    "metadata": kwargs.get("metadata", {}),
                }
            ]
        }


def test_chunk_text_empty_short_and_overlap():
    assert chunking_module.chunk_text("   ") == []
    assert chunking_module.chunk_text("short", max_chars=10, overlap=2) == ["short"]

    chunks = chunking_module.chunk_text("abcdefghij", max_chars=5, overlap=2)
    assert chunks == ["abcde", "defgh", "ghij"]


def test_chunk_markdown_by_headings():
    path = Path("product-doc.md")
    text = "# Scope\nline one\n# Constraints\nline two"

    chunks = chunking_module.chunk_markdown_by_headings(path, text)

    assert len(chunks) == 2
    assert all(chunk.category == "documentation" for chunk in chunks)
    assert "Scope" in chunks[0].content
    assert "Constraints" in chunks[1].content


def test_chunk_python_docstrings_extracts_module_class_function():
    path = Path("sample.py")
    text = '''"""module docs"""

class Demo:
    """class docs"""


def run():
    """function docs"""
    return 1
'''

    chunks = chunking_module.chunk_python_docstrings(path, text)

    assert len(chunks) >= 3
    assert all(chunk.source_kind == "code" for chunk in chunks)
    assert {chunk.module for chunk in chunks} >= {"sample", "Demo", "run"}


def test_chunk_python_code_syntax_error_fallback():
    path = Path("broken.py")
    text = "def broken(:\n    pass"

    chunks = chunking_module.chunk_python_code(path, text)

    assert chunks
    assert all(chunk.source_kind == "code" for chunk in chunks)
    assert all(chunk.category == "code" for chunk in chunks)
    assert chunks[0].content.startswith("[broken.py]")


def test_chunk_pdf_document_splits_structured_blocks_and_keeps_page_provenance(tmp_path: Path, monkeypatch):
    pdf_path = tmp_path / "rules.pdf"
    pdf_path.write_text("placeholder")

    class _FakePage:
        def __init__(self, text: str):
            self._text = text

        def extract_text(self):
            return self._text

    class _FakeReader:
        def __init__(self, _path: str):
            self.pages = [
                _FakePage(
                    "\n".join(
                        [
                            "Overview",
                            "General introduction " * 40,
                            "Charge date updates",
                            "If there are multiple queued charges for a subscription, the charge_date of a charge cannot be updated outside of the subscription cadence.",
                            "- Charge 1 cannot move to week 2",
                            "- Charge 2 must stay before week 3",
                        ]
                    )
                )
            ]

    monkeypatch.setattr(chunking_module, "PdfReader", _FakeReader)

    chunks = chunking_module.chunk_pdf_document(pdf_path)

    assert len(chunks) >= 2
    assert all(chunk.category == "documentation" for chunk in chunks)
    assert all(chunk.source_kind == "doc" for chunk in chunks)
    assert all("page-1::chunk-" in (chunk.module or "") for chunk in chunks)
    assert any("Charge date updates" in chunk.content for chunk in chunks)
    assert all(chunk.content.startswith(f"[{pdf_path}::page-1::chunk-") for chunk in chunks)


def test_should_include_and_collect_files(tmp_path: Path):
    (tmp_path / "main.py").write_text("print('ok')")
    (tmp_path / "readme.md").write_text("docs")
    (tmp_path / "ignore").mkdir()
    (tmp_path / "ignore" / "a.py").write_text("print('no')")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "keep.py").write_text("print('yes')")
    (tmp_path / "sub" / "skip.py").write_text("print('skip')")

    include = ["*.py", "**/*.py"]
    exclude = ["ignore/*", "**/skip.py"]

    assert ingest_module.should_include(tmp_path / "main.py", tmp_path, include, exclude) is True
    assert ingest_module.should_include(tmp_path / "readme.md", tmp_path, include, exclude) is False

    files = ingest_module.collect_files(tmp_path, include, exclude)
    rel_paths = [path.relative_to(tmp_path).as_posix() for path in files]
    assert rel_paths == ["main.py", "sub/keep.py"]


def test_ingest_file_deletes_existing_path_entries_and_counts_stored(monkeypatch, tmp_path: Path):
    path = tmp_path / "discounts.py"
    path.write_text("print('discounts')")
    resolved = str(path.resolve())

    items = [
        {"id": "old-path", "metadata": {"repo": "customcheckout", "source_path": resolved}},
        {"id": "other", "metadata": {"repo": "customcheckout", "source_path": "/tmp/other.py"}},
    ]
    chunks = [
        chunking_module.Chunk(content="one", source_kind="code", category="code"),
        chunking_module.Chunk(content="two", source_kind="code", category="code"),
    ]

    deleted_ids: list[str] = []
    stored_ids: list[str] = []

    class _FakeMM:
        def delete_memory(self, request):
            deleted_ids.append(request.memory_id)

        def store_memory(self, request, *, pre_fetched_items=None):
            stored_ids.append(request.upsert_key)
            return 0, [f"stored-{len(stored_ids)}"]

    monkeypatch.setattr(ingest_module, "_get_mem_manager", lambda: _FakeMM())
    monkeypatch.setattr(ingest_module, "chunk_file", lambda _path, _mode: list(chunks))

    deleted, stored = ingest_module.ingest_file(
        items=items,
        project_id="automatic-discounts",
        repo="customcheckout",
        path=path,
        mode="mixed",
        tags=["discounts"],
    )

    assert deleted == 1
    assert stored == 2
    assert deleted_ids == ["old-path"]
    assert len(stored_ids) == 2


def test_run_file_ingest_merges_repo_default_tags(monkeypatch, tmp_path: Path):
    path = tmp_path / "product-doc.pdf"
    path.write_text("placeholder")
    captured: dict[str, object] = {}

    class _RepoConfig:
        default_tags = ["product-docs", "prd"]

    monkeypatch.setattr(ingest_module, "read_manifest", lambda _path: {"repos": {}})
    monkeypatch.setattr(ingest_module, "resolve_repo_config", lambda **_kwargs: _RepoConfig())
    monkeypatch.setattr(ingest_module, "_load_memory_session", lambda _project: (object(), []))

    def _fake_ingest_file(**kwargs):
        captured["tags"] = kwargs["tags"]
        return 0, 1

    monkeypatch.setattr(ingest_module, "ingest_file", _fake_ingest_file)

    request = ingest_module.FileIngestRequest(
        project="multiple-queued-charges",
        repo="product-docs",
        path=path,
        mode="headings",
        tags=["charge-updates"],
    )
    ingest_module._run_file_ingest(request)

    assert captured["tags"] == ["charge-updates", "prd", "product-docs"]


def test_load_memory_session_returns_memory_and_items(monkeypatch):
    class _FakeMemory:
        def get_all(self, **_kwargs):
            return {
                "results": [
                    {
                        "id": "keep",
                        "memory": "decision body",
                        "metadata": {
                            "repo": "customcheckout",
                            "category": "decision",
                            "source_path": "/repo/customcheckout/flow.py",
                            "tags": ["critical"],
                        },
                    }
                ]
            }

    class _FakeMemManager:
        def get_memory(self, _project_id):
            return _FakeMemory()

    monkeypatch.setattr(ingest_module, "_get_mem_manager", lambda: _FakeMemManager())
    memory, items = ingest_module._load_memory_session("automatic-discounts")

    assert memory is not None
    assert len(items) == 1
    assert hasattr(items[0], "metadata")


def test_run_policy_dry_run_and_apply(monkeypatch, caplog):
    monkeypatch.setattr(
        ingest_module,
        "build_policy_actions",
        lambda **_kwargs: {
            "delete_ids": ["d1", "d2"],
            "delete_count": 2,
            "scanned_count": 3,
            "reasons": {"summary_over_limit": 1, "code_doc_stale": 1, "code_doc_duplicate_fingerprint": 0},
        },
    )

    deleted_ids: list[str] = []

    class _FakeMM:
        def get_memory(self, _project_id, **_kw):
            class _Mem:
                def get_all(self, **_kw2):
                    return {"results": [{"id": "x", "memory": "x", "metadata": {}}]}
            return _Mem()

        def delete_memory(self, request):
            deleted_ids.append(request.memory_id)

    monkeypatch.setattr(ingest_module, "_get_mem_manager", lambda: _FakeMM())

    dry_request = ingest_module.PolicyRunRequest(
        project="automatic-discounts",
        mode="dry-run",
        stale_days=45,
        summary_keep=5,
        repo=None,
        path_prefix=None,
    )
    with caplog.at_level(logging.INFO):
        ingest_module._run_policy(dry_request)
    assert "No deletions applied (dry-run)." in caplog.text
    assert "candidate_ids_preview=d1,d2" in caplog.text
    assert deleted_ids == []

    caplog.clear()
    apply_request = ingest_module.PolicyRunRequest(
        project="automatic-discounts",
        mode="apply",
        stale_days=45,
        summary_keep=5,
        repo=None,
        path_prefix=None,
    )
    with caplog.at_level(logging.INFO):
        ingest_module._run_policy(apply_request)
    assert "Applied policy deletions: 2" in caplog.text
    assert deleted_ids == ["d1", "d2"]


def test_run_clear_memories_cancel_and_confirm(monkeypatch, caplog):
    deleted_ids: list[str] = []

    class _FakeItem:
        def __init__(self, item_id):
            self.id = item_id

    class _FakeMM:
        def list_memories(self, _request):
            return [_FakeItem("a"), _FakeItem("b"), _FakeItem(123)], 3

        def delete_memory(self, request):
            deleted_ids.append(request.memory_id)

    monkeypatch.setattr(ingest_module, "_get_mem_manager", lambda: _FakeMM())

    request = ingest_module.ClearRequest(project="automatic-discounts")

    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    with caplog.at_level(logging.INFO):
        ingest_module._run_clear_memories(request)
    assert "Cancelled" in caplog.text
    assert deleted_ids == []

    caplog.clear()
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    with caplog.at_level(logging.INFO):
        ingest_module._run_clear_memories(request)
    assert "Deleted 2 memories." in caplog.text
    assert deleted_ids == ["a", "b"]


def test_build_parser_registers_commands_and_note_handler():
    parser = ingest_module.build_parser()
    subparsers_action = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    expected = {"repo", "file", "note", "list", "prune", "clear", "project-init", "context-plan", "policy-run"}
    assert expected.issubset(set(subparsers_action.choices.keys()))

    parsed = parser.parse_args(["note", "--project", "automatic-discounts", "--text", "hello world"])
    assert parsed.func is ingest_module.cmd_note


def test_ingest_file_with_no_chunks_only_deletes(monkeypatch, tmp_path: Path):
    path = tmp_path / "empty.py"
    path.write_text("")
    items = [{"id": "stale", "metadata": {"repo": "r", "source_path": str(path.resolve())}}]

    deleted_ids: list[str] = []

    class _FakeMM:
        def delete_memory(self, request):
            deleted_ids.append(request.memory_id)

        def store_memory(self, _request, *, pre_fetched_items=None):
            return 0, []

    monkeypatch.setattr(ingest_module, "_get_mem_manager", lambda: _FakeMM())
    monkeypatch.setattr(ingest_module, "chunk_file", lambda _path, _mode: [])

    deleted, stored = ingest_module.ingest_file(
        items=items, project_id="p", repo="r", path=path, mode="mixed", tags=[],
    )
    assert deleted == 1
    assert stored == 0
    assert deleted_ids == ["stale"]


def test_main_dispatches_and_prints_help(monkeypatch, capsys):
    seen: list[str] = []

    def fake_note_handler(args):
        seen.append(args.project)

    monkeypatch.setitem(ingest_module.COMMAND_HANDLERS, "note", fake_note_handler)
    monkeypatch.setattr(sys, "argv", ["ingest.py", "note", "--project", "automatic-discounts", "--text", "hello"])
    ingest_module.main()
    assert seen == ["automatic-discounts"]

    monkeypatch.setattr(sys, "argv", ["ingest.py"])
    ingest_module.main()
    help_out = capsys.readouterr().out
    assert "usage:" in help_out
