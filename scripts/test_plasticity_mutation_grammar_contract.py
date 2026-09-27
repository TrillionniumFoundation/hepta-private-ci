#!/usr/bin/env python3
"""Verify the control.engineering -> learning.plasticity grammar projection.

This is a static cross-owner contract test. It proves that the canonical protocol
owner/consumer declaration and the executable Rust projection agree; it does not
issue runtime authority, independent acceptance, activation, or release.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    protocols = load("docs/readiness/PROTOCOLS.json")
    rows = [row for row in objects(protocols) if row.get("id") == "MutationGrammarManifestV1"]
    require(len(rows) == 1, "MutationGrammarManifestV1 must have one canonical readiness row")
    protocol = rows[0]
    require(protocol.get("owner") == "control.engineering", "grammar owner drift")
    require(
        "learning.plasticity" in protocol.get("consumers", []),
        "learning.plasticity is not a registered grammar consumer",
    )
    require(protocol.get("authorityDelta") == "none", "grammar protocol may not grant authority")

    contracts = load("docs/contracts/CONTRACTS.json")
    envelopes = [row for row in objects(contracts) if row.get("id") == "IterationEnvelopeV1"]
    require(len(envelopes) == 1, "IterationEnvelopeV1 must have one canonical contract row")
    require(
        envelopes[0].get("producer") == "control.engineering",
        "IterationEnvelopeV1 producer drift",
    )

    implementation = load("docs/modules/learning.plasticity/IMPLEMENTATION_MAP.json")
    operations = {
        operation.get("operation"): operation
        for operation in implementation.get("operations", [])
    }
    mutation = operations.get("parameter_mutation_policy")
    require(mutation is not None, "parameter mutation policy is not implementation-mapped")
    require(
        mutation.get("sourcePath")
        == "codex-rs/hepta-plasticity/src/parameter_mutation_policy_v1.rs",
        "parameter mutation policy source drift",
    )
    require(mutation.get("authority") == "none", "mutation projection may not grant authority")

    policy_source = (
        ROOT / "codex-rs/hepta-plasticity/src/parameter_mutation_policy_v1.rs"
    ).read_text(encoding="utf-8")
    for token in (
        "MutationGrammarManifestV1",
        "mutation_grammar_digest",
        "EmptyMutationGrammar",
        "bytes.extend_from_slice(policy.mutation_grammar_digest.as_array())",
        "ParameterMutationSurfaceV1::Authority",
        "ParameterMutationSurfaceV1::RuntimeTopology",
        "ParameterMutationSurfaceV1::Credential",
    ):
        require(token in policy_source, f"mutation projection is missing {token}")

    coverage_source = (
        ROOT / "codex-rs/hepta-plasticity/src/generator_coverage_v1.rs"
    ).read_text(encoding="utf-8")
    for token in (
        "expected_learnable_parameter_set_digest",
        "actual_signal_set_digest",
        "scale_policy_digest",
        "mutation_grammar_digest",
        "owner_frontier_digest",
        "ZeroEligibleSignals",
        "PolicyDisabledUpdates",
    ):
        require(token in coverage_source, f"coverage receipt is missing {token}")

    coordinator_source = (
        ROOT / "codex-rs/hepta-agentd/src/control_engineering_iteration_base.rs"
    ).read_text(encoding="utf-8")
    replay_source = (
        ROOT / "codex-rs/hepta-agentd/src/control_engineering_iteration.rs"
    ).read_text(encoding="utf-8")
    require(
        "envelope.grammar_digest" in coordinator_source,
        "frozen iteration context does not bind the envelope grammar",
    )
    require(
        "lookup_exact_replay" in replay_source,
        "coordinator does not reconcile exact terminal replay before product I/O",
    )
    require(
        "submit_parameter_plasticity_v1" in replay_source,
        "coordinator bypasses or omits the named Agentd producer path",
    )

    print(
        json.dumps(
            {
                "contract": "MutationGrammarManifestV1",
                "owner": "control.engineering",
                "consumer": "learning.plasticity",
                "projection": mutation["sourcePath"],
                "coverage": "GeneratorCoverageReceiptV1",
                "authority_delta": "none",
                "status": "passed",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, OSError, ValueError) as error:
        print(f"plasticity grammar contract failed: {error}", file=sys.stderr)
        raise SystemExit(1)
