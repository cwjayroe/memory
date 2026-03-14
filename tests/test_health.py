from __future__ import annotations

import json
from io import BytesIO

import health as health_module


# ---------------------------------------------------------------------------
# _check_ollama
# ---------------------------------------------------------------------------


def test_check_ollama_ok(monkeypatch):
    class _FakeResp:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_kw: _FakeResp())

    result = health_module._check_ollama("http://localhost:11434", "llama3.2")
    assert result["status"] == "ok"
    assert "latency_ms" in result


def test_check_ollama_non_200(monkeypatch):
    class _FakeResp:
        status = 500
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_kw: _FakeResp())

    result = health_module._check_ollama("http://localhost:11434", "llama3.2")
    assert result["status"] == "degraded"


def test_check_ollama_connection_error(monkeypatch):
    import urllib.request
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda *_a, **_kw: (_ for _ in ()).throw(ConnectionError("refused")),
    )

    result = health_module._check_ollama("http://localhost:11434", "llama3.2")
    assert result["status"] == "error"
    assert "refused" in result["detail"]


# ---------------------------------------------------------------------------
# _check_chroma
# ---------------------------------------------------------------------------


def test_check_chroma_ok(monkeypatch):
    class _FakeClient:
        def __init__(self, **_kw):
            pass
        def list_collections(self):
            return []

    monkeypatch.setattr(health_module, "chromadb", type("mod", (), {"PersistentClient": _FakeClient}), raising=False)
    import sys
    fake_chromadb = type(sys)("chromadb")
    fake_chromadb.PersistentClient = _FakeClient
    monkeypatch.setitem(sys.modules, "chromadb", fake_chromadb)

    result = health_module._check_chroma("test-project")
    assert result["status"] == "ok"


def test_check_chroma_error(monkeypatch):
    import sys
    fake_chromadb = type(sys)("chromadb")

    class _BrokenClient:
        def __init__(self, **_kw):
            raise RuntimeError("chroma unavailable")

    fake_chromadb.PersistentClient = _BrokenClient
    monkeypatch.setitem(sys.modules, "chromadb", fake_chromadb)

    result = health_module._check_chroma("test-project")
    assert result["status"] == "error"
    assert "chroma unavailable" in result["detail"]


# ---------------------------------------------------------------------------
# _check_embedding_model
# ---------------------------------------------------------------------------


def test_check_embedding_model_ok(monkeypatch):
    import sys

    class _FakeModel:
        def __init__(self, _name):
            pass
        def encode(self, _texts):
            return [[0.1, 0.2]]

    fake_st = type(sys)("sentence_transformers")
    fake_st.SentenceTransformer = _FakeModel
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_st)

    result = health_module._check_embedding_model()
    assert result["status"] == "ok"


def test_check_embedding_model_error(monkeypatch):
    import sys
    fake_st = type(sys)("sentence_transformers")

    class _BrokenModel:
        def __init__(self, _name):
            raise RuntimeError("model not found")

    fake_st.SentenceTransformer = _BrokenModel
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_st)

    result = health_module._check_embedding_model()
    assert result["status"] == "error"


# ---------------------------------------------------------------------------
# _check_reranker
# ---------------------------------------------------------------------------


def test_check_reranker_ok(monkeypatch):
    import sys

    class _FakeEncoder:
        def __init__(self, _name):
            pass
        def predict(self, _pairs):
            return [0.9]

    fake_st = type(sys)("sentence_transformers")
    fake_st.CrossEncoder = _FakeEncoder
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_st)

    result = health_module._check_reranker("BAAI/bge-reranker-base")
    assert result["status"] == "ok"


def test_check_reranker_error(monkeypatch):
    import sys
    fake_st = type(sys)("sentence_transformers")

    class _BrokenEncoder:
        def __init__(self, _name):
            raise RuntimeError("reranker failed")

    fake_st.CrossEncoder = _BrokenEncoder
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_st)

    result = health_module._check_reranker("BAAI/bge-reranker-base")
    assert result["status"] == "error"


# ---------------------------------------------------------------------------
# run_health_check
# ---------------------------------------------------------------------------


def test_run_health_check_all_ok(monkeypatch):
    monkeypatch.setattr(health_module, "_check_ollama", lambda *_a: {"status": "ok"})
    monkeypatch.setattr(health_module, "_check_chroma", lambda *_a: {"status": "ok"})
    monkeypatch.setattr(health_module, "_check_embedding_model", lambda: {"status": "ok"})
    monkeypatch.setattr(health_module, "_check_reranker", lambda *_a: {"status": "ok"})

    result = health_module.run_health_check(
        ollama_base_url="http://localhost:11434",
        ollama_model="llama3.2",
        reranker_model="BAAI/bge-reranker-base",
        default_project_id="test-project",
    )
    assert result["overall"] == "ok"
    assert len(result["components"]) == 4


def test_run_health_check_degraded(monkeypatch):
    monkeypatch.setattr(health_module, "_check_ollama", lambda *_a: {"status": "ok"})
    monkeypatch.setattr(health_module, "_check_chroma", lambda *_a: {"status": "error", "detail": "down"})
    monkeypatch.setattr(health_module, "_check_embedding_model", lambda: {"status": "ok"})
    monkeypatch.setattr(health_module, "_check_reranker", lambda *_a: {"status": "ok"})

    result = health_module.run_health_check(
        ollama_base_url="http://localhost:11434",
        ollama_model="llama3.2",
        reranker_model="BAAI/bge-reranker-base",
        default_project_id="test-project",
    )
    assert result["overall"] == "degraded"


def test_run_health_check_skip_slow(monkeypatch):
    monkeypatch.setattr(health_module, "_check_ollama", lambda *_a: {"status": "ok"})
    monkeypatch.setattr(health_module, "_check_chroma", lambda *_a: {"status": "ok"})

    result = health_module.run_health_check(
        ollama_base_url="http://localhost:11434",
        ollama_model="llama3.2",
        reranker_model="BAAI/bge-reranker-base",
        default_project_id="test-project",
        skip_slow=True,
    )
    assert result["overall"] == "ok"
    assert result["components"]["embedding_model"]["status"] == "skipped"
    assert result["components"]["reranker"]["status"] == "skipped"
