#!/usr/bin/env python3
"""Closed-world verifier for the HNMF qualification package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.hepta_metadata import AUTHORITY_KEYS, has_schema_version
except ModuleNotFoundError as error:
    if error.name != "scripts":
        raise
    from hepta_metadata import AUTHORITY_KEYS, has_schema_version

ROOT = Path(__file__).resolve().parents[1]


MODALITIES = [
    "text",
    "image",
    "audio",
    "video",
    "code_ast",
    "gui_state",
    "tool_trajectory",
    "structured_data",
    "sensor",
]

POPULATIONS = [
    "sensory_trace",
    "episodic_binding",
    "semantic_concept",
    "procedural_skill",
    "predictive_world",
    "utility_salience",
    "meta_memory",
]

PROTOCOLS = [
    "ModalitySpanRefV1",
    "MemoryEventV1",
    "CrossModalBindingV1",
    "EngramNodeV1",
    "SynapseV1",
    "MemoryCueV1",
    "RecallPacketV1",
    "OutcomeSignalV1",
    "ReplaySelectionReceiptV1",
    "PlasticityBatchV1",
    "TopologyProposalV1",
    "ForgetPropagationReceiptV1",
]

WORK_PACKAGES = [
    "HNM-0-MULTIMODAL-CONTRACTS",
    "HNM-1-IMMUTABLE-EVENT-LEDGER",
    "HNM-2-HYBRID-PROJECTIONS",
    "HNM-3-SPARSE-ENGRAM-RECALL",
    "HNM-4-REPLAY-WORLD-PLASTICITY",
    "HNM-5-LONGITUDINAL-UNLEARNING",
    "HNM-6-STRUCTURAL-EVOLUTION",
]

TECHNICAL_HEADINGS = [
    "## 1. Authority, scope and non-goals",
    "## 2. Closed blocker model",
    "## 3. Source-of-truth and projection hierarchy",
    "## 4. Canonical multimodal data model",
    "## 5. Seven functional engram populations",
    "## 6. Fixed-point neuron dynamics",
    "## 7. Admission and write path",
    "## 8. Recall and contradiction path",
    "## 9. Replay and consolidation",
    "## 10. Eligibility, modulation and candidate plasticity",
    "## 11. Forgetting and non-resurrection",
    "## 12. Existing-module ownership map",
    "## 13. Resource, performance and concurrency bounds",
    "## 14. Security and privacy controls",
    "## 15. Verification and acceptance",
    "## 16. Bounded migration",
    "## 17. Claim ladder",
    "## 18. Work-package closure",
]

REQUIRED_FILES = [
    "docs/hnmf/README.md",
    "docs/hnmf/TECHNICAL.md",
    "docs/hnmf/MIGRATION.md",
    "docs/hnmf/HNMF.json",
    "docs/hnmf/GAPS.json",
    "qualification/hnmf-reference/Cargo.toml",
    "qualification/hnmf-reference/Cargo.lock",
    "qualification/hnmf-reference/README.md",
    "qualification/hnmf-reference/src/lib.rs",
    "codex-rs/hepta-cognitive-types/Cargo.toml",
    "codex-rs/hepta-cognitive-types/src/hnmf/mod.rs",
    "codex-rs/hepta-cognitive-types/src/hnmf/wire.rs",
    "codex-rs/hepta-cognitive-types/src/hnmf/span.rs",
    "codex-rs/hepta-cognitive-types/src/hnmf/event.rs",
    "codex-rs/hepta-cognitive-types/src/hnmf/engram.rs",
    "codex-rs/hepta-cognitive-types/src/hnmf/recall.rs",
    "codex-rs/hepta-cognitive-types/src/hnmf/replay.rs",
    "codex-rs/hepta-cognitive-types/src/hnmf/plasticity.rs",
    "codex-rs/hepta-cognitive-types/src/hnmf/forget.rs",
    "codex-rs/hepta-cognitive-types/tests/hnmf_reference_conformance.rs",
    "codex-rs/hepta-cognitive-types/tests/data/hnmf_conformance_v1.json",
    ".github/workflows/hnmf-qualification.yml",
]

RUST_TOKENS = [
    "pub enum ModalityKind",
    "pub enum EngramPopulation",
    "pub struct MemoryEvent",
    "pub struct EngramNode",
    "pub struct Synapse",
    "pub struct RecallPacket",
    "pub struct OutcomeSignal",
    "pub struct PlasticityBatch",
    "pub enum TopologyOperation",
    "pub struct ForgetBatch",
    "pub fn recall",
    "pub fn propose_plasticity",
    "pub fn apply_plasticity",
    "pub fn propose_forget",
    "pub fn apply_forget",
    "pub fn select_replay",
    "fn sparse_select",
    "CURRENT_RUN_MUTATION_ALLOWED: bool = false",
    "ONLINE_TOPOLOGY_ACTIVATION_ALLOWED: bool = false",
    "PRODUCTION_AUTHORITY: bool = false",
    "EXTERNAL_EFFECTS_ALLOWED: bool = false",
]

RUST_TESTS = [
    "cross_modal_pattern_completion_recalls_episode",
    "sparse_competition_is_bounded",
    "contradiction_forces_abstention",
    "plasticity_does_not_mutate_current_snapshot",
    "applying_plasticity_creates_exact_next_generation",
    "homeostasis_raises_threshold_for_active_node",
    "eligibility_trace_decays_without_new_coactivation",
    "modulator_is_risk_and_ood_bounded",
    "replay_selection_enforces_source_quota",
    "forgetting_prevents_recall_resurrection",
    "insertion_order_does_not_change_recall",
    "topology_proposal_cannot_self_activate",
    "hard_bounds_fail_closed",
]


class DuplicateKey(ValueError):
    """Raised for duplicate JSON object keys."""


def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKey(key)
        result[key] = value
    return result


def fail(message: str) -> None:
    raise SystemExit(f"FAIL_HEPTA_HNMF: {message}")


def need(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def load_json(path: str) -> dict[str, Any]:
    file_path = ROOT / path
    try:
        value = json.loads(
            file_path.read_text(encoding="utf-8"), object_pairs_hook=object_pairs
        )
    except Exception as error:  # noqa: BLE001 - verifier reports exact parse failures.
        fail(f"{path}: {error}")
    need(isinstance(value, dict), f"{path}: top-level object required")
    return value


def false_authority(value: Any, label: str) -> None:
    need(isinstance(value, dict), f"{label}: authority object required")
    need(list(value) == AUTHORITY_KEYS, f"{label}: authority key order/closure")
    need(not any(value.values()), f"{label}: positive authority is forbidden")


def verify() -> int:
    for path in REQUIRED_FILES:
        need((ROOT / path).is_file(), f"missing required file {path}")

    spec = load_json("docs/hnmf/HNMF.json")
    gaps = load_json("docs/hnmf/GAPS.json")

    need(spec.get("schema") == "hepta.hnmf.qualification.v1", "spec schema")
    need(has_schema_version(spec, 1), "spec schema version")
    need(spec.get("planId") == "HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN", "spec plan id")
    need(spec.get("planVersion") == "8.0.0", "spec plan version")
    need(
        spec.get("baselineCommit") == "70ef65a90a031ce0cc08b77b5596eb0d99edaa11",
        "spec baseline",
    )
    need(spec.get("modalities") == MODALITIES, "modality closure")
    need(
        [item.get("id") for item in spec.get("populations", [])] == POPULATIONS,
        "population closure",
    )
    need(
        [item.get("id") for item in spec.get("protocols", [])] == PROTOCOLS,
        "protocol closure",
    )
    need(
        [item.get("id") for item in spec.get("workPackages", [])] == WORK_PACKAGES,
        "work-package closure",
    )
    need(
        all(item.get("state") == "closed_reference" for item in spec["workPackages"]),
        "work-package reference state",
    )
    false_authority(spec.get("authorityFlags"), "spec")

    source = spec.get("sourceOfTruth", {})
    need(source.get("vectorDatabaseIsMemory") is False, "vector database authority")
    need(
        source.get("projectionMayMutateSourceFacts") is False,
        "projection mutation authority",
    )

    dynamics = spec.get("dynamics", {})
    need(dynamics.get("currentRunMutationAllowed") is False, "current-run mutation")
    need(
        dynamics.get("onlineTopologyActivationAllowed") is False,
        "online topology activation",
    )

    bounds = spec.get("resourceBounds", {})
    expected_bounds = {
        "maximumCandidateEvents": 512,
        "maximumNodes": 4096,
        "maximumSynapses": 32768,
        "maximumActiveNodes": 4096,
        "maximumActivePerPopulation": 64,
        "maximumRecurrentSteps": 4,
        "maximumRecallEvents": 16,
        "maximumActivationPaths": 32,
        "maximumReplayCandidates": 4096,
        "maximumReplaySelection": 256,
        "maximumWeightDeltaPpm": 50000,
    }
    need(bounds == expected_bounds, "resource bounds")

    defaults = spec.get("qualificationDefaults", {})
    need(defaults.get("minimumIndependentSnapshots", 0) >= 3, "snapshot evidence floor")
    need(defaults.get("minimumFutureCalendarWindows", 0) >= 2, "future-window floor")
    need(defaults.get("minimumEffectiveSampleSize", 0) >= 200, "ESS floor")
    need(
        defaults.get("candidateLcbMustExceedBaselineUcb") is True,
        "promotion interval rule",
    )
    need(
        defaults.get("maximumDeletionResurrectionCount") == 0,
        "deletion non-resurrection",
    )
    need(
        defaults.get("maximumUnresolvedHighRiskContradictions") == 0,
        "contradiction floor",
    )

    claims = spec.get("claimPosture", {})
    need(claims.get("referenceContractsClosed") is True, "reference contracts claim")
    need(claims.get("referenceAlgorithmsClosed") is True, "reference algorithms claim")
    for key in [
        "productionActivation",
        "longitudinalEfficacy",
        "functionalBiomimicry",
        "neuromorphicMechanism",
        "selfIterationProductionAuthority",
    ]:
        need(claims.get(key) is False, f"claim posture {key}")

    need(gaps.get("schema") == "hepta.hnmf.gap-ledger.v1", "gap schema")
    need(gaps.get("allReferenceGapsClosed") is True, "reference gap closure")
    need(gaps.get("productionActivationClaimed") is False, "gap production claim")
    gap_rows = gaps.get("gaps", [])
    need(len(gap_rows) == 18, "gap count")
    need(len({row.get("id") for row in gap_rows}) == 18, "gap ids")
    need(
        all(row.get("referenceState") == "closed_reference" for row in gap_rows),
        "gap reference states",
    )
    need(
        all(
            row.get("productionState") == "requires_independent_activation_evidence"
            for row in gap_rows
        ),
        "gap production states",
    )
    need(all(row.get("evidence") for row in gap_rows), "gap evidence")
    false_authority(gaps.get("authorityFlags"), "gaps")

    technical_path = "docs/hnmf/TECHNICAL.md"
    technical = (ROOT / technical_path).read_text(encoding="utf-8")
    need(len(technical.encode("utf-8")) >= 20_000, "technical specification too small")
    positions = [technical.find(heading) for heading in TECHNICAL_HEADINGS]
    need(all(position >= 0 for position in positions), "technical heading coverage")
    need(positions == sorted(positions), "technical heading ordering")
    need(len(set(positions)) == len(positions), "technical heading uniqueness")

    migration_path = "docs/hnmf/MIGRATION.md"
    migration = (ROOT / migration_path).read_text(encoding="utf-8")
    for phase in ["M0", "M1", "M2", "M3", "M4", "M5"]:
        need(f"Phase {phase}" in migration, f"migration phase {phase}")

    rust_path = "qualification/hnmf-reference/src/lib.rs"
    rust = (ROOT / rust_path).read_text(encoding="utf-8")
    need(len(rust.encode("utf-8")) >= 35_000, "reference runtime too small")
    for token in RUST_TOKENS + RUST_TESTS:
        need(token in rust, f"reference token {token}")
    need(
        "unsafe" not in rust.replace("#![forbid(unsafe_code)]", ""), "unsafe code token"
    )


    production_root = ROOT / "codex-rs/hepta-cognitive-types/src/hnmf"
    production_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(production_root.glob("*.rs"))
        if path.name != "tests.rs"
    )
    for protocol in PROTOCOLS:
        need(protocol in production_source, f"production protocol {protocol}")
    for token in [
        "pub trait CanonicalJsonV1",
        "deny_unknown_fields",
        "pub fn try_new",
        "MemoryVerificationStateV1",
        "RetentionPolicyV1",
        "current_snapshot_immutable",
        "production_activation_allowed",
    ]:
        need(token in production_source, f"production HNMF token {token}")
    conformance = (
        ROOT / "codex-rs/hepta-cognitive-types/tests/hnmf_reference_conformance.rs"
    ).read_text(encoding="utf-8")
    for token in [
        "canonical_event_fixture_is_valid_in_reference_and_production",
        "modality_range_mismatch_fails_closed_in_reference_and_production",
        "modality_closed_world_matches_reference",
    ]:
        need(token in conformance, f"production/reference conformance {token}")

    workflow = (ROOT / ".github/workflows/hnmf-qualification.yml").read_text(
        encoding="utf-8"
    )
    for command in [
        "python3 scripts/hepta-hnmf.py verify",
        "cargo fmt --manifest-path qualification/hnmf-reference/Cargo.toml -- --check",
        "cargo check --manifest-path qualification/hnmf-reference/Cargo.toml --all-targets --locked",
        "cargo test --manifest-path qualification/hnmf-reference/Cargo.toml --locked",
        "cargo check --manifest-path codex-rs/Cargo.toml --package codex-hepta-cognitive-types --all-targets --locked",
        "cargo clippy --manifest-path codex-rs/Cargo.toml --package codex-hepta-cognitive-types --all-targets --locked -- -D warnings",
        "cargo test --manifest-path codex-rs/Cargo.toml --package codex-hepta-cognitive-types --locked",
    ]:
        need(command in workflow, f"workflow command {command}")

    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_HNMF_REFERENCE_CLOSED_WORLD",
                "modalities": len(MODALITIES),
                "populations": len(POPULATIONS),
                "protocols": len(PROTOCOLS),
                "workPackages": len(WORK_PACKAGES),
                "gaps": len(gap_rows),
                "productionAuthority": False,
            },
            sort_keys=True,
        )
    )
    return 0


def self_test() -> int:
    try:
        json.loads('{"a":1,"a":2}', object_pairs_hook=object_pairs)
    except DuplicateKey:
        pass
    else:
        fail("duplicate-key fixture")
    need(len(MODALITIES) == 9, "modality fixture")
    need(len(POPULATIONS) == 7, "population fixture")
    need(len(WORK_PACKAGES) == 7, "work-package fixture")
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_HNMF_SELF_TEST",
                "cases": [
                    "duplicate_keys",
                    "modalities",
                    "populations",
                    "work_packages",
                ],
                "productionAuthority": False,
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["verify", "self-test"])
    arguments = parser.parse_args()
    return verify() if arguments.command == "verify" else self_test()


if __name__ == "__main__":
    raise SystemExit(main())
