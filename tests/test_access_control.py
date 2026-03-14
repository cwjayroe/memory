"""Tests for the access_control module."""

import json
import os
import pytest
from access_control import AccessController, TenantPolicy


class TestTenantPolicy:
    def test_empty_allow_list_allows_all(self):
        policy = TenantPolicy(tenant_id="t1")
        assert policy.can_access("any-project") is True

    def test_allow_list_pattern_matching(self):
        policy = TenantPolicy(
            tenant_id="t1",
            allowed_projects=["billing-*", "payments"],
        )
        assert policy.can_access("billing-prod") is True
        assert policy.can_access("billing-staging") is True
        assert policy.can_access("payments") is True
        assert policy.can_access("auth-service") is False

    def test_deny_list_takes_precedence(self):
        policy = TenantPolicy(
            tenant_id="t1",
            allowed_projects=["*"],
            denied_projects=["secret-*"],
        )
        assert policy.can_access("public-data") is True
        assert policy.can_access("secret-keys") is False

    def test_read_only_blocks_writes(self):
        policy = TenantPolicy(
            tenant_id="t1",
            read_only=True,
        )
        assert policy.can_access("any") is True
        assert policy.can_write("any") is False


class TestAccessController:
    def test_disabled_allows_everything(self):
        ac = AccessController(enabled=False)
        allowed, reason = ac.check_access("unknown", "any-project")
        assert allowed is True

    def test_no_policies_means_disabled(self):
        ac = AccessController(enabled=True)
        # No policies registered, so .enabled returns False
        assert ac.enabled is False
        allowed, _ = ac.check_access("anyone", "any")
        assert allowed is True

    def test_registered_policy_allows(self):
        ac = AccessController(enabled=True)
        ac.register_policy(TenantPolicy(
            tenant_id="team-a",
            allowed_projects=["billing-*"],
        ))
        allowed, _ = ac.check_access("team-a", "billing-prod")
        assert allowed is True

    def test_registered_policy_denies(self):
        ac = AccessController(enabled=True)
        ac.register_policy(TenantPolicy(
            tenant_id="team-a",
            allowed_projects=["billing-*"],
        ))
        allowed, reason = ac.check_access("team-a", "auth-service")
        assert allowed is False
        assert "project_denied" in reason

    def test_unknown_tenant_denied(self):
        ac = AccessController(enabled=True)
        ac.register_policy(TenantPolicy(tenant_id="team-a"))
        allowed, reason = ac.check_access("unknown-team", "any")
        assert allowed is False
        assert "unknown_tenant" in reason

    def test_superuser_always_allowed(self):
        ac = AccessController(enabled=True)
        ac.register_policy(TenantPolicy(
            tenant_id="team-a",
            allowed_projects=["billing-*"],
        ))
        allowed, _ = ac.check_access(AccessController.SUPERUSER_TENANT, "anything")
        assert allowed is True

    def test_write_check_respects_read_only(self):
        ac = AccessController(enabled=True)
        ac.register_policy(TenantPolicy(
            tenant_id="reader",
            read_only=True,
        ))
        allowed, _ = ac.check_access("reader", "any")
        assert allowed is True
        allowed, reason = ac.check_write("reader", "any")
        assert allowed is False
        assert reason == "read_only_tenant"

    def test_resolve_tenant(self):
        ac = AccessController()
        assert ac.resolve_tenant({"tenant_id": "custom"}) == "custom"
        assert ac.resolve_tenant({}) == "default"

    def test_remove_policy(self):
        ac = AccessController(enabled=True)
        ac.register_policy(TenantPolicy(tenant_id="team-a"))
        ac.remove_policy("team-a")
        assert ac.get_policy("team-a") is None

    def test_violations_counter(self):
        ac = AccessController(enabled=True)
        ac.register_policy(TenantPolicy(
            tenant_id="team-a",
            allowed_projects=["x"],
        ))
        ac.check_access("team-a", "forbidden")
        ac.check_access("team-a", "forbidden")
        assert ac.violations == 2

    def test_stats(self):
        ac = AccessController(enabled=True)
        ac.register_policy(TenantPolicy(tenant_id="t1"))
        stats = ac.stats()
        assert stats["tenant_count"] == 1
        assert "t1" in stats["tenants"]


class TestLoadFromEnv:
    def test_load_from_env(self, monkeypatch):
        policies = {
            "team-a": {
                "allowed_projects": ["billing-*"],
                "read_only": False,
            },
            "team-b": {
                "allowed_projects": ["auth-*"],
                "read_only": True,
            },
        }
        monkeypatch.setenv("TENANT_POLICIES", json.dumps(policies))
        ac = AccessController(enabled=True)
        count = ac.load_from_env()
        assert count == 2

        p = ac.get_policy("team-a")
        assert p is not None
        assert p.allowed_projects == ["billing-*"]

    def test_load_from_env_empty(self, monkeypatch):
        monkeypatch.delenv("TENANT_POLICIES", raising=False)
        ac = AccessController()
        assert ac.load_from_env() == 0

    def test_load_from_env_invalid_json(self, monkeypatch):
        monkeypatch.setenv("TENANT_POLICIES", "not-json")
        ac = AccessController()
        assert ac.load_from_env() == 0


class TestLoadFromManifest:
    def test_load_from_manifest(self):
        manifest = {
            "tenant_policies": {
                "team-x": {
                    "allowed_projects": ["*"],
                    "denied_projects": ["secret-*"],
                },
            },
        }
        ac = AccessController(enabled=True)
        count = ac.load_from_manifest(manifest)
        assert count == 1
        p = ac.get_policy("team-x")
        assert p.denied_projects == ["secret-*"]

    def test_load_from_manifest_no_section(self):
        ac = AccessController()
        assert ac.load_from_manifest({}) == 0
