
import os
from pathlib import Path

from dataclasses import dataclass


@dataclass(frozen=True)
class ServerConfig:
    """Groups all environment-driven server configuration in one place.

    Enterprise additions:
    - Connection pool sizing (pool_max_size, pool_ttl_seconds)
    - Cache backend selection (cache_backend, redis_url)
    - Rate limiting toggle (rate_limit_enabled)
    - Access control toggle (access_control_enabled)
    - Remote Chroma support (chroma_mode, chroma_host, chroma_port)
    - Structured logging (structured_logging)
    """

    max_projects_per_query: int = 10
    manifest_path: str = ""
    inference_max_projects: int = 2
    default_ranking_mode: str = "hybrid_weighted_rerank"
    default_token_budget: int = 1800
    min_token_budget: int = 600
    max_token_budget: int = 4000
    default_rerank_top_n: int = 40
    max_candidate_pool: int = 200
    project_timeout_seconds: float = 8.0
    global_timeout_seconds: float = 20.0
    cache_ttl_seconds: float = 60.0
    cache_max_entries: int = 128
    reranker_model_name: str = "BAAI/bge-reranker-base"

    # --- Enterprise scaling options ---
    pool_max_size: int = 64
    pool_ttl_seconds: float = 3600.0
    cache_backend: str = "memory"
    redis_url: str = "redis://localhost:6379/0"
    redis_key_prefix: str = "pmem:"
    rate_limit_enabled: bool = False
    access_control_enabled: bool = False
    chroma_mode: str = "local"
    chroma_host: str = "localhost"
    chroma_port: int = 8000
    chroma_auth_token: str = ""
    structured_logging: bool = False
    bulk_concurrency: int = 10

    @classmethod
    def from_env(cls) -> "ServerConfig":
        max_projects = int(os.environ.get("PROJECT_MEMORY_MAX_PROJECTS", "10"))
        default_manifest_path = str(Path(__file__).resolve().with_name("projects.yaml"))
        manifest_path = os.path.expanduser(
            os.environ.get("PROJECT_MEMORY_MANIFEST_PATH", default_manifest_path)
        )
        inference_max = max(
            1,
            min(
                int(os.environ.get("PROJECT_MEMORY_INFERENCE_MAX_PROJECTS", "2")),
                max_projects,
            ),
        )
        return cls(
            max_projects_per_query=max_projects,
            manifest_path=manifest_path,
            inference_max_projects=inference_max,
            default_ranking_mode=os.environ.get(
                "PROJECT_MEMORY_RANKING_MODE", "hybrid_weighted_rerank"
            ),
            default_token_budget=int(
                os.environ.get("PROJECT_MEMORY_DEFAULT_TOKEN_BUDGET", "1800")
            ),
            min_token_budget=int(os.environ.get("PROJECT_MEMORY_MIN_TOKEN_BUDGET", "600")),
            max_token_budget=int(os.environ.get("PROJECT_MEMORY_MAX_TOKEN_BUDGET", "4000")),
            default_rerank_top_n=int(
                os.environ.get("PROJECT_MEMORY_DEFAULT_RERANK_TOP_N", "40")
            ),
            max_candidate_pool=int(
                os.environ.get("PROJECT_MEMORY_MAX_CANDIDATE_POOL", "200")
            ),
            project_timeout_seconds=float(
                os.environ.get("PROJECT_MEMORY_PROJECT_SEARCH_TIMEOUT_SECONDS", "8.0")
            ),
            global_timeout_seconds=float(
                os.environ.get("PROJECT_MEMORY_GLOBAL_SEARCH_TIMEOUT_SECONDS", "20.0")
            ),
            cache_ttl_seconds=float(
                os.environ.get("PROJECT_MEMORY_CACHE_TTL_SECONDS", "60")
            ),
            cache_max_entries=int(
                os.environ.get("PROJECT_MEMORY_CACHE_MAX_ENTRIES", "128")
            ),
            reranker_model_name=os.environ.get(
                "PROJECT_MEMORY_RERANKER_MODEL", "BAAI/bge-reranker-base"
            ),
            # Enterprise scaling options
            pool_max_size=int(os.environ.get("PROJECT_MEMORY_POOL_MAX_SIZE", "64")),
            pool_ttl_seconds=float(
                os.environ.get("PROJECT_MEMORY_POOL_TTL_SECONDS", "3600")
            ),
            cache_backend=os.environ.get("PROJECT_MEMORY_CACHE_BACKEND", "memory"),
            redis_url=os.environ.get(
                "PROJECT_MEMORY_REDIS_URL", "redis://localhost:6379/0"
            ),
            redis_key_prefix=os.environ.get("PROJECT_MEMORY_REDIS_KEY_PREFIX", "pmem:"),
            rate_limit_enabled=os.environ.get(
                "PROJECT_MEMORY_RATE_LIMIT_ENABLED", ""
            ).lower() in ("1", "true", "yes"),
            access_control_enabled=os.environ.get(
                "PROJECT_MEMORY_ACCESS_CONTROL_ENABLED", ""
            ).lower() in ("1", "true", "yes"),
            chroma_mode=os.environ.get("PROJECT_MEMORY_CHROMA_MODE", "local"),
            chroma_host=os.environ.get("PROJECT_MEMORY_CHROMA_HOST", "localhost"),
            chroma_port=int(os.environ.get("PROJECT_MEMORY_CHROMA_PORT", "8000")),
            chroma_auth_token=os.environ.get("PROJECT_MEMORY_CHROMA_AUTH_TOKEN", ""),
            structured_logging=os.environ.get(
                "PROJECT_MEMORY_STRUCTURED_LOGGING", ""
            ).lower() in ("1", "true", "yes"),
            bulk_concurrency=int(
                os.environ.get("PROJECT_MEMORY_BULK_CONCURRENCY", "10")
            ),
        )
