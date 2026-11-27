"""Independently recompute bounded scientific gates without erasing failures."""

from population_audit_artifacts import _require, _same


def _gates(result):
    final, selection, codec, costs, baseline = (
        result[k] for k in ("final", "selection", "codec", "costs", "baseline")
    )
    metrics, choice = final["metrics"], selection["choice"]
    score = lambda policy, group="retention": metrics[policy][group]["accuracy"]
    split, single, oracle, random, metadata = (
        score(k)
        for k in (
            "split_learned_guarded",
            "single",
            "oracle",
            "uniform_random",
            "split_metadata_only",
        )
    )
    coverage, ood = (
        final["routing"]["supported_retention_coverage"],
        final["routing"]["raw_ood_reject_rate"],
    )
    retention = {k: score("selected", k) for k in ("semantic", "episode", "procedure")}
    transfer = {
        k: score("selected", k)
        for k in ("event_interpolation", "procedure_extrapolation")
    }
    gates = {
        "parent_source_quality": choice["parent_recall_gate"] is True,
        "split_preserves_parent_correct_semantic": choice[
            "parent_correct_semantic_preserved"
        ]["split"]
        is True,
        "parent_final_quality": score("parent", "semantic") >= 0.75,
        "split_preserves_parent_correct_final_semantic": final[
            "parent_correct_semantic_preserved"
        ]["split"]
        is True,
        "split_retention_nonnegative": split - single >= -1e-12,
        "router_supported_coverage": coverage >= 0.75,
        "router_eligible_oracle_quality": oracle >= 0.75,
        "router_eligible_oracle_regret": oracle - split <= 0.05 + 1e-12,
        "router_beats_expected_uniform_random": split - random >= 0.05 - 1e-12,
        "router_beats_metadata_capability": split - metadata >= 0.05 - 1e-12,
        "router_raw_ood_rejection": ood >= 0.90,
        "selected_heterogeneous_retention": all(v >= 0.75 for v in retention.values()),
        "selected_heterogeneous_transfer": all(v >= 0.75 for v in transfer.values()),
        "int8_storage_and_quality": codec["primary_gate_passed"] is True,
        "net_compression_advantage": costs.get(
            "full_system_costs_and_comparable_baseline_accounted"
        )
        is True
        and costs["retained_data_and_model_lower_bound_bytes"]
        < baseline["smallest_complete_exact_representation"]["bytes"]
        and score("selected", "known") >= baseline["typed_operation_exact"],
    }
    _same(
        result["research_gates"],
        gates,
        "negative and positive research gates preserved",
    )
    summary = {
        "chosen_arm": choice["chosen_arm"],
        "single_retention": single,
        "split_retention": split,
        "split_retention_gain": split - single,
        "oracle_retention": oracle,
        "oracle_representation_gain": oracle - single,
        "expected_uniform_random_retention": random,
        "metadata_retention": metadata,
        "router_regret": oracle - split,
        "router_gain_over_random": split - random,
        "router_gain_over_metadata": split - metadata,
        "supported_retention_coverage": coverage,
        "raw_ood_reject_rate": ood,
        "retention_by_family": retention,
        "transfer_by_family": transfer,
    }
    _same(result["summary"], summary, "raw-metric summary")
    engineering = dict.fromkeys(
        (
            "matched_adapter_budget",
            "matched_candidate_updates",
            "parent_unchanged",
            "source_groups_preserved",
            "final_owner_admission",
            "selection_unchanged",
            "selection_preceded_final_reads",
            "exact_typed_baseline",
            "both_precommitted_codecs_measured",
            "source_identity_unchanged",
            "selection_bytes_unchanged_after_codecs",
        ),
        True,
    )
    engineering["router_overhead_within_one_percent"] = choice[
        "router_within_one_percent"
    ]
    _same(result["engineering_gates"], engineering, "raw-verified engineering gates")
    _require(
        result["general_memory_proven"] is False
        and result["production_accepted"] is False,
        "bounded research claims only",
    )
