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


def test_chunk_pdf_document_returns_placeholder_when_no_text(tmp_path: Path, monkeypatch):
    pdf_path = tmp_path / "empty.pdf"
    pdf_path.write_text("placeholder")

    class _FakePage:
        def extract_text(self):
            return ""

    class _FakeReader:
        def __init__(self, _path: str):
            self.pages = [_FakePage()]

    monkeypatch.setattr(chunking_module, "PdfReader", _FakeReader)

    chunks = chunking_module.chunk_pdf_document(pdf_path)

    assert len(chunks) == 1
    assert "(No extractable text found in PDF.)" in chunks[0].content
    assert chunks[0].category == "documentation"


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
    monkeypatch.setattr(ingest_module, "chunk_file", lambda _path, _mode, **_kw: list(chunks))

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
    manifest_path = tmp_path / "projects.yaml"

    class _RepoConfig:
        default_tags = ["product-docs", "prd"]

    def _fake_read_manifest(path_arg):
        captured["manifest_path"] = path_arg
        return {"repos": {}}

    monkeypatch.setattr(ingest_module, "read_manifest", _fake_read_manifest)
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
        manifest_path=manifest_path,
    )
    ingest_module._run_file_ingest(request)

    assert captured["tags"] == ["charge-updates", "prd", "product-docs"]
    assert captured["manifest_path"] == manifest_path


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
    monkeypatch.setattr(ingest_module, "chunk_file", lambda _path, _mode, **_kw: [])

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


def test_sha256_text_deterministic():
    import hashlib
    result = ingest_module.sha256_text("hello world")
    expected = hashlib.sha256("hello world".encode("utf-8")).hexdigest()
    assert result == expected
    # same input → same output
    assert ingest_module.sha256_text("hello world") == result
    # different input → different output
    assert ingest_module.sha256_text("goodbye") != result


def test_memory_metadata_construction():
    item = {
        "id": "some-id",
        "memory": "content",
        "metadata": {
            "project_id": "proj",
            "repo": "myrepo",
            "source_path": "/path/file.py",
            "source_kind": "code",
            "fingerprint": "fp123",
            "updated_at": "2024-01-01T00:00:00Z",
        },
    }
    md = ingest_module.memory_metadata(item)
    assert md["project_id"] == "proj"
    assert md["repo"] == "myrepo"
    assert md["source_path"] == "/path/file.py"
    assert md["source_kind"] == "code"
    assert md["fingerprint"] == "fp123"
    assert "updated_at" in md


def test_chunk_markdown_by_headings_no_headings():
    from pathlib import Path
    path = Path("no-headings.md")
    text = "Just some plain text without any markdown headings"
    chunks = chunking_module.chunk_markdown_by_headings(path, text)
    # With no headings, text should still be chunked (fallback behavior)
    assert len(chunks) >= 1


def test_chunk_text_small_max_chars():
    chunks = chunking_module.chunk_text("abcdefghij", max_chars=4, overlap=1)
    assert len(chunks) >= 1
    combined = "".join(chunks)
    for char in "abcdefghij":
        assert char in combined


def test_run_repo_ingest_happy_path(monkeypatch, tmp_path, caplog):
    # Create a file to ingest
    (tmp_path / "main.py").write_text("print('hello')")

    class _FakeConfig:
        root = tmp_path
        include = ["*.py"]
        exclude = []
        default_tags = ["repo-tag"]
        chunking_by_extension = None

    monkeypatch.setattr(ingest_module, "read_manifest", lambda _path: {})
    monkeypatch.setattr(ingest_module, "resolve_repo_config", lambda **_kw: _FakeConfig())
    monkeypatch.setattr(ingest_module, "_load_memory_session", lambda _proj: (object(), []))

    captured = []

    def fake_ingest_file(**kwargs):
        captured.append(kwargs)
        return 0, 1

    monkeypatch.setattr(ingest_module, "ingest_file", fake_ingest_file)

    request = ingest_module.RepoIngestRequest(
        project="proj", repo="myrepo", root_override=None, mode="mixed",
        include_override=None, exclude_override=None, tags=["extra"],
        manifest_path=tmp_path / "projects.yaml",
    )
    with caplog.at_level(logging.INFO):
        ingest_module._run_repo_ingest(request)

    assert len(captured) == 1
    assert "extra" in captured[0]["tags"]
    assert "repo-tag" in captured[0]["tags"]
    assert "Done." in caplog.text


def test_run_repo_ingest_root_not_found(monkeypatch, tmp_path):
    import pytest

    class _FakeConfig:
        root = tmp_path / "nonexistent"
        include = []
        exclude = []
        default_tags = []
        chunking_by_extension = None

    monkeypatch.setattr(ingest_module, "read_manifest", lambda _path: {})
    monkeypatch.setattr(ingest_module, "resolve_repo_config", lambda **_kw: _FakeConfig())

    request = ingest_module.RepoIngestRequest(
        project="proj", repo="myrepo", root_override=None, mode="mixed",
        include_override=None, exclude_override=None, tags=[],
        manifest_path=tmp_path / "projects.yaml",
    )
    with pytest.raises(FileNotFoundError, match="Repo root does not exist"):
        ingest_module._run_repo_ingest(request)


def test_run_repo_ingest_diff_mode(monkeypatch, tmp_path, capsys):
    (tmp_path / "a.py").write_text("x")

    class _FakeConfig:
        root = tmp_path
        include = ["*.py"]
        exclude = []
        default_tags = []
        chunking_by_extension = None

    monkeypatch.setattr(ingest_module, "read_manifest", lambda _path: {})
    monkeypatch.setattr(ingest_module, "resolve_repo_config", lambda **_kw: _FakeConfig())
    monkeypatch.setattr(ingest_module, "_load_memory_session", lambda _proj: (object(), []))
    monkeypatch.setattr(ingest_module, "ingest_file", lambda **_kw: (1, 2))

    request = ingest_module.RepoIngestRequest(
        project="proj", repo="r", root_override=None, mode="mixed",
        include_override=None, exclude_override=None, tags=[],
        manifest_path=tmp_path / "p.yaml",
    )
    ingest_module._run_repo_ingest(request, diff=True)
    out = capsys.readouterr().out
    assert "-deleted=1" in out
    assert "+stored=2" in out
    assert "Repo diff:" in out


def test_run_note_ingest_happy_path(monkeypatch, caplog):
    captured = []

    class _FakeMM:
        def store_memory(self, request, **_kw):
            captured.append(request)
            return 0, ["note-id"]

    monkeypatch.setattr(ingest_module, "_get_mem_manager", lambda: _FakeMM())

    request = ingest_module.NoteRequest(
        project="proj", text="my note", repo="myrepo",
        source_path="/path/file.py", source_kind="decision", category="decision", tags=["t1"],
    )
    with caplog.at_level(logging.INFO):
        ingest_module._run_note_ingest(request)

    assert len(captured) == 1
    assert captured[0].content == "my note"
    assert "proj" in captured[0].upsert_key
    assert "Stored note memories: 1" in caplog.text


def test_run_note_ingest_empty_text(monkeypatch):
    import pytest
    monkeypatch.setattr(ingest_module, "_get_mem_manager", lambda: object())
    request = ingest_module.NoteRequest(
        project="proj", text="", repo=None, source_path=None,
        source_kind="summary", category="summary", tags=[],
    )
    with pytest.raises(ValueError, match="Note text cannot be empty"):
        ingest_module._run_note_ingest(request)


def test_run_list_memories_with_results(monkeypatch, caplog):
    from memory_types import MemoryItem

    items = [
        MemoryItem.from_dict({
            "id": "m1", "memory": "body1",
            "metadata": {"repo": "r", "category": "decision", "source_kind": "summary", "source_path": "/p", "updated_at": "2026-01-01T00:00:00Z", "tags": ["t1"]},
        }),
    ]

    class _FakeMM:
        def list_memories(self, _request):
            return items, 1

    monkeypatch.setattr(ingest_module, "_get_mem_manager", lambda: _FakeMM())

    request = ingest_module.IngestListRequest(
        project="proj", repo=None, category=None, tag=None,
        path_prefix=None, offset=0, limit=20,
    )
    with caplog.at_level(logging.INFO):
        ingest_module._run_list_memories(request)
    assert "total_matches=1" in caplog.text
    assert "id=m1" in caplog.text


def test_run_list_memories_no_results(monkeypatch, caplog):
    class _FakeMM:
        def list_memories(self, _request):
            return [], 0

    monkeypatch.setattr(ingest_module, "_get_mem_manager", lambda: _FakeMM())

    request = ingest_module.IngestListRequest(
        project="proj", repo=None, category=None, tag=None,
        path_prefix=None, offset=0, limit=20,
    )
    with caplog.at_level(logging.INFO):
        ingest_module._run_list_memories(request)
    assert "No memories found" in caplog.text


def test_run_prune_memories_fingerprint(monkeypatch, caplog):
    from memory_types import MemoryItem

    items = [
        MemoryItem.from_dict({"id": "newer", "memory": "a", "metadata": {"fingerprint": "fp1", "updated_at": "2026-03-01T00:00:00Z"}}),
        MemoryItem.from_dict({"id": "older", "memory": "b", "metadata": {"fingerprint": "fp1", "updated_at": "2025-01-01T00:00:00Z"}}),
    ]
    deleted_ids = []

    class _FakeMM:
        def list_memories(self, _request):
            return list(items), 2

        def delete_memory(self, request):
            deleted_ids.append(request.memory_id)

    monkeypatch.setattr(ingest_module, "_get_mem_manager", lambda: _FakeMM())

    request = ingest_module.PruneRequest(project="proj", repo=None, path_prefix=None, by="fingerprint")
    with caplog.at_level(logging.INFO):
        ingest_module._run_prune_memories(request)
    assert "older" in deleted_ids
    assert "newer" not in deleted_ids
    assert "Pruned duplicate fingerprints" in caplog.text


def test_run_prune_memories_path(monkeypatch, caplog):
    from memory_types import MemoryItem

    items = [
        MemoryItem.from_dict({"id": "stale", "memory": "a", "metadata": {"source_path": "/nonexistent/absolute/path.py"}}),
        MemoryItem.from_dict({"id": "relative", "memory": "b", "metadata": {"source_path": "relative/path.py"}}),
    ]
    deleted_ids = []

    class _FakeMM:
        def list_memories(self, _request):
            return list(items), 2

        def delete_memory(self, request):
            deleted_ids.append(request.memory_id)

    monkeypatch.setattr(ingest_module, "_get_mem_manager", lambda: _FakeMM())

    request = ingest_module.PruneRequest(project="proj", repo=None, path_prefix=None, by="path")
    with caplog.at_level(logging.INFO):
        ingest_module._run_prune_memories(request)
    assert "stale" in deleted_ids
    assert "relative" not in deleted_ids
    assert "Pruned stale source paths" in caplog.text


def test_run_context_plan(monkeypatch, caplog, tmp_path):
    monkeypatch.setattr(ingest_module, "read_manifest", lambda _path: {})
    monkeypatch.setattr(ingest_module, "build_context_plan", lambda **_kw: {"layers": [], "active_project": "proj"})

    request = ingest_module.ContextPlanRequest(
        repo="myrepo", project="proj", pack="default_3_layer",
        manifest_path=tmp_path / "projects.yaml",
    )
    with caplog.at_level(logging.INFO):
        ingest_module._run_context_plan(request)
    assert "active_project" in caplog.text
    assert "layers" in caplog.text


def test_summary_topic_key_variants():
    # upsert_key takes priority
    item1 = {"id": "1", "memory": "body", "metadata": {"upsert_key": "my-key", "module": "mod", "source_path": "/p"}}
    assert ingest_module._summary_topic_key(item1) == "my-key"

    # module is next
    item2 = {"id": "2", "memory": "body", "metadata": {"module": "my-module"}}
    assert ingest_module._summary_topic_key(item2) == "my-module"

    # source_path is next
    item3 = {"id": "3", "memory": "body", "metadata": {"source_path": "/src/file.py"}}
    assert ingest_module._summary_topic_key(item3) == "/src/file.py"

    # fallback to hash
    item4 = {"id": "4", "memory": "some body text here"}
    key = ingest_module._summary_topic_key(item4)
    assert key.startswith("summary::")


def test_build_policy_actions_stale_code_doc():
    items = [
        {"id": "old-code", "memory": "old", "metadata": {"category": "code", "repo": "r", "updated_at": "2024-01-01T00:00:00+00:00", "fingerprint": "fp-unique1"}},
        {"id": "recent-code", "memory": "new", "metadata": {"category": "code", "repo": "r", "updated_at": "2026-03-01T00:00:00+00:00", "fingerprint": "fp-unique2"}},
        {"id": "no-date-code", "memory": "no date", "metadata": {"category": "code", "repo": "r", "fingerprint": "fp-unique3"}},
    ]
    policy = ingest_module.build_policy_actions(items=items, stale_days=45, summary_keep=5)
    assert "old-code" in policy["delete_ids"]
    assert "recent-code" not in policy["delete_ids"]
    assert "no-date-code" not in policy["delete_ids"]  # no updated_at -> skipped
    assert policy["reasons"]["code_doc_stale"] >= 1


def test_build_policy_actions_path_prefix_filter():
    items = [
        {"id": "match", "memory": "m", "metadata": {"category": "summary", "repo": "r", "source_path": "/src/app/main.py", "updated_at": "2026-01-01T00:00:00+00:00", "upsert_key": "topic-a"}},
        {"id": "no-match", "memory": "m", "metadata": {"category": "summary", "repo": "r", "source_path": "/other/file.py", "updated_at": "2026-01-01T00:00:00+00:00", "upsert_key": "topic-b"}},
    ]
    policy = ingest_module.build_policy_actions(items=items, stale_days=45, summary_keep=5, path_prefix="/src/app")
    assert policy["scanned_count"] == 1  # only "match" passes the filter


def test_run_policy_verbose_dry_run(monkeypatch, capsys):
    monkeypatch.setattr(
        ingest_module, "build_policy_actions",
        lambda **_kw: {
            "delete_ids": ["d1"],
            "delete_count": 1,
            "scanned_count": 2,
            "reasons": {"summary_over_limit": 1, "code_doc_stale": 0, "code_doc_duplicate_fingerprint": 0},
            "reason_ids": {"summary_over_limit": ["d1"], "code_doc_stale": [], "code_doc_duplicate_fingerprint": []},
        },
    )
    fake_items = [{"id": "d1", "memory": "delete me body text", "metadata": {"category": "summary", "repo": "myrepo", "updated_at": "2026-01-01T00:00:00Z"}}]
    monkeypatch.setattr(ingest_module, "_load_memory_session", lambda _proj: (object(), list(fake_items)))

    request = ingest_module.PolicyRunRequest(
        project="proj", mode="dry-run", stale_days=45, summary_keep=5, repo=None, path_prefix=None,
    )
    ingest_module._run_policy(request, verbose=True)
    out = capsys.readouterr().out
    assert "Dry-run candidates" in out
    assert "d1" in out  # first 8 chars of id
    assert "summary_over_limit" in out


def test_run_export_to_file(monkeypatch, tmp_path, capsys):
    from memory_types import MemoryItem
    items = [MemoryItem.from_dict({"id": "m1", "memory": "body1", "metadata": {"category": "decision"}})]
    class _FakeMM:
        def get_all_items(self, _project):
            return list(items)
    monkeypatch.setattr(ingest_module, "_get_mem_manager", lambda: _FakeMM())

    out_path = tmp_path / "export.ndjson"
    ingest_module._run_export("proj", str(out_path))

    content = out_path.read_text()
    assert "body1" in content
    out = capsys.readouterr().out
    assert "Exported 1 memories" in out


def test_run_export_to_stdout(monkeypatch, capsys):
    from memory_types import MemoryItem
    items = [MemoryItem.from_dict({"id": "m1", "memory": "stdout body", "metadata": {}})]
    class _FakeMM:
        def get_all_items(self, _project):
            return list(items)
    monkeypatch.setattr(ingest_module, "_get_mem_manager", lambda: _FakeMM())

    ingest_module._run_export("proj", None)
    out = capsys.readouterr().out
    assert "stdout body" in out


def test_run_import_happy_path(monkeypatch, tmp_path, capsys):
    import json
    ndjson = tmp_path / "import.ndjson"
    ndjson.write_text(json.dumps({"memory": "imported text", "metadata": {"category": "decision"}}) + "\n")

    stored = []
    class _FakeMM:
        def get_all_items(self, _project):
            return []
        def store_memory(self, request, **_kw):
            stored.append(request.content)
            return 0, ["new-id"]
    monkeypatch.setattr(ingest_module, "_get_mem_manager", lambda: _FakeMM())

    ingest_module._run_import("proj", str(ndjson))
    out = capsys.readouterr().out
    assert "Imported 1 memories" in out
    assert stored == ["imported text"]


def test_run_import_bad_line_and_empty_content(monkeypatch, tmp_path, capsys):
    ndjson = tmp_path / "bad.ndjson"
    ndjson.write_text("not valid json\n{\"memory\": \"\"}\n{\"memory\": \"good\"}\n\n")

    stored = []
    class _FakeMM:
        def get_all_items(self, _project):
            return []
        def store_memory(self, request, **_kw):
            stored.append(request.content)
            return 0, ["id"]
    monkeypatch.setattr(ingest_module, "_get_mem_manager", lambda: _FakeMM())

    ingest_module._run_import("proj", str(ndjson))
    out = capsys.readouterr().out
    assert "Imported 1 memories" in out
    assert "errors=1" in out
    assert stored == ["good"]


def test_run_watch_delegates(monkeypatch, tmp_path):
    import watcher as watcher_module
    captured = {}
    def fake_watch_repo(**kwargs):
        captured.update(kwargs)
    monkeypatch.setattr(watcher_module, "watch_repo", fake_watch_repo)

    ingest_module._run_watch(
        project="proj", repo="myrepo", root=str(tmp_path),
        include=["*.py"], exclude=["*.pyc"], debounce=5.0,
    )
    assert captured["project_id"] == "proj"
    assert captured["repo"] == "myrepo"
    assert captured["include"] == ["*.py"]
    assert captured["debounce_seconds"] == 5.0


def test_run_file_ingest_file_not_found(monkeypatch, tmp_path):
    import pytest
    request = ingest_module.FileIngestRequest(
        project="proj", repo="r", path=tmp_path / "missing.py",
        mode="mixed", tags=[], manifest_path=tmp_path / "p.yaml",
    )
    with pytest.raises(FileNotFoundError, match="File not found"):
        ingest_module._run_file_ingest(request)


def test_run_file_ingest_diff_mode(monkeypatch, tmp_path, capsys):
    path = tmp_path / "file.py"
    path.write_text("x")

    monkeypatch.setattr(ingest_module, "read_manifest", lambda _p: {})
    monkeypatch.setattr(ingest_module, "resolve_repo_config", lambda **_kw: type("C", (), {"default_tags": [], "chunking_by_extension": None})())
    monkeypatch.setattr(ingest_module, "_load_memory_session", lambda _p: (object(), []))
    monkeypatch.setattr(ingest_module, "ingest_file", lambda **_kw: (1, 3))

    request = ingest_module.FileIngestRequest(
        project="proj", repo="r", path=path, mode="mixed", tags=[],
        manifest_path=tmp_path / "p.yaml",
    )
    ingest_module._run_file_ingest(request, diff=True)
    out = capsys.readouterr().out
    assert "File diff" in out
    assert "-deleted=1" in out
    assert "+stored=3" in out


def test_cmd_repo_dispatches(monkeypatch):
    captured = []
    monkeypatch.setattr(ingest_module, "_run_repo_ingest", lambda req, **kw: captured.append(("repo", req)))
    args = argparse.Namespace(project="proj", repo="r", root=None, mode="mixed", include=None, exclude=None, tags="t1", manifest="/tmp/p.yaml", diff=False)
    ingest_module.cmd_repo(args)
    assert len(captured) == 1
    assert captured[0][1].project == "proj"


def test_cmd_file_dispatches(monkeypatch, tmp_path):
    p = tmp_path / "f.py"
    p.write_text("x")
    captured = []
    monkeypatch.setattr(ingest_module, "_run_file_ingest", lambda req, **kw: captured.append(req))
    args = argparse.Namespace(project="proj", repo="r", path=str(p), mode="mixed", tags="t1", manifest="/tmp/p.yaml", diff=False)
    ingest_module.cmd_file(args)
    assert len(captured) == 1


def test_cmd_note_dispatches(monkeypatch):
    captured = []
    monkeypatch.setattr(ingest_module, "_run_note_ingest", lambda req: captured.append(req))
    args = argparse.Namespace(project="proj", text="hello", repo=None, source_path=None, source_kind="summary", category="summary", tags=None)
    ingest_module.cmd_note(args)
    assert len(captured) == 1
    assert captured[0].text == "hello"


def test_cmd_list_dispatches(monkeypatch):
    captured = []
    monkeypatch.setattr(ingest_module, "_run_list_memories", lambda req: captured.append(req))
    args = argparse.Namespace(project="proj", repo=None, category=None, tag=None, path_prefix=None, offset=0, limit=20)
    ingest_module.cmd_list(args)
    assert len(captured) == 1


def test_cmd_prune_dispatches(monkeypatch):
    captured = []
    monkeypatch.setattr(ingest_module, "_run_prune_memories", lambda req: captured.append(req))
    args = argparse.Namespace(project="proj", repo=None, path_prefix=None, by="both")
    ingest_module.cmd_prune(args)
    assert len(captured) == 1


def test_cmd_clear_dispatches(monkeypatch):
    captured = []
    monkeypatch.setattr(ingest_module, "_run_clear_memories", lambda req: captured.append(req))
    args = argparse.Namespace(project="proj")
    ingest_module.cmd_clear(args)
    assert len(captured) == 1


def test_cmd_project_init_dispatches(monkeypatch, tmp_path):
    captured = []
    monkeypatch.setattr(ingest_module, "_run_project_init", lambda req: captured.append(req))
    args = argparse.Namespace(project="proj", repos="r1,r2", description="", tags=None, set_repo_defaults=False, manifest=str(tmp_path / "p.yaml"))
    ingest_module.cmd_project_init(args)
    assert len(captured) == 1


def test_cmd_context_plan_dispatches(monkeypatch, tmp_path):
    captured = []
    monkeypatch.setattr(ingest_module, "_run_context_plan", lambda req: captured.append(req))
    args = argparse.Namespace(repo="r", project="proj", pack="default_3_layer", manifest=str(tmp_path / "p.yaml"))
    ingest_module.cmd_context_plan(args)
    assert len(captured) == 1


def test_cmd_policy_run_dispatches(monkeypatch):
    captured = []
    monkeypatch.setattr(ingest_module, "_run_policy", lambda req, **kw: captured.append((req, kw)))
    args = argparse.Namespace(project="proj", mode="dry-run", stale_days=30, summary_keep=3, repo=None, path_prefix=None, verbose=True)
    ingest_module.cmd_policy_run(args)
    assert len(captured) == 1
    assert captured[0][1].get("verbose") is True


def test_cmd_export_dispatches(monkeypatch):
    captured = []
    monkeypatch.setattr(ingest_module, "_run_export", lambda proj, out: captured.append((proj, out)))
    args = argparse.Namespace(project="proj", output="/tmp/out.json")
    ingest_module.cmd_export(args)
    assert captured == [("proj", "/tmp/out.json")]


def test_cmd_import_dispatches(monkeypatch):
    captured = []
    monkeypatch.setattr(ingest_module, "_run_import", lambda proj, path, upsert=True: captured.append((proj, path)))
    args = argparse.Namespace(project="proj", file="/tmp/in.ndjson", upsert=True)
    ingest_module.cmd_import(args)
    assert captured == [("proj", "/tmp/in.ndjson")]


def test_cmd_watch_dispatches(monkeypatch):
    captured = []
    monkeypatch.setattr(ingest_module, "_run_watch", lambda **kw: captured.append(kw))
    args = argparse.Namespace(project="proj", repo="r", root="/tmp/root", include="*.py", exclude="*.pyc", debounce=2.0)
    ingest_module.cmd_watch(args)
    assert len(captured) == 1
    assert captured[0]["project"] == "proj"
