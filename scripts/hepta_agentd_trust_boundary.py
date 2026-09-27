#!/usr/bin/env python3
"""Fail closed when runtime.agentd gains an unreviewed authority path."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "codex-rs" / "hepta-agentd" / "src"


@dataclass(frozen=True)
class BoundaryRule:
    token: str
    allowed_paths: frozenset[str]


RULES = (
    BoundaryRule(
        "start_current_run_start_record(",
        frozenset({"state.rs", "run_start_authority.rs"}),
    ),
    BoundaryRule(
        "start_canonical_intelligence(",
        frozenset({"state.rs", "run_start_authority.rs"}),
    ),
    BoundaryRule(
        "start_revalidated_run_start(",
        frozenset({"state.rs", "lane_b_runtime.rs"}),
    ),
    BoundaryRule(
        "RunSnapshot::from_revalidated_run_start(",
        frozenset({"lane_b_runtime.rs"}),
    ),
    BoundaryRule(
        "authentication_is_current(",
        frozenset({"objective_runtime.rs", "run_start_authority.rs", "state.rs"}),
    ),
)


class BoundaryError(ValueError):
    pass


def rust_sources(root: Path = SOURCE_ROOT) -> list[Path]:
    return sorted(path for path in root.rglob("*.rs") if path.is_file())


def relative(path: Path, root: Path = SOURCE_ROOT) -> str:
    return path.relative_to(root).as_posix()


def token_locations(
    token: str, sources: Iterable[Path], root: Path = SOURCE_ROOT
) -> list[tuple[str, int]]:
    locations: list[tuple[str, int]] = []
    for path in sources:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if token in line:
                locations.append((relative(path, root), number))
    return locations


def require_markers(
    text: str, markers: Iterable[str], label: str, errors: list[str]
) -> None:
    for marker in markers:
        if marker not in text:
            errors.append(f"{label} lost required marker: {marker}")


def reject_markers(
    text: str, markers: Iterable[str], label: str, errors: list[str]
) -> None:
    for marker in markers:
        if marker in text:
            errors.append(f"{label} regained forbidden marker: {marker}")


def validate(root: Path = SOURCE_ROOT) -> list[str]:
    sources = rust_sources(root)
    errors: list[str] = []
    for rule in RULES:
        locations = token_locations(rule.token, sources, root)
        if not locations:
            errors.append(f"missing guarded symbol: {rule.token}")
            continue
        for path, line in locations:
            if path not in rule.allowed_paths:
                errors.append(
                    f"unreviewed RunStart authority path {path}:{line}: {rule.token}"
                )

    objective = (root / "objective_runtime.rs").read_text(encoding="utf-8")
    require_markers(
        objective,
        (
            "verify_current_run_start(agentd, record)?.admit_compatibility()?",
            "let verified = verify_current_run_start(agentd, &record)?;",
            "verified.admit().await?",
        ),
        "objective admission",
        errors,
    )
    reject_markers(
        objective,
        (
            "agentd.start_current_run_start_record(&record)",
            "agentd.start_canonical_intelligence(&record)",
        ),
        "objective admission",
        errors,
    )

    authority = (root / "run_start_authority.rs").read_text(encoding="utf-8")
    reject_markers(
        authority,
        (
            "#[derive(Clone",
            "impl Clone for VerifiedRunStartV1",
            "pub struct VerifiedRunStartV1",
        ),
        "sealed RunStart witness",
        errors,
    )

    neuron = (root / "neuron_runtime.rs").read_text(encoding="utf-8")
    require_markers(
        neuron,
        (
            "pub struct AgentdDurableNeuronInvocationHandleV1",
            "trait DurableNeuronInvocationOwnerPortV1: Send + Sync",
            "Arc<Mutex<AgentdNeuronOwner<W, P>>>",
            "runtime.configuration_digest()",
            "runtime.current_anchor()",
            "fn verify_invocation(",
        ),
        "durable Neuron owner",
        errors,
    )
    reject_markers(
        neuron,
        (
            "pub trait AgentdDurableNeuronInvocationOwnerV1",
            "pub owner_digest:",
            "pub owner_revision:",
            "pub generation:",
            "pub agent_id:",
            "pub fn new(\n        agent_id: AgentId,\n        generation: u64,\n        owner: Arc<dyn",
        ),
        "durable Neuron owner",
        errors,
    )

    bootstrap = (root / "canonical_runtime_bootstrap.rs").read_text(encoding="utf-8")
    require_markers(
        bootstrap,
        (
            "neuron_owner: AgentdDurableNeuronInvocationHandleV1",
            "let before = self.neuron_owner.current_witness(identity)?;",
            ".verify_invocation(identity, record, &invocation)?;",
            "let after = self.neuron_owner.current_witness(identity)?;",
            "if before != after",
        ),
        "canonical runtime bootstrap",
        errors,
    )
    reject_markers(
        bootstrap,
        (
            "pub trait AgentdDurableNeuronInvocationOwnerV1",
            "AgentdNeuronInvocationWitnessV1::new",
        ),
        "canonical runtime bootstrap",
        errors,
    )

    state_control = (root / "state_control.rs").read_text(encoding="utf-8")
    require_markers(
        state_control,
        (
            "self.canonical_intelligence_available()",
            "canonical_runtime_recovering",
            "canonical_configured && canonical_available",
        ),
        "canonical runtime readiness",
        errors,
    )

    return errors


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"FAIL_RUNTIME_AGENTD_TRUST_BOUNDARY: {error}", file=sys.stderr)
        return 1
    print("PASS_RUNTIME_AGENTD_TRUST_BOUNDARY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
