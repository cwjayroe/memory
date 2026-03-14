from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

LOGGER = logging.getLogger(__name__)

PASCAL_EXCLUDE = frozenset(
    {
        "TypeError", "ValueError", "KeyError", "IndexError", "AttributeError",
        "RuntimeError", "OSError", "IOError", "StopIteration", "GeneratorExit",
        "None", "True", "False", "Exception", "BaseException", "object",
        "str", "int", "float", "bool", "list", "dict", "tuple", "set",
        "bytes", "bytearray", "frozenset", "type", "object",
    }
)

KNOWN_PATTERNS = [
    "circuit breaker", "rate limit", "retry", "dead letter", "saga pattern",
    "event sourcing", "cqrs", "pub/sub", "webhook", "middleware",
    "cache invalidation", "blue-green", "canary deploy", "feature flag",
    "idempotent",
]

STOP_WORDS = frozenset(
    {
        "the", "and", "for", "are", "but", "not", "you", "all", "can",
        "had", "her", "was", "one", "our", "out", "day", "get", "has",
        "him", "his", "how", "man", "new", "now", "old", "see", "way",
        "who", "boy", "did", "its", "let", "put", "say", "she", "too",
        "use", "api", "url", "http", "https", "get", "post", "put",
    }
)

PYTHON_BUILTINS = frozenset(
    {
        "abs", "all", "any", "ascii", "bin", "bool", "breakpoint", "bytearray",
        "bytes", "callable", "chr", "classmethod", "compile", "complex",
        "delattr", "dict", "dir", "divmod", "enumerate", "eval", "exec",
        "filter", "float", "format", "frozenset", "getattr", "globals",
        "hasattr", "hash", "help", "hex", "id", "input", "int", "isinstance",
        "issubclass", "iter", "len", "list", "locals", "map", "max", "memoryview",
        "min", "next", "object", "oct", "open", "ord", "pow", "print",
        "property", "range", "repr", "reversed", "round", "set", "setattr",
        "slice", "sorted", "staticmethod", "str", "sum", "super", "tuple",
        "type", "vars", "zip", "__import__",
    }
)

MAX_ENTITIES = 30


@dataclass
class Entity:
    name: str
    kind: str
    confidence: float


class EntityExtractor:
    def __init__(self, tag_vocab: list[str] | None = None) -> None:
        self._tag_vocab = (tag_vocab or [])

    def extract(
        self,
        text: str,
        source_metadata: dict | None = None,
    ) -> list[Entity]:
        entities: list[Entity] = []

        pascal = re.findall(
            r"[A-Z][a-z]+(?:[A-Z][a-z]+)+",
            text,
        )
        for m in pascal:
            if m not in PASCAL_EXCLUDE:
                entities.append(Entity(name=m, kind="service", confidence=0.7))

        snake = re.findall(
            r"[a-z][a-z0-9]*(?:_[a-z0-9]+){1,}",
            text,
        )
        for m in snake:
            if len(m) >= 5:
                entities.append(Entity(name=m, kind="module", confidence=0.6))

        file_paths = re.findall(
            r"(?:\.{0,2}/)?(?:[a-zA-Z0-9_.-]+/)+[a-zA-Z0-9_.-]+\.[a-z]{1,5}",
            text,
        )
        for m in file_paths:
            entities.append(Entity(name=m, kind="file", confidence=0.8))

        api_method = re.findall(
            r"(?:GET|POST|PUT|DELETE|PATCH)\s+/[a-zA-Z0-9/_-]+",
            text,
        )
        for m in api_method:
            entities.append(Entity(name=m.strip(), kind="api", confidence=0.75))

        api_path = re.findall(
            r"/[a-z][a-z0-9/_-]{3,}",
            text,
        )
        method_paths = {
            p.split(None, 1)[1] for p in api_method
            if len(p.split(None, 1)) >= 2
        }
        for m in api_path:
            if m not in method_paths:
                entities.append(Entity(name=m, kind="api", confidence=0.75))

        text_lower = text.lower()
        for pat in KNOWN_PATTERNS:
            if pat in text_lower:
                entities.append(Entity(name=pat, kind="pattern", confidence=0.85))

        for tag in self._tag_vocab:
            if tag and tag in text:
                entities.append(Entity(name=tag, kind="concept", confidence=0.9))

        pkg = re.findall(
            r"\b([a-z][a-z0-9]{2,}(?:-[a-z0-9]{3,})+)\b",
            text,
        )
        for m in pkg:
            entities.append(Entity(name=m, kind="tool", confidence=0.5))

        return self._postprocess(entities)

    def _postprocess(self, entities: list[Entity]) -> list[Entity]:
        seen: dict[tuple[str, str], float] = {}
        for e in entities:
            norm = e.name.lower().strip()
            if len(norm) < 3:
                continue
            if norm in STOP_WORDS or norm in PYTHON_BUILTINS:
                continue
            key = (norm, e.kind)
            if key not in seen or e.confidence > seen[key]:
                seen[key] = e.confidence

        result = [
            Entity(name=norm, kind=kind, confidence=conf)
            for (norm, kind), conf in seen.items()
        ]
        result.sort(key=lambda x: -x.confidence)
        return result[:MAX_ENTITIES]

    def extract_with_ollama(
        self,
        text: str,
        ollama_base_url: str,
        model: str,
    ) -> list[Entity]:
        rule_entities = self.extract(text)
        try:
            url = f"{ollama_base_url.rstrip('/')}/api/generate"
            prompt = (
                "Extract software entities from this text. "
                "Return a JSON array of objects with keys: name, kind, confidence. "
                "Kinds: service, api, module, pattern, concept, tool, file. "
                "Confidence 0.0-1.0. Text:\n\n" + text[:4000]
            )
            body = json.dumps(
                {"model": model, "prompt": prompt, "stream": False}
            ).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
            obj = json.loads(raw)
            full_response = obj.get("response", "")
            llm_entities = self._parse_ollama_json(full_response)
            for e in llm_entities:
                e.confidence = min(e.confidence * 0.95, 1.0)
            rule_by_key = {
                (e.name.lower().strip(), e.kind): e
                for e in rule_entities
            }
            for e in llm_entities:
                key = (e.name.lower().strip(), e.kind)
                if key not in rule_by_key or e.confidence > rule_by_key[key].confidence:
                    rule_by_key[key] = e
            merged = list(rule_by_key.values())
            merged.sort(key=lambda x: -x.confidence)
            return merged[:MAX_ENTITIES]
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, ValueError) as exc:
            LOGGER.debug("Ollama extraction failed: %s", exc)
            return rule_entities

    def _parse_ollama_json(self, raw: str) -> list[Entity]:
        entities: list[Entity] = []
        try:
            start = raw.find("[")
            if start >= 0:
                depth = 0
                end = start
                for i, c in enumerate(raw[start:], start):
                    if c == "[":
                        depth += 1
                    elif c == "]":
                        depth -= 1
                        if depth == 0:
                            end = i
                            break
                chunk = raw[start : end + 1]
                arr = json.loads(chunk)
                for item in arr:
                    if isinstance(item, dict):
                        name = item.get("name", "")
                        kind = item.get("kind") or "concept"
                        conf = float(item.get("confidence", 0.8))
                        if name:
                            entities.append(Entity(name=str(name), kind=str(kind), confidence=conf))
        except (json.JSONDecodeError, TypeError, KeyError):
            pass
        return entities


def extract_and_link(
    text: str,
    memory_id: str,
    store: Any,
    project_id: str,
    tag_vocab: list[str] | None = None,
) -> int:
    extractor = EntityExtractor(tag_vocab=tag_vocab)
    entities = extractor.extract(text)
    count = 0
    for e in entities:
        entity_id = store.upsert_entity(e.name, e.kind, project_id)
        store.link_memory_entity(memory_id, entity_id, e.confidence)
        count += 1
    return count
