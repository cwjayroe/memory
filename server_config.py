
import os
from pathlib import Path

from dataclasses import dataclass


@dataclass(frozen=True)
class ServerConfig:
    """Groups all environment-driven server configuration in one place."""

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
        )

