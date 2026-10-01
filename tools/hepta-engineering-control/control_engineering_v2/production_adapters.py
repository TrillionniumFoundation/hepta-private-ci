"""Fail-closed ports for externally governed production dependencies."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .control_plane import EngineeringError
from .external_controls import (
    AuditAnchorAttestation,
    DistributedFenceReceipt,
    DistributedRevocationFrontierReceipt,
    KeyCustodyReceipt,
)
from .integration_controller import IntegrationTerminalReceipt
from .orchestration import CompletionReceipt


class DistributedFenceProvider(Protocol):
    provider_id: str

    def current_frontier(self) -> DistributedRevocationFrontierReceipt: ...

    def current_fence(self) -> DistributedFenceReceipt: ...


class ImmutableAuditLogProvider(Protocol):
    provider_id: str

    def current_anchor(self) -> AuditAnchorAttestation: ...


class KeyCustodyProvider(Protocol):
    provider_id: str

    def custody_receipts(self) -> tuple[KeyCustodyReceipt, ...]: ...


class CompletionObserver(Protocol):
    provider_id: str

    def completion_receipt(self) -> CompletionReceipt: ...


class IntegrationTerminalObserver(Protocol):
    provider_id: str

    def terminal_receipt(self) -> IntegrationTerminalReceipt: ...


@dataclass(frozen=True)
class ProductionProviderSet:
    distributed_fence: DistributedFenceProvider
    immutable_audit_log: ImmutableAuditLogProvider
    key_custody: KeyCustodyProvider
    completion_observer: CompletionObserver
    terminal_observer: IntegrationTerminalObserver


def validate_live_provider_set(providers: ProductionProviderSet) -> tuple[str, ...]:
    if not isinstance(providers, ProductionProviderSet):
        raise EngineeringError("production_provider_set_required")
    identities = []
    for provider in (
        providers.distributed_fence,
        providers.immutable_audit_log,
        providers.key_custody,
        providers.completion_observer,
        providers.terminal_observer,
    ):
        identity = getattr(provider, "provider_id", None)
        if not isinstance(identity, str) or not identity:
            raise EngineeringError("production_provider_identity")
        folded = identity.casefold()
        if any(
            token in folded for token in ("fixture", "test", "mock", "local-hmac")
        ):
            raise EngineeringError("production_fixture_provider_rejected")
        identities.append(identity)
    if len(set(identities)) != len(identities):
        raise EngineeringError("production_provider_role_collision")
    return tuple(identities)
