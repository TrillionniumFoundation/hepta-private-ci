"""Audit retained raw population evidence independently of experiment scoring.

This audit verifies reproducible artifact consistency, not remote attestation of
execution. It never turns a failed research hypothesis into a passed gate."""

import argparse
import json
from pathlib import Path

from population_audit_artifacts import (
    SEEDS,
    _digest,
    _hash,
    _json,
    _read,
    _require,
    _same,
)
from population_audit_claims import _gates as _gates
from population_audit_costs import _costs
from population_audit_reads import _codecs, _final
from population_audit_router import _selection
from population_audit_sources import _baselines, _exact as _exact, _inputs
from population_audit_training import _training


def audit_trial(seed_directory):
    """Raise on inconsistent evidence; return negative hypotheses without error."""
    directory = Path(seed_directory).resolve()
    result = _json(directory / "result.json")
    data = _inputs(directory, result)
    inventory = _json(directory / "raw-evidence-inventory.json")
    for name, row in inventory.items():
        raw = _read(directory / name)
        _require(
            row == {"bytes": len(raw), "sha256": _hash(raw)},
            "retained raw artifact inventory: " + name,
        )
    points, receipts = _training(directory, data, result["training"])
    router = _selection(directory, data, result["selection"], points)
    policies = _final(directory, data, result["selection"], result["final"], router)
    _codecs(directory, data, result["training"], policies["single"], result["codec"])
    _baselines(directory, data, result["baseline"])
    _costs(directory, result, points, receipts)
    _gates(result)
    return {
        "schema": "hepta.memory-population.independent-audit.v1",
        "seed": result["seed"],
        "passed": True,
        "result_sha256": _hash(_read(directory / "result.json")),
        "raw_files_verified": len(inventory),
        "research_gates": result["research_gates"],
        "general_memory_proven": False,
        "scope": "artifact consistency and independent raw-result reconstruction; no remote execution attestation",
    }


def audit_population(output_root):
    root = Path(output_root).resolve()
    present = sorted(
        int(p.name[5:])
        for p in root.glob("seed-*")
        if p.is_dir() and p.name[5:].isdigit()
    )
    _same(present, list(SEEDS), "exactly all registered seeds, no cherry-picking")
    audits = [audit_trial(root / f"seed-{seed}") for seed in SEEDS]
    results = [_json(root / f"seed-{seed}/result.json") for seed in SEEDS]
    aggregate = _json(root / "aggregate.json")
    _same(aggregate["seeds"], list(SEEDS), "aggregate complete seed cohort")
    _require(
        len({r["protocol_sha256"] for r in results}) == 1
        and len({_digest(r["source_identity"]) for r in results}) == 1,
        "single frozen source and complete runtime identity across seeds",
    )
    mean_gain = sum(r["summary"]["split_retention_gain"] for r in results) / 3
    all_engineering = all(all(r["engineering_gates"].values()) for r in results)
    every = lambda key: all(r["research_gates"][key] is True for r in results)
    split = (
        all_engineering
        and mean_gain >= 0.05 - 1e-12
        and all(
            every(k)
            for k in (
                "parent_source_quality",
                "split_preserves_parent_correct_semantic",
                "parent_final_quality",
                "split_preserves_parent_correct_final_semantic",
                "split_retention_nonnegative",
            )
        )
    )
    router = all_engineering and all(
        every(k)
        for k in (
            "router_supported_coverage",
            "router_eligible_oracle_quality",
            "router_eligible_oracle_regret",
            "router_beats_expected_uniform_random",
            "router_raw_ood_rejection",
        )
    )
    claims = {
        "matched_budget_fission_advantage": split,
        "bounded_learned_router_vs_random": router,
        "learned_router_advantage_over_metadata": router
        and every("router_beats_metadata_capability"),
        "int8_checkpoint_storage_and_quality": all_engineering
        and every("int8_storage_and_quality"),
        "bounded_heterogeneous_retention": all_engineering
        and every("selected_heterogeneous_retention"),
        "bounded_heterogeneous_transfer": all_engineering
        and every("selected_heterogeneous_transfer"),
        "net_memory_compression_advantage": all_engineering
        and every("net_compression_advantage"),
        "general_memory": False,
    }
    _same(
        aggregate["claim_gates"],
        claims,
        "all aggregate claims independently reconstructed",
    )
    _same(
        aggregate["per_seed"],
        [
            {
                "seed": r["seed"],
                "summary": r["summary"],
                "engineering_gates": r["engineering_gates"],
                "research_gates": r["research_gates"],
            }
            for r in results
        ],
        "no omitted or altered failed seed",
    )
    _same(
        aggregate["engineering_passed"], all_engineering, "aggregate engineering gates"
    )
    _same(
        aggregate["mean_split_retention_gain"], mean_gain, "registered mean split gain"
    )
    _require(
        aggregate["negative_outcomes_retained"] is True
        and aggregate["total_optimizer_updates"] == 7680
        and aggregate["all_claims_passed"] is False
        and aggregate["finite_suite_cannot_certify_general_memory"] is True,
        "failed claims retained across the full cohort",
    )
    return {
        "schema": "hepta.memory-population.independent-cohort-audit.v1",
        "passed": True,
        "seeds": list(SEEDS),
        "trials": audits,
        "claim_gates": claims,
        "aggregate_sha256": _hash(_read(root / "aggregate.json")),
        "general_memory_proven": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--single", action="store_true")
    args = parser.parse_args()
    report = audit_trial(args.root) if args.single else audit_population(args.root)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(report, sort_keys=True))
