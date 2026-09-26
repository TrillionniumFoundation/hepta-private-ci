#!/usr/bin/env python3
"""Generate and verify the intelligence.control closed-world status projection.

The committed STATUS.json contains structural claims only. Exact commit/tree and
execution results are generated as CI receipts because embedding a commit in a
file that changes that commit is self-referential. This script fails closed when
a claimed source edge disappears or a document attempts to upgrade execution,
activation or release without an explicit receipt supplied by the workflow.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

MODULE = "intelligence.control"
STATUS_PATH = Path("docs/modules/intelligence.control/STATUS.json")


class TruthError(RuntimeError):
    pass


def read_text(root: Path, relative: str) -> str:
    path = root / relative
    if not path.is_file():
        raise TruthError(f"missing required source: {relative}")
    return path.read_text(encoding="utf-8")


def require_tokens(root: Path, relative: str, tokens: list[str]) -> None:
    text = read_text(root, relative)
    missing = [token for token in tokens if token not in text]
    if missing:
        raise TruthError(f"{relative} is missing required evidence: {missing}")


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def structural_projection(root: Path) -> dict[str, Any]:
    require_tokens(
        root,
        "codex-rs/hepta-intelligence/src/canonical.rs",
        [
            "pub fn prepare_intelligence_run",
            "selected candidate is not a legal candidate",
            "candidate_set.candidates",
            "validate_current_snapshot",
        ],
    )
    require_tokens(
        root,
        "codex-rs/hepta-agentd/src/intelligence_ingress.rs",
        [
            "authoritative_provider",
            "current_generation",
            "objective_run_fence_digest",
            "configuration_digest(record)",
        ],
    )
    require_tokens(
        root,
        "codex-rs/hepta-agentd/src/intelligence_profile.rs",
        [
            "AgentdCanonicalIntelligenceProfileV1",
            "with_canonical_intelligence_profile",
        ],
    )
    require_tokens(
        root,
        "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
        [
            "pub fn admission_generation",
            "pub fn objective_fence_digest",
            "CompositionMismatch",
            "require_composition_snapshot",
        ],
    )
    require_tokens(
        root,
        "codex-rs/hepta-agentd/src/intelligence_product_runner_core.rs",
        [
            "candidate_ids.sort()",
            "intuition_ids.sort()",
            "composition.admission_generation()",
            "composition.objective_fence_digest()",
        ],
    )
    require_tokens(
        root,
        "codex-rs/hepta-agentd/src/intelligence_learning_outbox.rs",
        [
            "Prepared",
            "Acknowledged",
            "Rejected",
            "Revoked",
            "Indeterminate",
            "pub fn reconcile",
        ],
    )
    require_tokens(
        root,
        "codex-rs/hepta-agentd/src/intelligence_product_learning.rs",
        [
            "append_production_decision",
            "append_production_outcome",
            "verify_active_decision_binding",
            "physical_terminal_digest",
        ],
    )
    require_tokens(
        root,
        "codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs",
        [
            "runtime_composition_rejects_wrong_generation_or_fence",
            "starting_composition_normalizes_only_to_its_running_successor",
            "supervisor_generation: 2",
            "agentd_generation: 3",
        ],
    )
    require_tokens(
        root,
        ".github/workflows/intelligence-control-closure.yml",
        [
            "fail-fast: false",
            "Agentd all-target check",
            "Agentd library tests",
            "Agentd strict clippy",
            "base-merge",
        ],
    )

    main_text = read_text(root, "codex-rs/hepta-agentd/src/main.rs")
    default_binary_composed = "with_canonical_intelligence_profile" in main_text

    return {
        "schema": "hepta.intelligence-control-status.v1",
        "schemaVersion": 1,
        "module": MODULE,
        "sourceIdentityPolicy": "exact_candidate_receipt_only",
        "implementation": {
            "canonicalFacadePresent": True,
            "authenticatedObjectiveRoutePresent": True,
            "authoritativeProviderFactoryPresent": True,
            "atomicHostProfileCompositionPresent": True,
            "defaultBinaryProfileComposed": default_binary_composed,
            "generationFenceUnified": True,
            "coordinatorCompositionIdentityEnforced": True,
            "canonicalCandidateMembershipEnforced": True,
            "rawCandidateOrderDecoupled": True,
            "durableLearningOutboxPresent": True,
            "authenticatedProductionDecisionApiPresent": True,
            "authenticatedProductionOutcomeApiPresent": True,
            "physicalTerminalBindingPresent": True,
            "distinctSpawnAndRunningGenerationTestsPresent": True,
            "independentQualificationWorkflowPresent": True,
        },
        "executionGates": {
            "sourceTestsPresent": True,
            "exactHeadExecuted": False,
            "deterministicMergeExecuted": False,
            "realProcessProviderE2ePassed": False,
            "targetHostHardTerminationQualified": False,
            "independentAcceptance": False,
            "activation": False,
            "release": False,
        },
        "claimRules": {
            "sourcePresenceIsNotExecution": True,
            "qualificationIsNotActivation": True,
            "indeterminateNeverMeansSuccess": True,
            "compatibilityRunStartIsNotCanonicalExecution": True,
            "capabilityRequiresRunnerAndProvider": True,
        },
    }


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TruthError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise TruthError(f"{path} must contain a JSON object")
    return value


def exact_receipt(
    root: Path,
    projection: dict[str, Any],
    lane: str,
    rust_result: str,
    formatting_result: str,
) -> dict[str, Any]:
    head = git(root, "rev-parse", "HEAD^{commit}")
    tree = git(root, "rev-parse", "HEAD^{tree}")
    if len(head) != 40 or len(tree) != 40:
        raise TruthError("git identity is not a full commit/tree hash")
    clean = not git(root, "status", "--porcelain", "--untracked-files=normal")
    executed = rust_result == "success" and formatting_result == "success"
    receipt = json.loads(json.dumps(projection))
    receipt["candidate"] = {
        "commit": head,
        "tree": tree,
        "lane": lane,
        "cleanWorktree": clean,
    }
    receipt["workflowResults"] = {
        "rust": rust_result,
        "formatting": formatting_result,
    }
    receipt["executionGates"]["exactHeadExecuted"] = executed and lane == "source-head"
    receipt["executionGates"]["deterministicMergeExecuted"] = (
        executed and lane == "base-merge"
    )
    return receipt


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root",
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write-status", action="store_true")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--lane", default=os.environ.get("HEPTA_INTELLIGENCE_LANE", "source-head"))
    parser.add_argument("--rust-result", default="not_run")
    parser.add_argument("--formatting-result", default="not_run")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    try:
        projection = structural_projection(root)
        committed_path = root / STATUS_PATH
        if args.write_status:
            write_json(committed_path, projection)
        if args.check:
            committed = load_json(committed_path)
            if committed != projection:
                raise TruthError(
                    f"{STATUS_PATH} is stale; run "
                    "scripts/hepta-intelligence-control-truth.py --write-status"
                )
        if args.receipt is not None:
            receipt = exact_receipt(
                root,
                projection,
                args.lane,
                args.rust_result,
                args.formatting_result,
            )
            write_json(args.receipt, receipt)
        if not args.check and not args.write_status and args.receipt is None:
            print(json.dumps(projection, indent=2, sort_keys=True))
    except (TruthError, subprocess.CalledProcessError) as error:
        print(f"intelligence.control truth failure: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
