from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import mcp_server as mcp_module


def _run_tool(module, name: str, arguments: dict):
    return asyncio.run(module.call_tool(name, arguments))[0].text


# ---------------------------------------------------------------------------
# Minimal stub types for prune/clear tests
# ---------------------------------------------------------------------------


@dataclass
class _FakeMeta:
    fingerprint: str | None = None
    updated_at: str | None = None
    source_path: str | None = None


@dataclass
class _FakeItem:
    id: str | None
    metadata: _FakeMeta = field(default_factory=_FakeMeta)


# ---------------------------------------------------------------------------
# ingest_repo
# ---------------------------------------------------------------------------


def test_ingest_repo_happy_path(monkeypatch, tmp_path):
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "b.py").write_text("y")

    @dataclass
    class _FakeRepoConfig:
        root: Path = tmp_path
        include: list = field(default_factory=list)
        exclude: list = field(default_factory=list)
        default_tags: list = field(default_factory=list)

    monkeypatch.setattr(mcp_module, "read_manifest", lambda _path: {})
    monkeypatch.setattr(mcp_module, "resolve_repo_config", lambda **_kw: _FakeRepoConfig())
    monkeypatch.setattr(mcp_module, "collect_files", lambda _root, _inc, _exc: [tmp_path / "a.py", tmp_path / "b.py"])
    monkeypatch.setattr(mcp_module.mem_manager, "get_all_items", lambda _project: [])
    monkeypatch.setattr(mcp_module, "ingest_file", lambda **_kw: (1, 3))

    text = _run_tool(mcp_module, "ingest_repo", {"project": "my-project", "repo": "customcheckout"})

    assert "files=2" in text
    assert "deleted=2" in text
    assert "stored=6" in text


def test_ingest_repo_root_not_found(monkeypatch):
    @dataclass
    class _FakeRepoConfig:
        root: Path = Path("/nonexistent/path/abc")
        include: list = field(default_factory=list)
        exclude: list = field(default_factory=list)
        default_tags: list = field(default_factory=list)

    monkeypatch.setattr(mcp_module, "read_manifest", lambda _path: {})
    monkeypatch.setattr(mcp_module, "resolve_repo_config", lambda **_kw: _FakeRepoConfig())

    text = _run_tool(mcp_module, "ingest_repo", {"project": "my-project", "repo": "customcheckout"})

    assert "does not exist" in text


# ---------------------------------------------------------------------------
# ingest_file
# ---------------------------------------------------------------------------


def test_ingest_file_happy_path(monkeypatch, tmp_path):
    path = tmp_path / "service.py"
    path.write_text("pass")

    @dataclass
    class _FakeRepoConfig:
        default_tags: list = field(default_factory=lambda: ["customcheckout", "checkout"])

    monkeypatch.setattr(mcp_module, "read_manifest", lambda _path: {})
    monkeypatch.setattr(mcp_module, "resolve_repo_config", lambda **_kw: _FakeRepoConfig())
    monkeypatch.setattr(mcp_module.mem_manager, "get_all_items", lambda _project: [])
    monkeypatch.setattr(mcp_module, "ingest_file", lambda **_kw: (0, 2))

    text = _run_tool(mcp_module, "ingest_file", {"project": "my-project", "repo": "customcheckout", "path": str(path)})

    assert "deleted=0" in text
    assert "stored=2" in text


def test_ingest_file_merges_manifest_default_tags(monkeypatch, tmp_path):
    path = tmp_path / "service.py"
    path.write_text("pass")
    captured: dict[str, object] = {}

    @dataclass
    class _FakeRepoConfig:
        default_tags: list = field(default_factory=lambda: ["customcheckout", "checkout"])

    monkeypatch.setattr(mcp_module, "read_manifest", lambda _path: {})
    monkeypatch.setattr(mcp_module, "resolve_repo_config", lambda **_kw: _FakeRepoConfig())
    monkeypatch.setattr(mcp_module.mem_manager, "get_all_items", lambda _project: [])

    def _fake_ingest_file(**kwargs):
        captured["tags"] = kwargs["tags"]
        return 0, 1

    monkeypatch.setattr(mcp_module, "ingest_file", _fake_ingest_file)

    _run_tool(
        mcp_module,
        "ingest_file",
        {"project": "my-project", "repo": "customcheckout", "path": str(path), "tags": ["manual"]},
    )

    assert captured["tags"] == ["checkout", "customcheckout", "manual"]


def test_ingest_file_returns_manifest_validation_error(monkeypatch, tmp_path):
    path = tmp_path / "service.py"
    path.write_text("pass")

    monkeypatch.setattr(mcp_module, "read_manifest", lambda _path: {})
    monkeypatch.setattr(
        mcp_module,
        "resolve_repo_config",
        lambda **_kw: (_ for _ in ()).throw(ValueError("repo mismatch")),
    )

    text = _run_tool(
        mcp_module,
        "ingest_file",
        {"project": "my-project", "repo": "customcheckout", "path": str(path)},
    )

    assert text == "repo mismatch"


def test_ingest_file_not_found(monkeypatch, tmp_path):
    missing = tmp_path / "missing.py"

    text = _run_tool(mcp_module, "ingest_file", {"project": "my-project", "repo": "customcheckout", "path": str(missing)})

    assert "does not exist" in text


# ---------------------------------------------------------------------------
# prune_memories
# ---------------------------------------------------------------------------


def test_prune_memories_by_fingerprint(monkeypatch):
    items = [
        _FakeItem("id-1", _FakeMeta(fingerprint="fp1", updated_at="2026-03-03T00:00:00")),
        _FakeItem("id-2", _FakeMeta(fingerprint="fp1", updated_at="2026-03-01T00:00:00")),
        _FakeItem("id-3", _FakeMeta(fingerprint="fp2", updated_at="2026-03-01T00:00:00")),
    ]
    deleted_ids: list[str] = []

    monkeypatch.setattr(mcp_module.mem_manager, "list_memories", lambda _req: (items, len(items)))
    monkeypatch.setattr(mcp_module.mem_manager, "delete_memory", lambda req: deleted_ids.append(req.memory_id))

    text = _run_tool(mcp_module, "prune_memories", {"project": "my-project", "by": "fingerprint"})

    assert deleted_ids == ["id-2"]
    assert "fingerprint=1" in text
    assert "path=0" in text


def test_prune_memories_by_path(monkeypatch, tmp_path):
    existing_file = tmp_path / "exists.py"
    existing_file.write_text("x")

    items = [
        _FakeItem("id-stale", _FakeMeta(source_path="/nonexistent/path/gone.py")),
        _FakeItem("id-keep", _FakeMeta(source_path=str(existing_file))),
    ]
    deleted_ids: list[str] = []

    monkeypatch.setattr(mcp_module.mem_manager, "list_memories", lambda _req: (items, len(items)))
    monkeypatch.setattr(mcp_module.mem_manager, "delete_memory", lambda req: deleted_ids.append(req.memory_id))

    text = _run_tool(mcp_module, "prune_memories", {"project": "my-project", "by": "path"})

    assert deleted_ids == ["id-stale"]
    assert "fingerprint=0" in text
    assert "path=1" in text


def test_prune_memories_both(monkeypatch, tmp_path):
    existing = tmp_path / "real.py"
    existing.write_text("x")
    items = [
        _FakeItem("id-fp-new", _FakeMeta(fingerprint="fp1", updated_at="2026-03-03T00:00:00", source_path=str(existing))),
        _FakeItem("id-fp-old", _FakeMeta(fingerprint="fp1", updated_at="2026-03-01T00:00:00", source_path=str(existing))),
        _FakeItem("id-stale", _FakeMeta(fingerprint="fp2", source_path="/nonexistent/stale.py")),
    ]
    deleted_ids: list[str] = []

    monkeypatch.setattr(mcp_module.mem_manager, "list_memories", lambda _req: (items, len(items)))
    monkeypatch.setattr(mcp_module.mem_manager, "delete_memory", lambda req: deleted_ids.append(req.memory_id))

    text = _run_tool(mcp_module, "prune_memories", {"project": "my-project", "by": "both"})

    assert "id-fp-old" in deleted_ids
    assert "id-stale" in deleted_ids
    assert "total=2" in text


# ---------------------------------------------------------------------------
# init_project
# ---------------------------------------------------------------------------


def test_init_project_creates_new_entry(monkeypatch):
    written: list[dict] = []

    monkeypatch.setattr(mcp_module, "validate_project_id", lambda _p: None)
    monkeypatch.setattr(mcp_module, "read_manifest", lambda _path: {})
    monkeypatch.setattr(mcp_module, "write_manifest", lambda _path, manifest: written.append(manifest))

    text = _run_tool(
        mcp_module,
        "init_project",
        {"project": "my-project", "repos": ["customcheckout"], "description": "test project"},
    )

    assert "Initialized project=my-project" in text
    assert "customcheckout" in text
    assert written
    projects = written[0].get("projects", {})
    assert "my-project" in projects
    assert projects["my-project"]["description"] == "test project"
    assert "customcheckout" in projects["my-project"]["repos"]


def test_init_project_requires_repos(monkeypatch):
    monkeypatch.setattr(mcp_module, "validate_project_id", lambda _p: None)

    text = _run_tool(mcp_module, "init_project", {"project": "my-project", "repos": []})

    assert "at least one" in text


def test_init_project_merges_existing(monkeypatch):
    written: list[dict] = []
    existing_manifest = {
        "projects": {
            "my-project": {
                "description": "old description",
                "repos": ["existing-repo"],
                "tags": ["old-tag"],
            }
        },
        "repos": {},
    }

    monkeypatch.setattr(mcp_module, "validate_project_id", lambda _p: None)
    monkeypatch.setattr(mcp_module, "read_manifest", lambda _path: existing_manifest)
    monkeypatch.setattr(mcp_module, "write_manifest", lambda _path, manifest: written.append(manifest))

    _run_tool(
        mcp_module,
        "init_project",
        {"project": "my-project", "repos": ["new-repo", "existing-repo"], "tags": ["new-tag"]},
    )

    projects = written[0]["projects"]
    assert set(projects["my-project"]["repos"]) == {"existing-repo", "new-repo"}
    # existing-repo already in list → no duplicate
    assert projects["my-project"]["repos"].count("existing-repo") == 1


def test_init_project_sets_repo_defaults_when_requested(monkeypatch):
    written: list[dict] = []
    existing_manifest = {
        "projects": {
            "my-project": {
                "description": "old description",
                "repos": ["existing-repo"],
                "tags": ["old-tag"],
            }
        },
        "repos": {
            "existing-repo": {
                "root": "/tmp/existing",
                "include": ["**/*.py"],
                "exclude": [],
                "default_tags": ["existing-repo"],
                "default_active_project": None,
            }
        },
    }

    monkeypatch.setattr(mcp_module, "validate_project_id", lambda _p: None)
    monkeypatch.setattr(mcp_module, "read_manifest", lambda _path: existing_manifest)
    monkeypatch.setattr(mcp_module, "write_manifest", lambda _path, manifest: written.append(manifest))

    _run_tool(
        mcp_module,
        "init_project",
        {"project": "my-project", "repos": ["existing-repo"], "set_repo_defaults": True},
    )

    assert written[0]["repos"]["existing-repo"]["default_active_project"] == "my-project"


def test_context_plan_tool_returns_json(monkeypatch):
    monkeypatch.setattr(
        mcp_module,
        "build_context_plan",
        lambda **_kwargs: {"repo": "customcheckout", "layers": [{"layer": "layer_1"}]},
    )
    monkeypatch.setattr(mcp_module, "read_manifest", lambda _path: {})

    text = _run_tool(mcp_module, "context_plan", {"repo": "customcheckout"})

    assert '"repo": "customcheckout"' in text
    assert '"layer": "layer_1"' in text


def test_policy_run_dry_run_and_apply(monkeypatch):
    monkeypatch.setattr(
        mcp_module,
        "build_policy_actions",
        lambda **_kwargs: {
            "delete_ids": ["id-1", "id-2"],
            "delete_count": 2,
            "scanned_count": 3,
            "reasons": {"summary_over_limit": 1},
        },
    )
    monkeypatch.setattr(
        mcp_module.mem_manager,
        "get_all_items",
        lambda _project: [],
    )
    deleted_ids: list[str] = []
    monkeypatch.setattr(
        mcp_module.mem_manager,
        "delete_memory",
        lambda req: deleted_ids.append(req.memory_id),
    )

    dry_run = _run_tool(mcp_module, "policy_run", {"project": "my-project", "mode": "dry-run"})
    applied = _run_tool(mcp_module, "policy_run", {"project": "my-project", "mode": "apply"})

    assert "delete_candidates=2" in dry_run
    assert "mode=apply" in applied
    assert deleted_ids == ["id-1", "id-2"]


# ---------------------------------------------------------------------------
# clear_memories
# ---------------------------------------------------------------------------


def test_clear_memories_requires_confirm():
    text = _run_tool(mcp_module, "clear_memories", {"project": "my-project"})

    assert "confirm=true" in text.lower() or "confirm" in text


def test_clear_memories_with_confirm(monkeypatch):
    items = [
        _FakeItem("id-1"),
        _FakeItem("id-2"),
    ]
    deleted_ids: list[str] = []

    monkeypatch.setattr(mcp_module.mem_manager, "list_memories", lambda _req: (items, len(items)))
    monkeypatch.setattr(mcp_module.mem_manager, "delete_memory", lambda req: deleted_ids.append(req.memory_id))

    text = _run_tool(mcp_module, "clear_memories", {"project": "my-project", "confirm": True})

    assert deleted_ids == ["id-1", "id-2"]
    assert "deleted=2" in text
