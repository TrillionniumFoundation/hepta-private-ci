"""New artifact/publication checks around the unchanged independent policy audit."""

import argparse
import json
from pathlib import Path

import numpy as np

from experiments.continuous_boundary_policy.audit import audit_run as original_audit
from experiments.continuous_boundary_policy.audit_integrity import (
    LEARNED,
    SEEDS,
    read_json,
    strict_json,
    verify_selection,
)
from experiments.continuous_boundary_policy.audit_math import (
    expected_specs,
    reference,
    require,
)
from experiments.continuous_boundary_policy.audit_stats import inspect_native_cost
from experiments.continuous_boundary_policy.common import save_json, sha
from .identity import (
    SELECTION_PATH,
    verify_frozen,
    verify_marker,
    verify_preconfirmation,
    verify_publication,
)
from .sources import OLD_SEAL_SHA, REPOSITORY


def training_references(root):
    """Original context check restricted to train/dev; no confirmation generation."""
    references = {}
    for seed in SEEDS:
        for phase, count in (("training", 12), ("development", 8)):
            saved = read_json(root, f"contexts/{seed}/{phase}.json")
            require(
                saved["seed"] == seed
                and saved["phase"] == phase
                and len(saved["contexts"]) == count,
                "Task context schedule mismatch",
            )
            for index, (row, expected) in enumerate(
                zip(saved["contexts"], expected_specs(seed, phase, count))
            ):
                require(
                    row["id"] == f"{seed}.{phase}.context{index}"
                    and row["index"] == index
                    and row["spec"] == expected,
                    "Task parameters disagree with frozen phase stream",
                )
                ref = reference(expected)
                require(
                    sha(ref["q"].tobytes()) == row["dp_sha256"],
                    "Independent finite Bellman teacher digest mismatch",
                )
                references[seed, phase, index] = ref
                for name in ("model_build_cost", "planning_cost"):
                    require(
                        all(
                            np.isfinite(row[name][key]) and row[name][key] >= 0
                            for key in ("wall_seconds", "cpu_seconds")
                        ),
                        "Invalid shared solver clock",
                    )
    return references


def training_costs(root, training):
    rows = [
        strict_json(line) for line in (root / "costs.jsonl").read_bytes().splitlines()
    ]
    expected = {("training_setup", seed, None) for seed in SEEDS}
    expected |= {
        ("training_development", seed, arm) for seed in SEEDS for arm in LEARNED
    }
    seen, totals = (
        set(),
        dict.fromkeys(
            ("python_cpu_seconds", "completed_child_cpu_seconds", "wall_seconds"), 0.0
        ),
    )
    for row in rows:
        key = row["phase"], row["seed"], row.get("arm")
        require(
            key in expected and key not in seen,
            "Missing/duplicate/undeclared training cost phase",
        )
        seen.add(key)
        cost = row["cost"]
        for name in totals:
            value = cost[name]
            require(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and np.isfinite(value)
                and value >= 0,
                "Invalid measured training cost",
            )
            totals[name] += value
        if row["phase"] == "training_development":
            receipt = training[row["seed"], row["arm"]]
            require(
                cost == receipt["cost"]
                and row["native_process_cost"] == receipt["native_process_cost"],
                "Training cost ledger changed",
            )
            counters, _, _ = inspect_native_cost(row["native_process_cost"], cost)
            require(
                row["arm"] == "native_sparse" or counters["actual_kernel_calls"] == 0,
                "Continuous training invoked sparse cells",
            )
    require(seen == expected, "Incomplete training cost roster")
    return {"rows": len(rows), "totals": totals}


def preconfirmation(study, binaries=None, repository=REPOSITORY):
    root = Path(study).resolve()
    env = verify_frozen(root, binaries, repository)
    selection = verify_preconfirmation(root)
    refs = training_references(root)
    checkpoints, _, _, training = verify_selection(root, selection, refs)
    costs = training_costs(root, training)
    return {
        "schema": "hepta.boundary-policy-reproduction.preconfirmation-audit.v1",
        "passed": True,
        "source_seal_sha256": env["source_seal_sha256"],
        "protocol_sha256": env["protocol_sha256"],
        "selection_seal_sha256": sha((root / "SELECTION_SEAL.json").read_bytes()),
        "reproduction_plan_sha256": env["reproduction_plan_sha256"],
        "checkpoints_verified": len(checkpoints),
        "contexts_verified": len(refs),
        "training_receipts_verified": len(training),
        "costs": costs,
        "confirmation_artifacts_present": False,
        "confirmation_streams_generated": False,
        "actual_executables_checked": binaries is not None,
        "independent_new_samples": False,
    }


def audit_run(study, binaries=None, repository=REPOSITORY):
    root = Path(study).resolve()
    env = verify_frozen(root, binaries, repository)
    for phase in (
        "INITIALIZED",
        "TRAINING_STARTED",
        "TRAINING_COMPLETE",
        "CONFIRMATION_COMPLETE",
    ):
        verify_marker(root, phase)
    external = read_json(root, "EXTERNAL_SELECTION.json")
    verify_publication(
        external["selection_commit"],
        SELECTION_PATH,
        (root / "SELECTION_SEAL.json").read_bytes(),
        repository,
    )
    result = original_audit(root, repository)
    result["reproduction"] = {
        "schema": "hepta.boundary-policy-reproduction.identity-audit.v1",
        "original_source_seal_sha256": OLD_SEAL_SHA,
        "reproduction_plan_sha256": env["reproduction_plan_sha256"],
        "source_publication_commit": env["publication_commit"],
        "selection_publication_commit": external["selection_commit"],
        "actual_executables_checked": binaries is not None,
        "independent_new_samples": False,
        "pool_with_original_results": False,
        "original_result_replaced": False,
        "original_benefit_gates": "0/4",
        "mathematical_auditor": "unchanged original continuous_boundary_policy.audit.audit_run",
    }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["preconfirmation", "confirmation"])
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--native-binary", type=Path)
    parser.add_argument("--score-binary", type=Path)
    args = parser.parse_args()
    require(
        not args.output.resolve().is_relative_to(args.study.resolve()),
        "Audit report must be outside immutable raw study",
    )
    require(not args.output.exists(), "Audit report already exists")
    require(
        (args.native_binary is None) == (args.score_binary is None),
        "Supply both binaries or audit source-bound evidence offline",
    )
    binaries = (
        None
        if args.native_binary is None
        else {"native": args.native_binary, "score": args.score_binary}
    )
    result = (
        preconfirmation(args.study, binaries)
        if args.phase == "preconfirmation"
        else audit_run(args.study, binaries)
    )
    save_json(args.output, result)
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "output": str(args.output),
                "sha256": sha(args.output.read_bytes()),
            }
        )
    )


if __name__ == "__main__":
    main()
