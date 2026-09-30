#!/usr/bin/env python3
"""Validate fail-closed memory.retrieval closure contracts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

HEX40 = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_STAGES = [
    "prepare",
    "durable_publish",
    "restart_recover",
    "query",
    "decision",
    "native_consume",
    "downstream_effect",
    "acknowledgement",
]
EXPECTED_QUALITY_CASES = {
    "multilingual-cjk",
    "code-path-queries",
    "long-query",
    "empty-query",
    "stale-source",
    "contradictory-source",
    "adversarial-near-duplicate",
    "cross-tenant-isolation",
    "float32-int16-int8-comparison",
    "ann-versus-full-scan",
}
EXPECTED_METRICS = {
    "latency_p50",
    "latency_p95",
    "latency_p99",
    "stage_latency_p50",
    "stage_latency_p95",
    "stage_latency_p99",
    "candidates_scanned",
    "top_k",
    "score_distribution",
    "ood_distribution",
    "cpu_time",
    "rss_peak",
    "allocation_bytes",
    "snapshot_bytes",
    "snapshot_age",
    "contention",
    "deadline_rejections",
    "cancellation_rejections",
    "budget_rejections",
    "worker_kill_success_rate",
    "host_survival_rate",
    "downstream_effect_success_rate",
}
EXPECTED_PRODUCTION_GATES = {
    "named-protected-host",
    "exact-binary-source-tree",
    "process-tree-cpu-rss-wall-isolation",
    "kill-points-and-host-survival",
    "external-immutable-raw-evidence",
    "independent-identity-signature",
    "operator-security-release-acceptance",
    "canary",
    "rollback-rehearsal",
    "approved-slo-and-automatic-fallback",
}


class ContractError(ValueError):
    """A fail-closed contract violation."""


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys
        )
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(f"{path}: {error}") from error
    if not isinstance(value, dict):
        raise ContractError(f"{path}: top-level value must be an object")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def validate_composition(root: Path) -> None:
    path = root / "qualification/memory-retrieval/product-composition.json"
    value = load_json(path)
    require(
        value.get("schema") == "hepta.memory-retrieval.product-composition.v1",
        f"{path}: wrong schema",
    )
    require(value.get("module") == "memory.retrieval", f"{path}: wrong module")
    stages = value.get("stages")
    require(isinstance(stages, list), f"{path}: stages must be an array")
    require(
        [stage.get("name") for stage in stages if isinstance(stage, dict)]
        == EXPECTED_STAGES,
        f"{path}: lifecycle stages must be exact and ordered",
    )
    for ordinal, stage in enumerate(stages, start=1):
        require(isinstance(stage, dict), f"{path}: malformed lifecycle stage")
        require(stage.get("ordinal") == ordinal, f"{path}: non-contiguous stage ordinal")
        require(
            stage.get("identityField") == "execution_identity_v1",
            f"{path}: every stage must carry the same execution identity",
        )

    production_enabled = value.get("productionEnabled")
    require(
        isinstance(production_enabled, bool),
        f"{path}: productionEnabled must be boolean",
    )
    if production_enabled:
        require(
            value.get("activationMode") == "production",
            f"{path}: production mode required",
        )
        require(
            value.get("encoder", {}).get("state") == "qualified",
            f"{path}: encoder unqualified",
        )
        require(
            value.get("index", {}).get("state") == "qualified",
            f"{path}: index unqualified",
        )
        security = value.get("security", {})
        for field in ("transport", "endpoint", "mtlsProfile"):
            require(
                bool(security.get(field)),
                f"{path}: missing production security field {field}",
            )
        require(bool(security.get("authScopes")), f"{path}: production scopes are empty")
        require(not value.get("promotionBlockers"), f"{path}: production has blockers")
    else:
        require(
            value.get("activationMode") == "compatibility",
            f"{path}: non-production manifest must remain compatibility-only",
        )
        require(bool(value.get("promotionBlockers")), f"{path}: blockers must be explicit")


def validate_quality_policy(root: Path) -> None:
    path = root / "qualification/memory-retrieval/quality-performance-policy.json"
    value = load_json(path)
    require(
        value.get("schema")
        == "hepta.memory-retrieval.quality-performance-policy.v1",
        f"{path}: wrong schema",
    )
    require(
        set(value.get("requiredQualityCases", [])) == EXPECTED_QUALITY_CASES,
        f"{path}: case matrix drift",
    )
    require(
        set(value.get("requiredMetrics", [])) == EXPECTED_METRICS,
        f"{path}: metrics matrix drift",
    )
    require(
        isinstance(value.get("minimumSamplesPerCase"), int)
        and value["minimumSamplesPerCase"] >= 100,
        f"{path}: sample minimum must be at least 100",
    )
    if value.get("productionEligible"):
        require(
            value.get("evidenceStatus") == "accepted",
            f"{path}: evidence is not accepted",
        )
        require(
            value.get("acceptanceThresholdsState") == "approved",
            f"{path}: thresholds are not approved",
        )
    else:
        require(
            value.get("evidenceStatus") != "accepted",
            f"{path}: contradictory evidence status",
        )


def validate_production_policy(root: Path) -> None:
    path = root / "qualification/memory-retrieval/production-qualification.json"
    value = load_json(path)
    require(
        value.get("schema") == "hepta.memory-retrieval.production-qualification.v1",
        f"{path}: wrong schema",
    )
    gates = value.get("gates")
    require(isinstance(gates, list), f"{path}: gates must be an array")
    ids = [gate.get("id") for gate in gates if isinstance(gate, dict)]
    require(len(ids) == len(set(ids)), f"{path}: duplicate gate IDs")
    require(set(ids) == EXPECTED_PRODUCTION_GATES, f"{path}: production gate matrix drift")
    all_passed = all(
        isinstance(gate, dict)
        and gate.get("passed") is True
        and bool(gate.get("evidence"))
        for gate in gates
    )
    require(
        value.get("releaseEligible") is all_passed,
        f"{path}: releaseEligible must equal the evidence-backed gate conjunction",
    )
    boundary = value.get("claimBoundary")
    require(isinstance(boundary, dict), f"{path}: missing claim boundary")
    if not all_passed:
        for claim in (
            "productionImplementation",
            "productExecutionProved",
            "independentAcceptance",
            "activation",
            "release",
        ):
            require(boundary.get(claim) is False, f"{path}: premature claim {claim}")


def validate_implementation_map(root: Path) -> None:
    path = root / "docs/modules/memory.retrieval/IMPLEMENTATION_MAP.json"
    value = load_json(path)
    require(
        value.get("sourceIdentityPolicy")
        == "exact_parent_observation_plus_runtime_manifest_v1",
        f"{path}: source identity policy drift",
    )
    observed = value.get("observedAtHead")
    require(isinstance(observed, dict), f"{path}: observedAtHead missing")
    require(
        bool(HEX40.fullmatch(str(observed.get("commit", "")))),
        f"{path}: invalid observed commit",
    )
    require(
        bool(HEX40.fullmatch(str(observed.get("tree", "")))),
        f"{path}: invalid observed tree",
    )
    operations = value.get("operations")
    require(isinstance(operations, list), f"{path}: operations missing")
    indexed = {
        operation.get("operation"): operation
        for operation in operations
        if isinstance(operation, dict)
    }
    for name in ("build_candidate_union", "recall"):
        operation = indexed.get(name)
        require(isinstance(operation, dict), f"{path}: operation {name} missing")
        require(bool(operation.get("tests")), f"{path}: operation {name} lacks direct tests")


def stamp_observation(root: Path, commit: str, tree: str) -> None:
    require(bool(HEX40.fullmatch(commit)), "stamp commit must be lowercase 40-hex")
    require(bool(HEX40.fullmatch(tree)), "stamp tree must be lowercase 40-hex")
    path = root / "docs/modules/memory.retrieval/IMPLEMENTATION_MAP.json"
    value = load_json(path)
    value["observedAtHead"] = {"commit": commit, "tree": tree}
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--stamp-observation", nargs=2, metavar=("COMMIT", "TREE"))
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.stamp_observation:
            stamp_observation(root, *args.stamp_observation)
        validate_composition(root)
        validate_quality_policy(root)
        validate_production_policy(root)
        validate_implementation_map(root)
    except ContractError as error:
        print(f"memory.retrieval closure validation failed: {error}", file=sys.stderr)
        return 1
    print("memory.retrieval closure contracts: valid and fail-closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
