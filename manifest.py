"""Manifest utilities for project-memory ingestion and retrieval."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from helpers import ( 
    dedupe_keep_order,
    normalize_strings,
    normalize_tags,
    safe_dict,
)
from constants import (
    DEFAULT_PROJECT_ID,
    MEMORY_ROOT,
)
import yaml

DEFAULT_INCLUDE = ["**/*.py", "**/*.md", "**/*.rst", "**/*.txt"]
DEFAULT_EXCLUDE = [
    "**/.git/**",
    "**/.venv/**",
    "**/__pycache__/**",
    "**/.pytest_cache/**",
    "**/node_modules/**",
    "**/migrations/**",
]
DEFAULT_CONTEXT_PACK = {
    "layer_1": {
        "query": "engineering best practices, architecture constraints, coding standards",
        "project_ids_from": "org_practice_projects",
    },
    "layer_2": {
        "query_template": "{active_project} architecture, recent decisions, constraints",
        "project_ids_from": "[active_project] + org_practice_projects",
    },
    "layer_3": {
        "query_template": "{active_project} in repo {repo}, critical files and flow constraints",
        "project_ids_from": "[active_project] + org_practice_projects",
        "repo_filter": True,
        "categories": ["code", "summary", "decision", "architecture", "documentation"],
    },
}

PROJECT_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass
class RepoConfig:
    root: Path
    include: list[str]
    exclude: list[str]
    default_tags: list[str]
    default_active_project: str | None = None


_MANIFEST_INDEX_CACHE_LOCK = threading.Lock()
_MANIFEST_INDEX_CACHE: dict[str, Any] = {
    "path": None,
    "mtime": None,
    "index": None,
}


def guess_repo_root(repo: str) -> str:
    candidate = Path("/Users/willjayroe/Desktop/repos") / repo
    if candidate.exists():
        return str(candidate)
    return "."


def _default_manifest_v2() -> dict[str, Any]:
    return {
        "version": 2,
        "defaults": {
            "ranking_mode": "hybrid_weighted_rerank",
            "token_budget": 1800,
            "limit": 6,
            "org_practice_projects": ["customcheckout-practices"],
        },
        "projects": {},
        "repos": {},
        "context_packs": {"default_3_layer": DEFAULT_CONTEXT_PACK},
    }


def _is_manifest_v2(manifest: dict[str, Any]) -> bool:
    if not isinstance(manifest, dict):
        return False
    if manifest.get("version") == 2:
        return True
    return "repos" in manifest and isinstance(manifest.get("repos"), dict)


def _ensure_manifest_v2(manifest: dict[str, Any]) -> dict[str, Any]:
    if _is_manifest_v2(manifest):
        data = dict(manifest)
        data["version"] = 2
        data.setdefault("defaults", _default_manifest_v2()["defaults"])
        data.setdefault("projects", {})
        data.setdefault("repos", {})
        data.setdefault("context_packs", {"default_3_layer": DEFAULT_CONTEXT_PACK})
        if "default_3_layer" not in safe_dict(data.get("context_packs")):
            data["context_packs"]["default_3_layer"] = DEFAULT_CONTEXT_PACK
        return data

    migrated = _default_manifest_v2()
    old_projects = safe_dict(manifest.get("projects"))
    seen_repo_defaults: set[str] = set()

    for project_id, project_config_raw in old_projects.items():
        project_config = safe_dict(project_config_raw)
        old_repos = safe_dict(project_config.get("repos"))
        repo_names = sorted(old_repos.keys())
        migrated["projects"][project_id] = {
            "description": project_config.get("description", ""),
            "tags": normalize_tags(project_config.get("tags") or [project_id]),
            "repos": repo_names,
        }
        for repo_name, repo_config_raw in old_repos.items():
            repo_config = safe_dict(repo_config_raw)
            if repo_name not in migrated["repos"]:
                migrated["repos"][repo_name] = {
                    "root": repo_config.get("root") or guess_repo_root(repo_name),
                    "include": repo_config.get("include") or list(DEFAULT_INCLUDE),
                    "exclude": repo_config.get("exclude") or list(DEFAULT_EXCLUDE),
                    "default_tags": normalize_tags(repo_config.get("default_tags") or [repo_name]),
                }
            if repo_name not in seen_repo_defaults:
                migrated["repos"][repo_name]["default_active_project"] = project_id
                seen_repo_defaults.add(repo_name)

    if "customcheckout-practices" in migrated["projects"]:
        migrated["defaults"]["org_practice_projects"] = ["customcheckout-practices"]

    return migrated


def read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _default_manifest_v2()

    if yaml is None:
        raise RuntimeError("PyYAML is required to read projects.yaml manifest")

    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Invalid manifest structure in {path}")
    return _ensure_manifest_v2(data)


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    if yaml is None:
        raise RuntimeError("PyYAML is required to write projects.yaml manifest")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")


def validate_project_id(project_id: str) -> None:
    if not PROJECT_ID_PATTERN.match(project_id):
        raise ValueError(
            "Invalid project id. Use lowercase kebab-case (example: checkout-tax, shopify-catalog-sync)."
        )


def resolve_repo_config(
    *,
    manifest: dict[str, Any],
    project_id: str,
    repo: str,
    root_override: str | None,
    include_override: list[str] | None,
    exclude_override: list[str] | None,
) -> RepoConfig:
    data = _ensure_manifest_v2(manifest)
    repos = safe_dict(data.get("repos"))
    repo_config = safe_dict(repos.get(repo))

    project_config = safe_dict(safe_dict(data.get("projects")).get(project_id))
    project_repos = normalize_strings(project_config.get("repos"))
    if project_repos and repo not in project_repos:
        pass

    root = Path(root_override or repo_config.get("root") or ".").expanduser().resolve()
    include = include_override or normalize_strings(repo_config.get("include")) or list(DEFAULT_INCLUDE)
    exclude = exclude_override or normalize_strings(repo_config.get("exclude")) or list(DEFAULT_EXCLUDE)
    default_tags = normalize_tags(repo_config.get("default_tags") or [repo])
    default_active_project = repo_config.get("default_active_project")
    if not isinstance(default_active_project, str):
        default_active_project = None

    return RepoConfig(
        root=root,
        include=list(include),
        exclude=list(exclude),
        default_tags=default_tags,
        default_active_project=default_active_project,
    )


# Backward-compatible alias for legacy callers.
_guess_repo_root = guess_repo_root


def _resolve_active_project(
    manifest: dict[str, Any],
    repo: str,
    explicit_project: str | None,
    *,
    default_project_id: str = DEFAULT_PROJECT_ID,
) -> str:
    if explicit_project:
        return explicit_project
    repo_config = safe_dict(safe_dict(manifest.get("repos")).get(repo))
    default_active_project = repo_config.get("default_active_project")
    if isinstance(default_active_project, str) and default_active_project.strip():
        return default_active_project.strip()
    return default_project_id


def _resolve_project_ids_from_spec(spec: Any, active_project: str, org_practice_projects: list[str]) -> list[str]:
    def expand_token(token: str) -> list[str]:
        clean = token.strip()
        if not clean:
            return []
        if clean == "active_project":
            return [active_project]
        if clean == "org_practice_projects":
            return list(org_practice_projects)
        if clean.startswith("[") and clean.endswith("]"):
            inner = clean[1:-1].strip()
            parts = [p.strip() for p in inner.split(",") if p.strip()]
            expanded: list[str] = []
            for part in parts:
                expanded.extend(expand_token(part))
            return expanded
        return [clean]

    expanded: list[str] = []
    if isinstance(spec, list):
        for entry in spec:
            if isinstance(entry, str):
                expanded.extend(expand_token(entry))
    elif isinstance(spec, str):
        if "+" in spec:
            for part in spec.split("+"):
                expanded.extend(expand_token(part.strip()))
        else:
            expanded.extend(expand_token(spec))
    else:
        expanded.append(active_project)

    return dedupe_keep_order(expanded)


def build_context_plan(
    *,
    manifest: dict[str, Any],
    repo: str,
    explicit_project: str | None,
    pack_name: str = "default_3_layer",
    default_project_id: str = DEFAULT_PROJECT_ID,
) -> dict[str, Any]:
    data = _ensure_manifest_v2(manifest)
    defaults = safe_dict(data.get("defaults"))
    context_packs = safe_dict(data.get("context_packs"))
    pack = safe_dict(context_packs.get(pack_name))
    if not pack:
        raise ValueError(f"Context pack not found: {pack_name}")

    active_project = _resolve_active_project(data, repo, explicit_project, default_project_id=default_project_id)
    org_practice_projects = normalize_strings(defaults.get("org_practice_projects"))
    ranking_mode = str(defaults.get("ranking_mode") or "hybrid_weighted_rerank")
    token_budget = int(defaults.get("token_budget") or 1800)
    default_limit = int(defaults.get("limit") or 6)

    layer_names = sorted(
        [name for name in pack.keys() if name.startswith("layer_")],
        key=lambda name: int(name.split("_")[-1]) if name.split("_")[-1].isdigit() else name,
    )

    layers: list[dict[str, Any]] = []
    for layer_name in layer_names:
        layer_cfg = safe_dict(pack.get(layer_name))
        query = layer_cfg.get("query")
        if not isinstance(query, str) or not query.strip():
            query_template = str(layer_cfg.get("query_template") or "{active_project} context in repo {repo}")
            query = query_template.format(active_project=active_project, repo=repo)

        project_ids = _resolve_project_ids_from_spec(
            layer_cfg.get("project_ids_from"),
            active_project,
            org_practice_projects,
        )

        payload: dict[str, Any] = {
            "query": query,
            "project_ids": project_ids,
            "ranking_mode": ranking_mode,
            "token_budget": token_budget,
            "limit": int(layer_cfg.get("limit") or default_limit),
        }
        if layer_cfg.get("repo_filter"):
            payload["repo"] = repo
        categories = normalize_strings(layer_cfg.get("categories"))
        if categories:
            payload["categories"] = categories

        layers.append({"layer": layer_name, "payload": payload})

    merged_project_ids = dedupe_keep_order(
        [project_id for layer in layers for project_id in layer["payload"].get("project_ids", [])]
    )

    return {
        "repo": repo,
        "active_project": active_project,
        "context_pack": pack_name,
        "org_practice_projects": org_practice_projects,
        "merged_project_ids": merged_project_ids,
        "layers": layers,
    }


def _tokenize_for_inference(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _discover_project_ids_from_memory_root(memory_root: str = MEMORY_ROOT) -> list[str]:
    try:
        root = Path(memory_root).expanduser()
        if not root.exists():
            return []
        return sorted(entry.name for entry in root.iterdir() if entry.is_dir())
    except Exception:
        return []


def build_project_index_from_manifest(manifest_data: dict[str, Any]) -> dict[str, Any]:
    projects_index: dict[str, dict[str, list[str]]] = {}
    projects = safe_dict(manifest_data.get("projects"))
    for project_id, raw_config in projects.items():
        if not isinstance(project_id, str):
            continue
        clean_project_id = project_id.strip()
        if not clean_project_id:
            continue
        config = safe_dict(raw_config)
        projects_index[clean_project_id] = {
            "tags": normalize_tags(config.get("tags")),
            "repos": normalize_strings(config.get("repos")),
        }

    defaults = safe_dict(manifest_data.get("defaults"))
    org_practice_projects = normalize_strings(defaults.get("org_practice_projects"))
    return {
        "projects": projects_index,
        "org_practice_projects": dedupe_keep_order(org_practice_projects),
    }


def load_project_index_with_cache(
    *,
    manifest_path: str,
    default_project_id: str = DEFAULT_PROJECT_ID,
    memory_root: str = MEMORY_ROOT,
) -> dict[str, Any]:
    resolved_path = Path(manifest_path).expanduser()
    try:
        current_mtime = resolved_path.stat().st_mtime if resolved_path.exists() else None
    except OSError:
        current_mtime = None

    with _MANIFEST_INDEX_CACHE_LOCK:
        if (
            _MANIFEST_INDEX_CACHE.get("index") is not None
            and _MANIFEST_INDEX_CACHE.get("path") == str(resolved_path)
            and _MANIFEST_INDEX_CACHE.get("mtime") == current_mtime
        ):
            return dict(_MANIFEST_INDEX_CACHE["index"])

    manifest_data: dict[str, Any] = {}
    if yaml is not None and resolved_path.exists():
        try:
            loaded = yaml.safe_load(resolved_path.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict):
                manifest_data = loaded
        except Exception:
            manifest_data = {}

    index = build_project_index_from_manifest(manifest_data)
    projects = safe_dict(index.get("projects"))
    if not projects:
        for project_id in _discover_project_ids_from_memory_root(memory_root):
            projects[project_id] = {"tags": [], "repos": []}
        index["projects"] = projects

    if default_project_id and default_project_id not in projects:
        projects[default_project_id] = {"tags": [], "repos": []}

    with _MANIFEST_INDEX_CACHE_LOCK:
        _MANIFEST_INDEX_CACHE["path"] = str(resolved_path)
        _MANIFEST_INDEX_CACHE["mtime"] = current_mtime
        _MANIFEST_INDEX_CACHE["index"] = dict(index)

    return index


def resolve_org_practice_projects(index: dict[str, Any], max_projects: int) -> list[str]:
    practices = normalize_strings(index.get("org_practice_projects"))
    return dedupe_keep_order(practices)[:max_projects]


def infer_projects_from_query(
    *,
    query: str,
    repo_hint: str | None,
    max_projects: int,
    index: dict[str, Any],
) -> list[tuple[str, float]]:
    projects = safe_dict(index.get("projects"))
    if not projects:
        return []

    query_lc = query.lower()
    query_tokens = set(_tokenize_for_inference(query))
    scored: list[tuple[str, float]] = []

    for project_id, raw_meta in projects.items():
        if not isinstance(project_id, str) or not project_id.strip():
            continue
        meta = safe_dict(raw_meta)
        score = 0.0

        project_id_lc = project_id.lower()
        if project_id_lc in query_lc:
            score += 3.0

        for token in _tokenize_for_inference(project_id_lc.replace("-", " ")):
            if token in query_tokens:
                score += 1.0

        tags = normalize_tags(meta.get("tags"))
        for tag in tags:
            tag_tokens = set(_tokenize_for_inference(tag))
            if tag_tokens and query_tokens.intersection(tag_tokens):
                score += 1.5

        repos = normalize_strings(meta.get("repos"))
        for repo_name in repos:
            if repo_name and repo_name.lower() in query_lc:
                score += 1.0

        if repo_hint and repo_hint in repos:
            score += 1.2

        if score > 0:
            scored.append((project_id, score))

    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored[: max(1, max_projects)]
