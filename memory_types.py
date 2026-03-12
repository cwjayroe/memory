
import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils import safe_int, optional_str, as_bool, normalize_tags, normalize_strings, normalize_project_ids , normalize_response_format, normalize_excerpt_chars # type: ignore
from constants import DEFAULT_EXCERPT_CHARS 

@dataclass
class MemoryMetadata:
    project_id: str | None = None
    repo: str | None = None
    category: str | None = None
    source_kind: str | None = None
    source_path: str | None = None
    module: str | None = None
    updated_at: str | None = None
    tags: list[str] = field(default_factory=list)
    fingerprint: str | None = None
    upsert_key: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Any) -> "MemoryMetadata":
        raw = value if isinstance(value, dict) else {}
        known_keys = {
            "project_id",
            "repo",
            "category",
            "source_kind",
            "source_path",
            "module",
            "updated_at",
            "tags",
            "fingerprint",
            "upsert_key",
        }
        extra = {key: item for key, item in raw.items() if key not in known_keys}
        return cls(
            project_id=raw.get("project_id") if isinstance(raw.get("project_id"), str) else None,
            repo=raw.get("repo") if isinstance(raw.get("repo"), str) else None,
            category=raw.get("category") if isinstance(raw.get("category"), str) else None,
            source_kind=raw.get("source_kind") if isinstance(raw.get("source_kind"), str) else None,
            source_path=raw.get("source_path") if isinstance(raw.get("source_path"), str) else None,
            module=raw.get("module") if isinstance(raw.get("module"), str) else None,
            updated_at=raw.get("updated_at") if isinstance(raw.get("updated_at"), str) else None,
            tags=normalize_tags(raw.get("tags")),
            fingerprint=raw.get("fingerprint") if isinstance(raw.get("fingerprint"), str) else None,
            upsert_key=raw.get("upsert_key") if isinstance(raw.get("upsert_key"), str) else None,
            extra=extra,
        )

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = dict(self.extra)
        if self.project_id is not None:
            value["project_id"] = self.project_id
        if self.repo is not None:
            value["repo"] = self.repo
        if self.category is not None:
            value["category"] = self.category
        if self.source_kind is not None:
            value["source_kind"] = self.source_kind
        if self.source_path is not None:
            value["source_path"] = self.source_path
        if self.module is not None:
            value["module"] = self.module
        if self.updated_at is not None:
            value["updated_at"] = self.updated_at
        if self.tags:
            value["tags"] = list(self.tags)
        if self.fingerprint is not None:
            value["fingerprint"] = self.fingerprint
        if self.upsert_key is not None:
            value["upsert_key"] = self.upsert_key
        return value

    def get(self, key: str, default: Any = None) -> Any:
        if key == "project_id":
            return self.project_id if self.project_id is not None else default
        if key == "repo":
            return self.repo if self.repo is not None else default
        if key == "category":
            return self.category if self.category is not None else default
        if key == "source_kind":
            return self.source_kind if self.source_kind is not None else default
        if key == "source_path":
            return self.source_path if self.source_path is not None else default
        if key == "module":
            return self.module if self.module is not None else default
        if key == "updated_at":
            return self.updated_at if self.updated_at is not None else default
        if key == "tags":
            return list(self.tags)
        if key == "fingerprint":
            return self.fingerprint if self.fingerprint is not None else default
        if key == "upsert_key":
            return self.upsert_key if self.upsert_key is not None else default
        return self.extra.get(key, default)


@dataclass
class MemoryItem:
    id: str | None
    memory: str
    metadata: MemoryMetadata
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Any) -> "MemoryItem":
        raw = value if isinstance(value, dict) else {}
        known_keys = {"id", "memory", "metadata"}
        extra = {key: item for key, item in raw.items() if key not in known_keys}
        memory_value = raw.get("memory")
        return cls(
            id=raw.get("id") if isinstance(raw.get("id"), str) else None,
            memory=memory_value if isinstance(memory_value, str) else str(memory_value or ""),
            metadata=MemoryMetadata.from_dict(raw.get("metadata")),
            extra=extra,
        )

    def as_dict(self) -> dict[str, Any]:
        value = dict(self.extra)
        value["id"] = self.id
        value["memory"] = self.memory
        value["metadata"] = self.metadata.as_dict()
        return value

    def get(self, key: str, default: Any = None) -> Any:
        if key == "id":
            return self.id if self.id is not None else default
        if key == "memory":
            return self.memory
        if key == "metadata":
            return self.metadata.as_dict()
        return self.extra.get(key, default)


@dataclass(frozen=True)
class SearchContextParsePolicy:
    max_projects_per_query: int
    default_limit: int = 8
    max_limit: int = 20
    default_ranking_mode: str = "hybrid_weighted_rerank"
    allowed_ranking_modes: frozenset[str] = frozenset({"hybrid_weighted_rerank", "hybrid_weighted"})
    default_token_budget: int = 1800
    min_token_budget: int = 600
    max_token_budget: int = 4000
    default_rerank_top_n: int = 40
    max_candidate_pool: int = 200
    candidate_pool_default_multiplier: int = 6
    candidate_pool_default_min: int = 30
    candidate_pool_min: int = 10


@dataclass(frozen=True)
class SearchContextRequest:
    query: str
    project_id: str | None
    project_ids: list[str]
    repo: str | None
    path_prefix: str | None
    tags: list[str]
    categories: list[str]
    limit: int
    ranking_mode: str
    token_budget: int
    candidate_pool: int
    rerank_top_n: int
    debug: bool
    response_format: str
    include_full_text: bool
    excerpt_chars: int

    @classmethod
    def from_arguments(
        cls,
        arguments: dict[str, Any],
        *,
        policy: SearchContextParsePolicy,
    ) -> "SearchContextRequest":
        query = str(arguments["query"]).strip()
        limit = max(1, min(safe_int(arguments.get("limit", policy.default_limit), policy.default_limit), policy.max_limit))
        ranking_mode = str(arguments.get("ranking_mode") or policy.default_ranking_mode).strip() or policy.default_ranking_mode
        if ranking_mode not in policy.allowed_ranking_modes:
            ranking_mode = policy.default_ranking_mode
        token_budget = max(
            policy.min_token_budget,
            min(
                safe_int(arguments.get("token_budget", policy.default_token_budget), policy.default_token_budget),
                policy.max_token_budget,
            ),
        )
        candidate_pool_default = max(limit * policy.candidate_pool_default_multiplier, policy.candidate_pool_default_min)
        candidate_pool_arg = arguments.get("candidate_pool")
        candidate_pool = (
            safe_int(candidate_pool_arg, candidate_pool_default)
            if candidate_pool_arg is not None
            else candidate_pool_default
        )
        candidate_pool = max(policy.candidate_pool_min, min(candidate_pool, policy.max_candidate_pool))
        rerank_top_n = max(
            1,
            min(
                safe_int(arguments.get("rerank_top_n", policy.default_rerank_top_n), policy.default_rerank_top_n),
                policy.max_candidate_pool,
            ),
        )
        return cls(
            query=query,
            project_id=optional_str(arguments.get("project_id")),
            project_ids=normalize_project_ids(arguments.get("project_ids"), max_projects=policy.max_projects_per_query),
            repo=optional_str(arguments.get("repo")),
            path_prefix=optional_str(arguments.get("path_prefix")),
            tags=normalize_tags(arguments.get("tags")),
            categories=normalize_strings(arguments.get("categories")),
            limit=limit,
            ranking_mode=ranking_mode,
            token_budget=token_budget,
            candidate_pool=candidate_pool,
            rerank_top_n=rerank_top_n,
            debug=as_bool(arguments.get("debug", False)),
            response_format=normalize_response_format(arguments.get("response_format")),
            include_full_text=as_bool(arguments.get("include_full_text", False)),
            excerpt_chars=normalize_excerpt_chars(arguments.get("excerpt_chars", DEFAULT_EXCERPT_CHARS)),
        )


@dataclass(frozen=True)
class StoreMemoryRequest:
    project_id: str
    content: str
    repo: str | None
    source_path: str | None
    source_kind: str
    category: str
    module: str | None
    tags: list[str]
    upsert_key: str | None
    fingerprint: str | None

    @classmethod
    def from_arguments(cls, arguments: dict[str, Any], *, default_project_id: str) -> "StoreMemoryRequest":
        source_kind = optional_str(arguments.get("source_kind")) or "summary"
        category = optional_str(arguments.get("category")) or source_kind
        return cls(
            project_id=optional_str(arguments.get("project_id")) or default_project_id,
            content=str(arguments["content"]).strip(),
            repo=optional_str(arguments.get("repo")),
            source_path=optional_str(arguments.get("source_path")),
            source_kind=source_kind,
            category=category,
            module=optional_str(arguments.get("module")),
            tags=normalize_tags(arguments.get("tags")),
            upsert_key=optional_str(arguments.get("upsert_key")),
            fingerprint=optional_str(arguments.get("fingerprint")),
        )


@dataclass(frozen=True)
class ListMemoriesRequest:
    project_id: str
    repo: str | None
    category: str | None
    tag: str | None
    path_prefix: str | None
    offset: int
    limit: int
    response_format: str
    include_full_text: bool
    excerpt_chars: int

    @classmethod
    def from_arguments(
        cls,
        arguments: dict[str, Any],
        *,
        default_project_id: str,
        default_limit: int,
        max_limit: int,
    ) -> "ListMemoriesRequest":
        return cls(
            project_id=optional_str(arguments.get("project_id")) or default_project_id,
            repo=optional_str(arguments.get("repo")),
            category=optional_str(arguments.get("category")),
            tag=optional_str(arguments.get("tag")),
            path_prefix=optional_str(arguments.get("path_prefix")),
            offset=max(0, safe_int(arguments.get("offset", 0), 0)),
            limit=max(1, min(safe_int(arguments.get("limit", default_limit), default_limit), max_limit)),
            response_format=normalize_response_format(arguments.get("response_format")),
            include_full_text=as_bool(arguments.get("include_full_text", False)),
            excerpt_chars=normalize_excerpt_chars(arguments.get("excerpt_chars", DEFAULT_EXCERPT_CHARS)),
        )


@dataclass(frozen=True)
class GetMemoryRequest:
    project_id: str
    memory_id: str
    response_format: str

    @classmethod
    def from_arguments(cls, arguments: dict[str, Any], *, default_project_id: str) -> "GetMemoryRequest":
        return cls(
            project_id=optional_str(arguments.get("project_id")) or default_project_id,
            memory_id=str(arguments.get("memory_id") or "").strip(),
            response_format=normalize_response_format(arguments.get("response_format")),
        )


@dataclass(frozen=True)
class DeleteMemoryRequest:
    project_id: str
    memory_id: str | None
    upsert_key: str | None

    @classmethod
    def from_arguments(cls, arguments: dict[str, Any], *, default_project_id: str) -> "DeleteMemoryRequest":
        return cls(
            project_id=optional_str(arguments.get("project_id")) or default_project_id,
            memory_id=optional_str(arguments.get("memory_id")),
            upsert_key=optional_str(arguments.get("upsert_key")),
        )


@dataclass(frozen=True)
class RepoIngestRequest:
    project: str
    repo: str
    root_override: str | None
    mode: str
    include_override: list[str] | None
    exclude_override: list[str] | None
    tags: list[str]
    manifest_path: Path

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "RepoIngestRequest":
        return cls(
            project=args.project,
            repo=args.repo,
            root_override=args.root,
            mode=args.mode,
            include_override=args.include,
            exclude_override=args.exclude,
            tags=normalize_tags(args.tags),
            manifest_path=Path(args.manifest),
        )


@dataclass(frozen=True)
class FileIngestRequest:
    project: str
    repo: str
    path: Path
    mode: str
    tags: list[str]

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "FileIngestRequest":
        return cls(
            project=args.project,
            repo=args.repo,
            path=Path(args.path).expanduser().resolve(),
            mode=args.mode,
            tags=normalize_tags(args.tags),
        )


@dataclass(frozen=True)
class NoteRequest:
    project: str
    text: str
    repo: str | None
    source_path: str | None
    source_kind: str
    category: str
    tags: list[str]

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "NoteRequest":
        return cls(
            project=args.project,
            text=str(args.text).strip(),
            repo=optional_str(args.repo),
            source_path=optional_str(args.source_path),
            source_kind=str(args.source_kind),
            category=str(args.category),
            tags=normalize_tags(args.tags),
        )


@dataclass(frozen=True)
class IngestListRequest:
    project: str
    repo: str | None
    category: str | None
    tag: str | None
    path_prefix: str | None
    offset: int
    limit: int

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "IngestListRequest":
        return cls(
            project=args.project,
            repo=optional_str(args.repo),
            category=optional_str(args.category),
            tag=optional_str(args.tag),
            path_prefix=optional_str(args.path_prefix),
            offset=max(0, int(args.offset)),
            limit=max(1, int(args.limit)),
        )


@dataclass(frozen=True)
class PruneRequest:
    project: str
    repo: str | None
    path_prefix: str | None
    by: str

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "PruneRequest":
        return cls(
            project=args.project,
            repo=optional_str(args.repo),
            path_prefix=optional_str(args.path_prefix),
            by=args.by,
        )


@dataclass(frozen=True)
class ClearRequest:
    project: str

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "ClearRequest":
        return cls(project=args.project)


@dataclass(frozen=True)
class ProjectInitRequest:
    project: str
    repos: list[str]
    description: str
    tags: list[str]
    set_repo_defaults: bool
    manifest_path: Path

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "ProjectInitRequest":
        return cls(
            project=args.project,
            repos=normalize_strings(args.repos),
            description=str(args.description or ""),
            tags=normalize_tags(args.tags),
            set_repo_defaults=bool(args.set_repo_defaults),
            manifest_path=Path(args.manifest),
        )


@dataclass(frozen=True)
class ContextPlanRequest:
    repo: str
    project: str | None
    pack: str
    manifest_path: Path

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "ContextPlanRequest":
        return cls(
            repo=args.repo,
            project=optional_str(args.project),
            pack=args.pack,
            manifest_path=Path(args.manifest),
        )


@dataclass(frozen=True)
class PolicyRunRequest:
    project: str
    mode: str
    stale_days: int
    summary_keep: int
    repo: str | None
    path_prefix: str | None

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "PolicyRunRequest":
        return cls(
            project=args.project,
            mode=args.mode,
            stale_days=max(0, int(args.stale_days)),
            summary_keep=max(1, int(args.summary_keep)),
            repo=optional_str(args.repo),
            path_prefix=optional_str(args.path_prefix),
        )
