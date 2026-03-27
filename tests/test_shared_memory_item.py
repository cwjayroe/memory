from __future__ import annotations
from memory_core import helpers as helpers_module
from memory_core import memory_types as dataclasses_module

def test_memory_metadata_and_item_from_dict_preserve_known_and_extra_fields():
    item = dataclasses_module.MemoryItem.from_dict(
        {
            "id": "mem-1",
            "memory": "decision memory",
            "metadata": {
                "project_id": "automatic-discounts",
                "repo": "customcheckout",
                "category": "decision",
                "source_kind": "summary",
                "source_path": "/repo/customcheckout/service.py",
                "module": "discounts",
                "updated_at": "2026-03-01T00:00:00+00:00",
                "tags": ["discounts", "critical"],
                "fingerprint": "fp-1",
                "upsert_key": "decision:auto",
                "custom_meta": "keep-me",
            },
            "custom_item": 42,
        }
    )

    assert item.id == "mem-1"
    assert item.memory == "decision memory"
    assert item.metadata.repo == "customcheckout"
    assert item.metadata.tags == ["discounts", "critical"]
    assert item.metadata.extra["custom_meta"] == "keep-me"
    assert item.extra["custom_item"] == 42


def test_memory_item_get_metadata_is_dict_compatible():
    item = dataclasses_module.MemoryItem.from_dict(
        {
            "id": "mem-2",
            "memory": "summary",
            "metadata": {
                "repo": "customcheckout",
                "category": "summary",
                "tags": ["checkout"],
            },
        }
    )

    metadata = item.get("metadata")
    assert isinstance(metadata, dict)
    assert metadata.get("repo") == "customcheckout"
    assert metadata.get("category") == "summary"
    assert metadata.get("tags") == ["checkout"]


def test_get_all_items_returns_memory_item_instances():
    class _Memory:
        def get_all(self, **_kwargs):
            return {
                "results": [
                    {
                        "id": "m-1",
                        "memory": "hello",
                        "metadata": {"repo": "customcheckout"},
                    },
                    "invalid-entry",
                ]
            }

    items = helpers_module.get_all_items(_Memory(), "automatic-discounts", limit=10)

    assert len(items) == 1
    assert isinstance(items[0], helpers_module.MemoryItem)
    assert items[0].id == "m-1"
    assert items[0].metadata.repo == "customcheckout"
