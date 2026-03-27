from __future__ import annotations

import json
import logging
import re
import uuid
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

LOGGER = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class UnionFind:
    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        if x not in self._parent:
            self._parent[x] = x
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, x: str, y: str) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self._parent[rx] = ry

    def groups(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for key in self._parent:
            root = self.find(key)
            result.setdefault(root, []).append(key)
        return result


@dataclass
class MemoryCluster:
    cluster_id: str
    memory_ids: list[str]
    shared_entities: list[str]
    category: str | None
    size: int


@dataclass
class ConsolidationAction:
    cluster_id: str
    memory_ids: list[str]
    shared_entities: list[str]
    action: str
    summary_preview: str | None = None
    new_memory_id: str | None = None


@dataclass
class DuplicateGroup:
    memory_ids: list[str]
    similarity: float
    repo: str | None
    category: str | None


def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"\b[a-zA-Z0-9]+\b", text.lower())
    return set(w for w in words if len(w) > 1)


class ConsolidationEngine:
    def __init__(
        self,
        store: Any,
        memory_manager: Any | None = None,
        ollama_base_url: str = "http://localhost:11434",
        ollama_model: str = "llama3.2",
    ) -> None:
        self._store = store
        self._memory_manager = memory_manager
        self._ollama_base_url = ollama_base_url.rstrip("/")
        self._ollama_model = ollama_model

    def find_clusters(
        self,
        project_id: str,
        min_cluster_size: int = 3,
        category: str | None = None,
        entity: str | None = None,
    ) -> list[MemoryCluster]:
        if entity is not None:
            memory_ids = self._store.find_memories_by_entity(entity)
            items: list[dict[str, Any]] = []
            for mid in memory_ids:
                raw = self._store.get_memory(mid)
                if raw is None:
                    continue
                if category is not None:
                    md = raw.get("metadata") or {}
                    if md.get("category") != category:
                        continue
                items.append(raw)
        else:
            raw_items, _ = self._store.list_memories(
                limit=500,
                category=category,
            )
            items = list(raw_items)

        memory_ids = [it["id"] for it in items if it.get("id")]
        entity_to_memories: dict[str, set[str]] = {}
        memory_to_entities: dict[str, set[str]] = {}

        for mid in memory_ids:
            entities_raw = self._store.get_entities_for_memory(mid)
            entity_keys = {e["name"] for e in entities_raw}
            memory_to_entities[mid] = entity_keys
            for ek in entity_keys:
                entity_to_memories.setdefault(ek, set()).add(mid)

        uf = UnionFind()
        for mid in memory_ids:
            uf.find(mid)

        for i, mid_a in enumerate(memory_ids):
            ents_a = memory_to_entities.get(mid_a, set())
            for mid_b in memory_ids[i + 1 :]:
                ents_b = memory_to_entities.get(mid_b, set())
                if len(ents_a & ents_b) >= 2:
                    uf.union(mid_a, mid_b)

        groups = uf.groups()
        clusters: list[MemoryCluster] = []

        for root, ids in groups.items():
            if len(ids) < min_cluster_size:
                continue
            all_entities: dict[str, int] = {}
            for mid in ids:
                for e in memory_to_entities.get(mid, set()):
                    all_entities[e] = all_entities.get(e, 0) + 1
            shared = [e for e, cnt in all_entities.items() if cnt >= 2]
            cat_counts: dict[str, int] = {}
            for mid in ids:
                raw = next((it for it in items if it.get("id") == mid), None)
                if raw:
                    cat = (raw.get("metadata") or {}).get("category") or ""
                    cat_counts[cat] = cat_counts.get(cat, 0) + 1
            cat = max(cat_counts, key=cat_counts.get) if cat_counts else None
            cluster_id = f"cluster_{abs(hash(tuple(sorted(ids)))) % 10**8}"
            clusters.append(
                MemoryCluster(
                    cluster_id=cluster_id,
                    memory_ids=sorted(ids),
                    shared_entities=sorted(shared),
                    category=cat,
                    size=len(ids),
                )
            )

        clusters.sort(key=lambda c: c.size, reverse=True)
        return clusters

    def synthesize_cluster(
        self,
        cluster: MemoryCluster,
        project_id: str,
    ) -> str | None:
        bodies: list[str] = []
        for mid in cluster.memory_ids:
            raw = self._store.get_memory(mid)
            if raw:
                bodies.append(raw.get("body") or "")
        if not bodies:
            return None

        shared_summary = ", ".join(cluster.shared_entities[:5])
        if not shared_summary:
            shared_summary = "various topics"

        numbered = "\n".join(f"{i+1}. {b}" for i, b in enumerate(bodies))
        prompt = f"""You are a knowledge consolidation assistant. Below are {len(bodies)} related memories about {shared_summary}.

Synthesize them into a single, concise summary that captures all key information, decisions, and relationships. Focus on the most important points and eliminate redundancy.

Memories:
{numbered}

Consolidated summary:
"""

        try:
            payload = json.dumps(
                {
                    "model": self._ollama_model,
                    "prompt": prompt,
                    "stream": False,
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                f"{self._ollama_base_url}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return (data.get("response") or "").strip() or None
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            LOGGER.warning("Ollama synthesis failed: %s", exc)
            return None

    def consolidate(
        self,
        project_id: str,
        category: str | None = None,
        entity: str | None = None,
        dry_run: bool = True,
    ) -> list[ConsolidationAction]:
        clusters = self.find_clusters(
            project_id,
            min_cluster_size=3,
            category=category,
            entity=entity,
        )
        actions: list[ConsolidationAction] = []

        for cluster in clusters:
            if dry_run:
                summary = self.synthesize_cluster(cluster, project_id)
                preview = (summary[:200] + "...") if summary and len(summary) > 200 else summary
                actions.append(
                    ConsolidationAction(
                        cluster_id=cluster.cluster_id,
                        memory_ids=cluster.memory_ids,
                        shared_entities=cluster.shared_entities,
                        action="would_consolidate",
                        summary_preview=preview,
                        new_memory_id=None,
                    )
                )
            else:
                summary = self.synthesize_cluster(cluster, project_id)
                if not summary:
                    continue
                new_id = str(uuid.uuid4())
                metadata: dict[str, Any] = {
                    "project_id": project_id,
                    "category": "summary",
                    "source_kind": "consolidation",
                    "updated_at": _utc_now(),
                    "tags": ["consolidated"],
                }
                self._store.upsert_memory(new_id, summary, metadata)

                for source_id in cluster.memory_ids:
                    self._store.add_relation(new_id, source_id, "supersedes")

                for source_id in cluster.memory_ids:
                    raw = self._store.get_memory(source_id)
                    if raw:
                        md = dict(raw.get("metadata") or {})
                        md["priority"] = "low"
                        md["updated_at"] = _utc_now()
                        self._store.upsert_memory(source_id, raw.get("body") or "", md)

                preview = (summary[:200] + "...") if len(summary) > 200 else summary
                actions.append(
                    ConsolidationAction(
                        cluster_id=cluster.cluster_id,
                        memory_ids=cluster.memory_ids,
                        shared_entities=cluster.shared_entities,
                        action="consolidated",
                        summary_preview=preview,
                        new_memory_id=new_id,
                    )
                )

        return actions

    def detect_near_duplicates(
        self,
        project_id: str,
        threshold: float = 0.92,
        category: str | None = None,
    ) -> list[DuplicateGroup]:
        raw_items, _ = self._store.list_memories(limit=1000, category=category)
        items = [it for it in raw_items if it.get("id") and it.get("body")]

        by_repo_cat: dict[tuple[str | None, str | None], list[dict[str, Any]]] = {}
        for it in items:
            md = it.get("metadata") or {}
            key = (md.get("repo"), md.get("category"))
            by_repo_cat.setdefault(key, []).append(it)

        pairs: list[tuple[str, str, float, str | None, str | None]] = []
        for (repo, cat), group in by_repo_cat.items():
            for i, a in enumerate(group):
                set_a = _tokenize(a.get("body") or "")
                for b in group[i + 1 :]:
                    set_b = _tokenize(b.get("body") or "")
                    sim = _jaccard_similarity(set_a, set_b)
                    if sim > threshold:
                        pairs.append((a["id"], b["id"], sim, repo, cat))

        uf = UnionFind()
        for aid, bid, _, _, _ in pairs:
            uf.find(aid)
            uf.find(bid)
        for aid, bid, _, _, _ in pairs:
            uf.union(aid, bid)

        groups = uf.groups()
        result: list[DuplicateGroup] = []
        id_to_item = {it["id"]: it for it in items}

        for root, ids in groups.items():
            if len(ids) < 2:
                continue
            sims: list[float] = []
            repo_cat: tuple[str | None, str | None] = (None, None)
            for i, aid in enumerate(ids):
                it = id_to_item.get(aid)
                if it:
                    md = it.get("metadata") or {}
                    repo_cat = (md.get("repo"), md.get("category"))
                for bid in ids[i + 1 :]:
                    for pa, pb, s, r, c in pairs:
                        if (pa == aid and pb == bid) or (pa == bid and pb == aid):
                            sims.append(s)
                            if r is not None or c is not None:
                                repo_cat = (r, c)
                            break
            avg_sim = sum(sims) / len(sims) if sims else threshold
            result.append(
                DuplicateGroup(
                    memory_ids=sorted(ids),
                    similarity=avg_sim,
                    repo=repo_cat[0],
                    category=repo_cat[1],
                )
            )

        result.sort(key=lambda g: len(g.memory_ids), reverse=True)
        return result


def run_consolidation(
    store: Any,
    project_id: str,
    category: str | None = None,
    entity: str | None = None,
    dry_run: bool = True,
    ollama_base_url: str = "http://localhost:11434",
    ollama_model: str = "llama3.2",
) -> list[ConsolidationAction]:
    engine = ConsolidationEngine(
        store=store,
        memory_manager=None,
        ollama_base_url=ollama_base_url,
        ollama_model=ollama_model,
    )
    return engine.consolidate(
        project_id=project_id,
        category=category,
        entity=entity,
        dry_run=dry_run,
    )
