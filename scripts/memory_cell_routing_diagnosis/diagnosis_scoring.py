"""Post-read diagnostics: raw controls, capability scoring and cost scope."""

from collections import Counter

from diagnosis_common import digest


def routed_rows(probes, raw, versions, capabilities, routes):
    from population_scoring import assess_probe

    rows = []
    for index, (probe, route) in enumerate(zip(probes, routes, strict=True)):
        slot = route["slot"]
        if slot is not None and (type(slot) is not int or slot not in (0, 1)):
            raise ValueError("invalid frozen expert route")
        generated, version = (
            (None, None) if slot is None else (raw[slot][index], versions[slot])
        )
        rows.append(
            {
                **assess_probe(probe, generated, version, capabilities),
                "slot": slot,
                "route_reason": route["reason"],
            }
        )
    return rows


def route_diagnostics(probes, scored, expert_scored):
    """Target classes are diagnostic, calculated after actual raw generations."""
    from population_scoring import GROUPS

    result = {}
    for group, families in GROUPS.items():
        indices = [
            i
            for i, p in enumerate(probes)
            if families is None or p["family"] in families
        ]
        confusion, reasons = Counter(), Counter()
        available = hit = routed = admitted = 0
        for index in indices:
            probe, row = probes[index], scored[index]
            winners = [
                slot
                for slot in range(2)
                if expert_scored[slot][index]["supported_correct"]
            ]
            target = "reject" if not winners else "+".join(map(str, winners))
            chosen = "reject" if row["slot"] is None else str(row["slot"])
            confusion[f"target={target};chosen={chosen}"] += 1
            reasons[row["route_reason"]] += 1
            if probe["family"] != "unknown":
                available += bool(winners)
                hit += row["slot"] in winners
            routed += row["slot"] is not None
            admitted += row["slot"] is not None and row["capability_allowed"]
        result[group] = {
            "total": len(indices),
            "routed": routed,
            "capability_admitted": admitted,
            "oracle_correct_available": available,
            "oracle_correct_selected": hit,
            "oracle_correct_selection_rate": hit / available if available else None,
            "target_route_confusion": dict(sorted(confusion.items())),
            "reasons": dict(sorted(reasons.items())),
        }
    return result


def expert_scores(probes, raw, versions, capabilities):
    from population_scoring import assess_probe

    questions = [probe["question"] for probe in probes]
    if any([row["question"] for row in rows] != questions for rows in raw):
        raise ValueError("fresh raw output panel alignment mismatch")
    return [
        [
            assess_probe(probe, generated, version, capabilities)
            for probe, generated in zip(probes, rows, strict=True)
        ]
        for rows, version in zip(raw, versions, strict=True)
    ]


def score_source(probes, raw, versions, capabilities, source_routes):
    from population_scoring import summarize_rows

    expert_scored = expert_scores(probes, raw, versions, capabilities)
    policies = {}
    for name, routes in source_routes.items():
        rows = routed_rows(probes, raw, versions, capabilities, routes)
        policies[name] = {
            "metrics": summarize_rows(rows),
            "routing": route_diagnostics(probes, rows, expert_scored),
            "by_wording": {
                str(wording): summarize_rows(
                    [
                        row
                        for probe, row in zip(probes, rows, strict=True)
                        if probe["wording"] == wording
                    ]
                )
                for wording in range(4)
            },
        }
    return {
        "policies": policies,
        "training_observation_diagnostics_only": True,
        "nearest_controls_include_self_prototypes": True,
        "independent_test_set": False,
        "questions_sha256": digest([p["question"] for p in probes]),
    }


def score_final(probes, split_raw, single_raw, versions, capabilities, plan):
    from population_scoring import assess_probe, summarize_rows

    if [p["question"] for p in probes] != [p["question"] for p in plan["rows"]]:
        raise ValueError("frozen route plan differs from final probes")
    if [p["question"] for p in probes] != [r["question"] for r in single_raw]:
        raise ValueError("single control raw outputs differ from final probes")
    expert_scored = expert_scores(probes, split_raw, versions["split"], capabilities)
    names = tuple(plan["rows"][0]["routes"])
    policies = {}
    for name in names:
        routes = [row["routes"][name] for row in plan["rows"]]
        rows = routed_rows(probes, split_raw, versions["split"], capabilities, routes)
        guarded = [
            {
                "slot": row["guarded_slots"][name],
                "reason": row["routes"][name]["reason"]
                if row["guarded_slots"][name] is not None
                else "metadata_guard_abstention",
            }
            for row in plan["rows"]
        ]
        guarded_rows = routed_rows(
            probes, split_raw, versions["split"], capabilities, guarded
        )
        policies[name] = {
            "rows": rows,
            "metrics": summarize_rows(rows),
            "guarded_metrics": summarize_rows(guarded_rows),
            "routing": route_diagnostics(probes, rows, expert_scored),
            "guarded_dispatch_executed": False,
        }
    rows = [
        assess_probe(probe, raw, versions["single"][0], capabilities)
        for probe, raw in zip(probes, single_raw, strict=True)
    ]
    policies["single"] = {"rows": rows, "metrics": summarize_rows(rows)}
    for policy in ("oracle", "uniform"):
        rows = []
        for index, probe in enumerate(probes):
            if probe["family"] == "unknown":
                continue
            actual = [expert[index] for expert in expert_scored]
            correct = [row["supported_correct"] for row in actual]
            raw = [row["raw_correct"] for row in actual]
            value = max(correct) if policy == "oracle" else sum(correct) / 2
            rows.append(
                {
                    "probe_id": probe["probe_id"],
                    "family": probe["family"],
                    "correct": value,
                    "supported_correct": value,
                    "raw_correct": max(raw) if policy == "oracle" else sum(raw) / 2,
                    "action_abstained": False,
                    "decoder_unknown": False,
                    "actual_supported_expert_correct": correct,
                    "evaluation_only": True,
                }
            )
        policies[policy] = {
            "rows": rows,
            "metrics": summarize_rows(rows),
            "used_for_selection_or_routing": False,
            "all_metric_denominator_is_known_only": True,
            "unknown_metric_not_applicable": True,
            "uniform_is_exact_two_expert_expectation": policy == "uniform",
        }
    differences = {}
    for name in names:
        differences[name] = {}
        for cohort in ("known", "retention", "transfer", "unknown"):
            value = policies[name]["metrics"][cohort]["accuracy"]
            differences[name][cohort] = {
                "vs_original_percentage_points": 100
                * (value - policies["original"]["metrics"][cohort]["accuracy"]),
                "vs_single_percentage_points": 100
                * (value - policies["single"]["metrics"][cohort]["accuracy"]),
            }
    return {
        "policies": policies,
        "expert_scored": expert_scored,
        "paired_differences": differences,
        "final_cohort_previously_exposed": True,
        "new_final_decoder_outputs": True,
        "all_expert_outputs_computed_for_diagnosis": True,
        "live_dispatch_executed": False,
        "oracle_used_for_selection_or_routing": False,
        "confirmation": False,
        "source_dependency_groups_per_seed": 28,
        "wording_rows_are_correlated": True,
        "statistical_independence_across_seeds_or_groups_established": False,
        "comparable_policy_cohorts": ["known", "retention", "transfer"],
        "all_denominators": {
            name: value["metrics"]["all"]["total"] for name, value in policies.items()
        },
        "source_authority": "pinned local research fixture, not HNMF admission",
        "scientific_phase3_closed": False,
        "production_accepted": False,
    }


def added_costs(read_receipts, feature_receipt, routing_costs, elapsed, cpu):
    reads = [receipt["cost"] for receipt in read_receipts]
    sums = {
        key: sum(row[key] for row in reads)
        for key in (
            "queries",
            "input_tokens",
            "generated_tokens",
            "generation_seconds",
            "wall_seconds",
            "fresh_processes",
        )
    }
    for key in ("parent_cpu_seconds", "child_cpu_seconds"):
        sums[key] = (
            None
            if any(row[key] is None for row in reads)
            else sum(row[key] for row in reads)
        )
    fits = {
        name: routing_costs["receipts"][name] for name in ("full_cross", "balanced")
    }
    return {
        "scope": "additional diagnosis event; historical training and prior diagnosis excluded here",
        "decoder_reads": sums,
        "parent_features": {
            key: feature_receipt[key]
            for key in (
                "model_forwards",
                "input_tokens",
                "forward_seconds",
                "wall_seconds",
                "bytes",
                "shape",
                "parent_cpu_seconds",
                "child_cpu_seconds",
                "optimizer_updates",
                "feature_worker_processes",
                "worker_process_exited",
                "worker_cost",
            )
        },
        "router_fit_optimizer_updates": sum(
            value["training"]["optimizer_updates"] for value in fits.values()
        ),
        "router_fit_wall_seconds": sum(
            value["wall_seconds"] for value in fits.values()
        ),
        "router_fit_parent_cpu_seconds": sum(
            value["parent_cpu_seconds"] for value in fits.values()
        ),
        "routing_work": routing_costs,
        "decoder_optimizer_updates": 0,
        "new_gradient_probes": 0,
        "whole_seed_wall_seconds": elapsed,
        "whole_seed_cpu": cpu,
        "stage_wall_costs_overlap_whole_seed_wall": True,
        "parent_features_not_decoder_queries": True,
        "all_diagnostic_reads_charged_once_not_once_per_policy": True,
        "per_policy_total_budget_matched": False,
        "equal_total_budget": False,
        "fresh_processes_include_model_load_and_validation": True,
    }
