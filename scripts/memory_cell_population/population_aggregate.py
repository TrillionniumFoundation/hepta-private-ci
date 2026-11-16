"""Fail-closed bounded claims; retain negative research outcomes across all seeds."""

import argparse
import json
import math
from pathlib import Path

SEEDS = (1907, 2719, 4051)


def _accuracy(metrics, arm, group):
    value = metrics[arm][group]["accuracy"]
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise ValueError("finite measured accuracy required")
    return value


def assess_trial(training, selection, final, codec, baseline, costs):
    metrics, choice = final["metrics"], selection["choice"]
    score = lambda arm, group="retention": _accuracy(metrics, arm, group)
    split = score("split_learned_guarded")
    oracle = score("oracle")
    random = score("uniform_random")
    metadata = score("split_metadata_only")
    retention = {
        kind: score("selected", kind) for kind in ("semantic", "episode", "procedure")
    }
    transfer = {
        kind: score("selected", kind)
        for kind in ("event_interpolation", "procedure_extrapolation")
    }
    coverage = final["routing"]["supported_retention_coverage"]
    ood = final["routing"]["raw_ood_reject_rate"]
    if any(
        type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1
        for v in (coverage, ood)
    ):
        raise ValueError("finite measured routing coverage required")
    engineering = {
        "matched_adapter_budget": training["costs"]["same_adapter_budget"] is True,
        "matched_candidate_updates": choice["matched_optimizer_updates"] is True,
        "router_overhead_within_one_percent": choice["router_within_one_percent"]
        is True,
        "parent_unchanged": training["parent_unchanged"] is True,
        "source_groups_preserved": training["source_dependency_groups_preserved"]
        is True,
        "final_owner_admission": final["all_owner_admitted"] is True,
        "selection_unchanged": final["selection_unchanged"] is True,
        "selection_preceded_final_reads": (
            final["chosen_before_final_read"] is True
            and final["chosen_arm"] == choice["chosen_arm"]
        ),
        "exact_typed_baseline": baseline["typed_operation_exact"] == 1,
        "both_precommitted_codecs_measured": set(codec["variants"]) == {"8", "4"},
    }
    router_checks = {
        "router_supported_coverage": coverage >= 0.75,
        "router_eligible_oracle_quality": oracle >= 0.75,
        "router_eligible_oracle_regret": oracle - split <= 0.05 + 1e-12,
        "router_beats_expected_uniform_random": split - random >= 0.05 - 1e-12,
        "router_beats_metadata_capability": split - metadata >= 0.05 - 1e-12,
        "router_raw_ood_rejection": ood >= 0.90,
    }
    net_advantage = False
    if costs.get("full_system_costs_and_comparable_baseline_accounted") is True:
        actual = costs.get("complete_system_storage_bytes")
        exact = baseline.get("complete_equivalent_system_bytes")
        if any(type(value) is not int or value <= 0 for value in (actual, exact)):
            raise ValueError(
                "complete equivalent system bytes required for a positive compression claim"
            )
        net_advantage = (
            actual < exact
            and score("selected", "known") >= baseline["typed_operation_exact"]
        )
    research = {
        "parent_source_quality": choice["parent_recall_gate"] is True,
        "split_preserves_parent_correct_semantic": choice[
            "parent_correct_semantic_preserved"
        ]["split"]
        is True,
        "parent_final_quality": final["parent_semantic_recall"] >= 0.75,
        "split_preserves_parent_correct_final_semantic": final[
            "parent_correct_semantic_preserved"
        ]["split"]
        is True,
        "split_retention_nonnegative": split - score("single") >= -1e-12,
        **router_checks,
        "selected_heterogeneous_retention": all(v >= 0.75 for v in retention.values()),
        "selected_heterogeneous_transfer": all(v >= 0.75 for v in transfer.values()),
        "int8_storage_and_quality": codec["primary_gate_passed"] is True,
        "net_compression_advantage": net_advantage,
    }
    return {
        "engineering_gates": engineering,
        "research_gates": research,
        "summary": {
            "chosen_arm": choice["chosen_arm"],
            "single_retention": score("single"),
            "split_retention": split,
            "split_retention_gain": split - score("single"),
            "oracle_retention": oracle,
            "oracle_representation_gain": oracle - score("single"),
            "expected_uniform_random_retention": random,
            "metadata_retention": metadata,
            "router_regret": oracle - split,
            "router_gain_over_random": split - random,
            "router_gain_over_metadata": split - metadata,
            "supported_retention_coverage": coverage,
            "raw_ood_reject_rate": ood,
            "retention_by_family": retention,
            "transfer_by_family": transfer,
        },
        "general_memory_proven": False,
        "production_accepted": False,
    }


def aggregate(results):
    if (
        type(results) is not list
        or len(results) != 3
        or sorted(r["seed"] for r in results) != list(SEEDS)
    ):
        raise ValueError(
            "exactly the three distinct registered seeds required; missing outcomes cannot be dropped"
        )
    if (
        len({r["protocol_sha256"] for r in results}) != 1
        or len({json.dumps(r["source_identity"], sort_keys=True) for r in results}) != 1
    ):
        raise ValueError(
            "one immutable protocol, source implementation and runtime identity required"
        )
    results = sorted(results, key=lambda r: r["seed"])
    mean_gain = sum(r["summary"]["split_retention_gain"] for r in results) / len(
        results
    )
    all_engineering = all(all(r["engineering_gates"].values()) for r in results)
    every = lambda key: all(r["research_gates"][key] is True for r in results)
    split_pass = (
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
    routing = (
        "router_supported_coverage",
        "router_eligible_oracle_quality",
        "router_eligible_oracle_regret",
        "router_beats_expected_uniform_random",
        "router_raw_ood_rejection",
    )
    bounded_router = all_engineering and all(every(k) for k in routing)
    claims = {
        "matched_budget_fission_advantage": split_pass,
        "bounded_learned_router_vs_random": bounded_router,
        "learned_router_advantage_over_metadata": bounded_router
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
    return {
        "schema": "hepta.memory-population.aggregate.v1",
        "seeds": list(SEEDS),
        "protocol_sha256": results[0]["protocol_sha256"],
        "source_identity": results[0]["source_identity"],
        "engineering_passed": all_engineering,
        "claim_gates": claims,
        "mean_split_retention_gain": mean_gain,
        "per_seed": [
            {
                "seed": r["seed"],
                "summary": r["summary"],
                "engineering_gates": r["engineering_gates"],
                "research_gates": r["research_gates"],
            }
            for r in results
        ],
        "total_optimizer_updates": sum(
            r["training"]["costs"]["total_optimizer_updates"] for r in results
        ),
        "negative_outcomes_retained": True,
        "all_claims_passed": all(claims.values()),
        "finite_suite_cannot_certify_general_memory": True,
        "production_accepted": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, nargs=3, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = aggregate([json.loads(p.read_text()) for p in args.results])
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(value, sort_keys=True, allow_nan=False))
