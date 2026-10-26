"""Fixed historical DEV pairing and externally pinned confirmation-entry rule."""

from itertools import product
import numpy as np

from remaining_audit_core_v8 import METHODS, require


CANDIDATE = "terminal_field8_remaining"
AXES = (("v5", "v6"), ("agnews", "dbpedia"), ("linear", "gated"), (7, 17, 29))


def validate_entry(rule, report):
    require(rule["schema"] == "hepta.remaining-terminal-confirmation-entry-rule.v8" and rule["status"] == "FROZEN"
        and rule["control_protocol_sha256"] == report["protocol_sha256"]
        and rule["control_source_sha256"] == report["source_sha256"]
        and rule["control_execution_commit"] == report["source_commit"]
        and rule["declared_candidate"] == CANDIDATE and rule["required_methods"] == list(METHODS)
        and rule["mandatory_complete_slots"] == 96 and rule["required_complete_fits_per_method"] == 24
        and rule["all_actual_errors_disqualify"] is True
        and rule["all_saved_states_actions_receipts_and_anchor_losses_must_replay"] is True
        and rule["full_field_reference"] == {"fits": 24, "require_complete32": True,
            "maximum_action_state_old_loss_difference": 1e-10}, "original fixed source, census and parity entry rule")
    rules = rule["development_plausibility"]
    require(rules["future_loss_candidate_minus_each_comparator"] == {
        "comparators": ["myopic_h1", "loss2_remaining"], "version_task_head_groups": 8,
        "required_group_comparisons": 16, "mean_upper_bound": -.006}
        and rules["old_loss_candidate_minus_original_warmup"] == {"version_task_head_groups": 8, "mean_upper_bound": -.020}
        and rules["candidate_over_myopic_policy_cpu"]["version_task_head_groups"] == 8
        and rules["candidate_over_myopic_policy_cpu"]["maximum_ratio"] == 3,
        "unchanged conservative historical-development margins and whole-policy cost")
    require(rule["unchanged_future_scientific_requirements"] == {"primary_comparisons": 12,
        "one_sided_family_alpha": .05, "future_loss_upper_confidence_bound_strictly_below": -.001,
        "old_loss_upper_confidence_bound_at_most": 0, "maximum_candidate_over_myopic_policy_cpu_ratio": 3,
        "all_required_primary_trajectories_complete32": True, "component_identity_and_role_disjointness_required": True}
        and rule["no_posthoc_threshold_or_cohort_relaxation"] is True
        and rule["no_additional_configuration_search_in_this_study"] is True
        and rule["scientific_acceptance"] is False and rule["production_authority"] is False,
        "development entry must not replace original scientific approval")


def summarize(records, arrays, parities):
    keys = [(*fit, m) for fit in product(*AXES) for m in METHODS]
    by_key = {(r["version"], r["task"], r["head"], r["seed"], r["method"]): r for r in records}
    require(len(records) == len(by_key) == 96 and set(by_key) == set(keys), "exact96 DEV policy slots including every stop/error")
    for row in records:
        if row["available"]:
            for role in ("future", "old"):
                values = arrays[row["array_keys"][role+"_nll"]]
                require(values.shape == (512,) and np.isfinite(values).all(), "512 original paired source losses")
        if row["complete32"]:
            require(row["available"] and row["status"] == "completed" and row["completed_steps"] == 32
                and not row["actual_errors"] and type(row["cpu_ns"]) is int and row["cpu_ns"] > 0,
                "complete32 cannot be inferred from a partial terminal score")
    groups = []
    for v, t, h in product(*AXES[:3]):
        group = {"version": v, "task": t, "head": h, "policies": [], "future": []}
        policy_rows = {m: [by_key[v, t, h, s, m] for s in AXES[3]] for m in METHODS}
        ready = {m: all(r["complete32"] for r in rows) for m, rows in policy_rows.items()}
        identities = {r["selection_sources_sha256"] for rows in policy_rows.values() for r in rows}
        require(len(identities) == 1 and None not in identities, "all methods and three seeds pair identical ordered source roles")
        for method, rows in policy_rows.items():
            item = {"method": method, "complete_seeds": sum(r["complete32"] for r in rows),
                "available_prefixes": sum(r["available"] for r in rows), "available32": ready[method]}
            if ready[method]:
                for role in ("future", "old"):
                    item[role+"_nll"] = float(np.mean([r[role]["nll"] for r in rows]))
                    item[role+"_accuracy"] = float(np.mean([r[role]["accuracy"] for r in rows]))
                item["cpu_ns"] = sum(r["cpu_ns"] for r in rows)
            group["policies"].append(item)
        candidate = policy_rows[CANDIDATE]
        for baseline in ("myopic_h1", "loss2_remaining"):
            comparison = {"baseline": baseline, "available32": ready[CANDIDATE] and ready[baseline],
                "mean_difference": None, "passes_dev_margin": False}
            if comparison["available32"]:
                delta = np.stack([arrays[a["array_keys"]["future_nll"]]-arrays[b["array_keys"]["future_nll"]]
                    for a, b in zip(candidate, policy_rows[baseline], strict=True)])
                mean = float(delta.mean(axis=0).mean())
                comparison.update(mean_difference=mean, paired_seed_means=delta.mean(axis=1).tolist(),
                    paired_seed_sample_sd=float(np.std(delta.mean(axis=1), ddof=1)), sources=512,
                    passes_dev_margin=mean <= -.006)
            group["future"].append(comparison)
        old = {"available32": ready[CANDIDATE], "mean_difference": None, "passes_dev_margin": False}
        if ready[CANDIDATE]:
            delta = np.stack([arrays[r["array_keys"]["old_nll"]]-arrays[r["warmup_old_nll_key"]] for r in candidate])
            mean = float(delta.mean(axis=0).mean())
            old.update(mean_difference=mean, paired_seed_means=delta.mean(axis=1).tolist(),
                paired_seed_sample_sd=float(np.std(delta.mean(axis=1), ddof=1)), passes_dev_margin=mean <= -.020)
        group["old_vs_original_warmup"] = old
        group["candidate_h1_cpu_ratio"] = None
        group["candidate_full_cpu_ratio"] = None
        for baseline, label in (("myopic_h1", "h1"), ("full_adjoint_remaining", "full")):
            if ready[CANDIDATE] and ready[baseline]:
                group["candidate_"+label+"_cpu_ratio"] = sum(r["cpu_ns"] for r in candidate)/sum(r["cpu_ns"] for r in policy_rows[baseline])
        group["passes_cost"] = group["candidate_h1_cpu_ratio"] is not None and group["candidate_h1_cpu_ratio"] <= 3.
        group["all_four_methods_complete32"] = all(ready.values())
        groups.append(group)
    expected_fits = {f"{v}-{t}-seed{s}-{h}" for v, t, h, s in product(*AXES)}
    require(len(parities) == 24 and {r["fit"] for r in parities} == expected_fits, "all24 registered Full/field parity records")
    parity_pass = all(r["complete"] and r["passed"] and all(r["max_"+k+"_difference"] <= 1e-10
        for k in ("states", "actions", "old_losses")) for r in parities)
    counts = {"complete32_slots": sum(r["complete32"] for r in records),
        "actual_error_slots": sum(bool(r["actual_errors"]) for r in records),
        "future_dev_margin_passes": sum(c["passes_dev_margin"] for g in groups for c in g["future"]),
        "old_dev_margin_passes": sum(g["old_vs_original_warmup"]["passes_dev_margin"] for g in groups),
        "cost_group_passes": sum(g["passes_cost"] for g in groups), "full_field_parity_passed": parity_pass}
    enter = (counts["complete32_slots"] == 96 and counts["actual_error_slots"] == 0 and parity_pass
        and counts["future_dev_margin_passes"] == 16 and counts["old_dev_margin_passes"] == 8 and counts["cost_group_passes"] == 8)
    return {"groups": groups, "counts": counts, "confirmation_entry_passed": enter,
        "disposition": "ELIGIBLE_TO_PREPARE_SEPARATE_CONFIRMATION" if enter else "REJECT_FOR_CONFIRMATION",
        "new_confirmation_consumed": False, "scientific_acceptance": False, "native_admission": False,
        "scope": "paired means of three seeds on disclosed historical512-component roles; development screen only, no confidence-interval or population guarantee"}
