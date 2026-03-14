from __future__ import annotations

import json
from io import BytesIO

import summarizer as summarizer_module


# ---------------------------------------------------------------------------
# _build_summary_prompt
# ---------------------------------------------------------------------------


def test_build_summary_prompt_structure():
    samples = {"decision": ["sample1", "sample2"], "code": ["code_sample"]}
    prompt = summarizer_module._build_summary_prompt("test-project", samples)
    assert "test-project" in prompt
    assert "[DECISION]" in prompt
    assert "[CODE]" in prompt
    assert "sample1" in prompt
    assert "Summary:" in prompt


def test_build_summary_prompt_truncates_excerpts():
    long_excerpt = "x" * 500
    samples = {"decision": [long_excerpt]}
    prompt = summarizer_module._build_summary_prompt("proj", samples)
    assert len(long_excerpt[:300]) == 300
    assert "x" * 300 in prompt
    assert "x" * 301 not in prompt


def test_build_summary_prompt_limits_excerpts_per_category():
    samples = {"decision": [f"excerpt{i}" for i in range(10)]}
    prompt = summarizer_module._build_summary_prompt("proj", samples)
    assert "excerpt0" in prompt
    assert "excerpt2" in prompt
    assert "excerpt3" not in prompt


# ---------------------------------------------------------------------------
# generate_scope_summary
# ---------------------------------------------------------------------------


def test_generate_scope_summary_empty_items():
    result = summarizer_module.generate_scope_summary(project_id="proj", items=[])
    assert "No memories found" in result


def test_generate_scope_summary_filters_by_repo():
    items = [
        {"id": "1", "memory": "relevant content", "metadata": {"repo": "myrepo", "category": "decision"}},
        {"id": "2", "memory": "other content", "metadata": {"repo": "otherrepo", "category": "decision"}},
    ]
    result = summarizer_module.generate_scope_summary(
        project_id="proj", items=items, repo="nonexistent",
    )
    assert "No memories found" in result


def test_generate_scope_summary_filters_by_category():
    items = [
        {"id": "1", "memory": "decision content", "metadata": {"repo": "repo", "category": "decision"}},
        {"id": "2", "memory": "code content", "metadata": {"repo": "repo", "category": "code"}},
    ]
    result = summarizer_module.generate_scope_summary(
        project_id="proj", items=items, category="architecture",
    )
    assert "No memories found" in result


def test_generate_scope_summary_calls_ollama(monkeypatch):
    items = [
        {"id": "1", "memory": "architecture decision body", "metadata": {"category": "decision"}},
    ]

    class _FakeResponse:
        def read(self):
            return json.dumps({"response": "Summary of the scope."}).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass

    captured = {}

    def fake_urlopen(req, timeout=60):
        captured["url"] = req.full_url
        captured["data"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse()

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = summarizer_module.generate_scope_summary(
        project_id="proj",
        items=items,
        ollama_base_url="http://localhost:11434",
        ollama_model="llama3.2",
    )
    assert result == "Summary of the scope."
    assert "localhost:11434" in captured["url"]
    assert captured["data"]["model"] == "llama3.2"


def test_generate_scope_summary_handles_ollama_error(monkeypatch):
    items = [
        {"id": "1", "memory": "some content", "metadata": {"category": "decision"}},
    ]

    import urllib.request
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("offline")),
    )

    result = summarizer_module.generate_scope_summary(project_id="proj", items=items)
    assert "Summary generation failed" in result


def test_generate_scope_summary_empty_llm_response(monkeypatch):
    items = [
        {"id": "1", "memory": "content", "metadata": {"category": "decision"}},
    ]

    class _FakeResponse:
        def read(self):
            return json.dumps({"response": ""}).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_kw: _FakeResponse())

    result = summarizer_module.generate_scope_summary(project_id="proj", items=items)
    assert result == "(empty response from LLM)"
