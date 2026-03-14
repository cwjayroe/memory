"""Multi-tenant access control for enterprise memory deployments.

Provides tenant isolation so that different teams, services, or business
units can share a single memory server without cross-contamination.

Access control is enforced at the MCP handler layer:
- Each request carries a ``tenant_id`` (from env, header, or config).
- Tenants are mapped to allowed ``project_id`` patterns via a policy.
- Operations outside the tenant's scope are rejected before hitting storage.

Policies can be loaded from:
- Environment variable (JSON): TENANT_POLICIES='{"team-a": {"allowed_projects": ["billing-*"]}}'
- Manifest YAML (tenant_policies section)
- Programmatic registration
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class TenantPolicy:
    """Access policy for a single tenant."""

    tenant_id: str
    allowed_projects: list[str] = field(default_factory=list)
    denied_projects: list[str] = field(default_factory=list)
    max_memories_per_project: int = 50000
    max_projects: int = 100
    read_only: bool = False
    rate_limit_key: str | None = None

    def can_access(self, project_id: str) -> bool:
        """Check if this tenant is allowed to access *project_id*."""
        # Deny list takes precedence
        for pattern in self.denied_projects:
            if fnmatch.fnmatch(project_id, pattern):
                return False
        # If allow list is empty, everything is allowed (minus denies)
        if not self.allowed_projects:
            return True
        return any(
            fnmatch.fnmatch(project_id, pattern)
            for pattern in self.allowed_projects
        )

    def can_write(self, project_id: str) -> bool:
        """Check if this tenant can write to *project_id*."""
        if self.read_only:
            return False
        return self.can_access(project_id)


class AccessController:
    """Multi-tenant access control manager.

    In single-tenant mode (no policies configured), all operations are
    allowed with an implicit default tenant.
    """

    SUPERUSER_TENANT = "__superuser__"

    def __init__(self, *, enabled: bool = True):
        self._policies: dict[str, TenantPolicy] = {}
        self._lock = threading.Lock()
        self._enabled = enabled
        self._default_tenant_id = os.environ.get("DEFAULT_TENANT_ID", "default")
        self._violations = 0

    @property
    def enabled(self) -> bool:
        return self._enabled and bool(self._policies)

    @property
    def violations(self) -> int:
        return self._violations

    def register_policy(self, policy: TenantPolicy) -> None:
        with self._lock:
            self._policies[policy.tenant_id] = policy

    def remove_policy(self, tenant_id: str) -> None:
        with self._lock:
            self._policies.pop(tenant_id, None)

    def get_policy(self, tenant_id: str) -> TenantPolicy | None:
        with self._lock:
            return self._policies.get(tenant_id)

    def resolve_tenant(self, arguments: dict[str, Any]) -> str:
        """Extract tenant_id from request arguments or fall back to default."""
        return str(arguments.get("tenant_id") or self._default_tenant_id)

    def check_access(self, tenant_id: str, project_id: str) -> tuple[bool, str]:
        """Check if tenant can access project. Returns (allowed, reason)."""
        if not self.enabled:
            return True, "access_control_disabled"

        if tenant_id == self.SUPERUSER_TENANT:
            return True, "superuser"

        policy = self.get_policy(tenant_id)
        if policy is None:
            # Unknown tenant with AC enabled: deny by default
            self._violations += 1
            return False, f"unknown_tenant:{tenant_id}"

        if not policy.can_access(project_id):
            self._violations += 1
            return False, f"project_denied:{project_id}"

        return True, "allowed"

    def check_write(self, tenant_id: str, project_id: str) -> tuple[bool, str]:
        """Check if tenant can write to project."""
        allowed, reason = self.check_access(tenant_id, project_id)
        if not allowed:
            return allowed, reason

        policy = self.get_policy(tenant_id)
        if policy and policy.read_only:
            self._violations += 1
            return False, "read_only_tenant"

        return True, "write_allowed"

    def load_from_env(self) -> int:
        """Load tenant policies from TENANT_POLICIES env var (JSON).

        Returns count of policies loaded.
        """
        raw = os.environ.get("TENANT_POLICIES", "")
        if not raw:
            return 0

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            LOGGER.warning("Invalid TENANT_POLICIES JSON: %s", exc)
            return 0

        if not isinstance(data, dict):
            return 0

        count = 0
        for tenant_id, config in data.items():
            if not isinstance(config, dict):
                continue
            policy = TenantPolicy(
                tenant_id=str(tenant_id),
                allowed_projects=config.get("allowed_projects", []),
                denied_projects=config.get("denied_projects", []),
                max_memories_per_project=int(config.get("max_memories_per_project", 50000)),
                max_projects=int(config.get("max_projects", 100)),
                read_only=bool(config.get("read_only", False)),
                rate_limit_key=config.get("rate_limit_key"),
            )
            self.register_policy(policy)
            count += 1

        LOGGER.info("Loaded %d tenant policies from environment", count)
        return count

    def load_from_manifest(self, manifest: dict[str, Any]) -> int:
        """Load tenant policies from manifest YAML (tenant_policies section)."""
        policies_section = manifest.get("tenant_policies")
        if not isinstance(policies_section, dict):
            return 0

        count = 0
        for tenant_id, config in policies_section.items():
            if not isinstance(config, dict):
                continue
            policy = TenantPolicy(
                tenant_id=str(tenant_id),
                allowed_projects=config.get("allowed_projects", []),
                denied_projects=config.get("denied_projects", []),
                max_memories_per_project=int(config.get("max_memories_per_project", 50000)),
                max_projects=int(config.get("max_projects", 100)),
                read_only=bool(config.get("read_only", False)),
                rate_limit_key=config.get("rate_limit_key"),
            )
            self.register_policy(policy)
            count += 1

        return count

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.enabled,
                "tenant_count": len(self._policies),
                "tenants": list(self._policies.keys()),
                "violations": self._violations,
            }
