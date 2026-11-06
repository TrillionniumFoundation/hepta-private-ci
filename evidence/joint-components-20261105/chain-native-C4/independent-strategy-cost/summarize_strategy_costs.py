#!/usr/bin/env python3
"""Derive finite-cohort comparisons from independent raw accounting.

This reads only the locally produced independent accounting and saved original
receipts. It never executes the original reader or any native measurement.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPORT = HERE / "independent-strategy-recomputation.json"
ROOT = HERE.parents[1]
RAW = ROOT / "w1/C4-strategy-receipts"
AXES = ("cpu_ns", "wall_ns")


def ratio(a, b):
    return dict(numerator=a, denominator=b, value=a/b) if b else None


def phases(rows, field):
    return {axis: sum(row[field][axis] for row in rows) for axis in AXES}


def table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(str(cell) for cell in row) + " |" for row in rows)
    return "\n".join(lines)


def scientific_ns(value, unit):
    return f"{value / unit:.6f}"


def main():
    report_bytes = REPORT.read_bytes()
    r = json.loads(report_bytes)
    totals, legal_rows, attack_rows, reused_rows, repeated = {}, [], [], [], []
    for family in ("legal", "reused", "false"):
        rows = [row for part in r[family]["reports"] for row in part["costs"]]
        verifies = {axis: sum(value["total"][axis] for row in rows for paths in row["verification"].values() for value in paths.values()) for axis in AXES}
        totals[family] = dict(actual_setup_calls=sum(x["actual_setup_calls"] for x in rows),
            actual_searches=sum(x["actual_searches"] for x in rows), nonce_attempts=sum(x["attempts"] for x in rows),
            target_hits_in_repeated_arm_observations=sum(x["target_hits"] for x in rows),
            failed_nonce_attempts=sum(x["failed_nonce_attempts"] for x in rows),
            exhausted_searches=sum(x["exhausted_searches"] for x in rows),
            material_generation_separate={axis:sum(s["material_setup"][axis] for s in r[family]["reports"]) for axis in AXES},
            setup=phases(rows,"setup"), search=phases(rows,"search"), inclusive_total=phases(rows,"inclusive_total"),
            inclusive_residual=phases(rows,"inclusive_residual"), verification_all_labels_and_cases=verifies,
            unsupported_cohorts=sum(x["actual_setup_calls"] for x in rows if not x["supported"]),
            unsupported_setup=phases([x for x in rows if not x["supported"]],"setup"),
            supported_cohorts=sum(x["actual_setup_calls"] for x in rows if x["supported"]),
            semantic_alerts=sum(len(s["semantic_alerts"]) for s in r[family]["reports"]),
            timing_aggregate_scope="sum of recorded repeated benchmark intervals, not independently credited work or live traffic")
        if family == "legal":
            totals[family].update(separate_evidence=phases(rows,"separate_evidence"),
                                  separate_product_mutation=phases(rows,"separate_mutation"),
                                  proof_materializations=sum(x["proof_materializations"] for x in rows),
                                  materialized_proof_bytes=sum(x["serialized_proof_bytes"] for x in rows))
        execution = r["execution_bindings"][family]
        assert execution["source_before"] == execution["source_after"] == {
            "commit": r["source_commit"], "tree": r["source_tree"], "source_state": "committed-clean",
            "tracked_bytes": 985270534, "tracked_entries": 10357, "tracked_worktree_verified": True}
        assert execution["build_profile"] == "release" and execution["architecture"] == "x64"
        assert execution["target"] == "x86_64-unknown-linux-gnu"
        assert execution["cargo_configuration_before"] == execution["cargo_configuration_after"]
        observations = execution["observations"]
        assert all(x["exit_code"] == 0 and x["timed_out"] is False for x in observations)
        builds = [x for x in observations if x["command"][:3] == ["cargo", "+1.95.0", "build"]]
        native = [x for x in observations if Path(x["command"][0]).name.startswith("pon_w1_")]
        assert len(builds)==1 and builds[0]["timeout_seconds"]==900 and "--locked" in builds[0]["command"] and "--release" in builds[0]["command"]
        assert len(native)==(30 if family=="legal" else 1) and all(x["timeout_seconds"]==300 for x in native)
        totals[family]["outer_native_process_elapsed"] = dict(sum_ns=sum(x["elapsed_ns"] for x in native), minimum_ns=min(x["elapsed_ns"] for x in native), maximum_ns=max(x["elapsed_ns"] for x in native), original_per_child_timeout_seconds=300)
        totals[family]["original_build_elapsed_ns"] = builds[0]["elapsed_ns"]
    for shard in r["legal"]["reports"]:
        costs=shard["costs"]
        byarm={c["arm"]:c for c in costs}
        best=min(costs,key=lambda c:c["inclusive_total"]["cpu_ns"])
        base=byarm["eager-transposed"]
        item=dict(shard["selection"], observed_best_fixed_arm=best["arm"],
            selection="retrospective one supplied arm for all eight cohorts; no per-search oracle or holdout claim",
            setup_calls=8, searches=best["actual_searches"], nonce_attempts=best["attempts"], misses=best["failed_nonce_attempts"],
            target_hits=best["target_hits"], setup=best["setup"], search=best["search"], inclusive_total=best["inclusive_total"],
            inclusive_cpu_per_nonce_ns=best["per_attempt"]["cpu_ns"], inclusive_wall_per_nonce_ns=best["per_attempt"]["wall_ns"],
            inclusive_cpu_per_hit_ns=best["per_target_hit"]["cpu_ns"], baseline_cpu_over_best=ratio(base["inclusive_total"]["cpu_ns"],best["inclusive_total"]["cpu_ns"]),
            paired_factorial_ratios={}, setup_fraction_cpu=best["setup"]["cpu_ns"]/best["inclusive_total"]["cpu_ns"])
        for label,a,b in [
            ("eager_transposed_over_lazy_transposed","eager-transposed","lazy-transposed"),
            ("eager_full_limb_over_lazy_full_limb","eager-full-limb","lazy-full-limb"),
            ("transposed_over_full_limb_eager","eager-transposed","eager-full-limb"),
            ("transposed_over_full_limb_lazy","lazy-transposed","lazy-full-limb")]:
            item["paired_factorial_ratios"][label]=ratio(byarm[a]["inclusive_total"]["cpu_ns"],byarm[b]["inclusive_total"]["cpu_ns"])
        # This is the preexisting-winner case: acquisition and marginal mutation
        # are kept as two explicit denominators, never equated.
        for cost in costs:
            prod=cost["verification"]["product-last"]["production"]["total"]["cpu_ns"]
            mut=cost["separate_mutation"]["cpu_ns"]
            repeated.append(dict(shard["selection"], arm=cost["arm"], observed_candidates=cost["target_hits"],
                mutation_cpu_ns=mut, product_rejection_cpu_ns=prod, original_producer_cpu_ns=cost["inclusive_total"]["cpu_ns"],
                production_rejection_over_mutation_only=ratio(prod,mut),
                production_rejection_over_this_honest_acquisition_plus_mutation=ratio(prod,cost["inclusive_total"]["cpu_ns"]+mut),
                valid_proof_prerequisite=True, acquisition_is_not_an_adversarial_lower_bound=True))
        legal_rows.append(item)
    reused=r["reused"]["reports"][0]["costs"]
    names=list(dict.fromkeys(x["class_name"] for x in reused))
    old=json.loads((RAW/"reused-v3/original/w1-actual-reuse-v3/manifest.json").read_text())["reader"]
    for name in names:
        costs=[c for c in reused if c["class_name"]==name]
        supported=[c for c in costs if c["supported"]]
        assert all(c["actual_searches"]==c["target_hits"]==32 and all(v["outcomes"]=={"Accepted":32} for v in c["verification"]["legal"].values()) for c in supported)
        best=min(supported,key=lambda c:c["inclusive_total"]["cpu_ns"])
        generic=next(c for c in supported if c["arm"]=="prepared-generic")
        reference=next(row for row in old["fixed_cohort_comparison"] if row["class"]==name)
        assert reference["all_supported_arms_measured"] is True and reference["lowest_observed_supplied_cohort_arm"]==best["arm"] and reference["actual_eight_cohorts_cpu_ns"]==best["inclusive_total"]["cpu_ns"]
        reused_rows.append(dict(class_name=name, horizon=4, target_index=0,
            observed_best_fixed_arm=best["arm"], supported_arms=len(supported), unsupported_arms=len(costs)-len(supported),
            setup_calls=8, searches=32, nonce_attempts=best["attempts"], misses=best["failed_nonce_attempts"],
            setup=best["setup"], search=best["search"], inclusive_total=best["inclusive_total"],
            inclusive_cpu_per_nonce_ns=best["per_attempt"]["cpu_ns"], inclusive_wall_per_nonce_ns=best["per_attempt"]["wall_ns"],
            inclusive_cpu_per_hit_ns=best["per_target_hit"]["cpu_ns"], generic_over_best_cpu=ratio(generic["inclusive_total"]["cpu_ns"],best["inclusive_total"]["cpu_ns"]),
            setup_fraction_cpu=best["setup"]["cpu_ns"]/best["inclusive_total"]["cpu_ns"],
            selection="retrospective one supplied arm over eight H4 cohorts, not per-search oracle; not directly paired with legal-v3 or Sparse census"))
    for cost in r["false"]["reports"][0]["costs"]:
        paths=cost["verification"]["from-zero"]
        assert all(v["outcomes"]=={"Transcript":32} for v in paths.values())
        attack_rows.append(dict(class_name=cost["class_name"], horizon=4, target_index=0, setup_calls=8,
            searches=32, nonce_attempts=cost["attempts"], misses=cost["failed_nonce_attempts"], candidate_count=cost["target_hits"],
            setup=cost["setup"], search=cost["search"], inclusive_attacker_total=cost["inclusive_total"],
            attacker_cpu_per_candidate_ns=cost["per_target_hit"]["cpu_ns"],
            production_reject_cpu_per_candidate_ns=paths["production"]["total"]["cpu_ns"]/32,
            production_reject_median_cpu_ns=paths["production"]["timings"]["cpu_ns"]["median"],
            path_ratios={path:{axis:ratio(v["total"][axis],cost["inclusive_total"][axis]) for axis in AXES} for path,v in paths.items()},
            production_rejection=paths["production"]["total"],
            setup_fraction_cpu=cost["setup"]["cpu_ns"]/cost["inclusive_total"]["cpu_ns"],
            candidate_reconstructed_without_legal_proof=True, rejected_before_product_check="Transcript",
            public_service_amplification_measured=False, attacker_lower_bound=False))
    prod=sum(c["production_rejection"]["cpu_ns"] for c in attack_rows)
    full=totals["false"]["inclusive_total"]["cpu_ns"]
    totals["false"]["production_rejection_cpu_over_full_attacker_cpu_equal_class_sum"] = ratio(prod,full)
    totals["false"]["production_rejection_cpu_ns"] = prod
    prod_wall=sum(c["production_rejection"]["wall_ns"] for c in attack_rows)
    material=totals["false"]["material_generation_separate"]
    totals["false"]["production_rejection_wall_ns"] = prod_wall
    totals["false"]["one_shared_material_generation_sensitivity"] = dict(
        allocation="charge the one observed whole-campaign material-generation interval once to all 72 setups / 288 searches; no per-class or per-candidate replication",
        material_generation=material,
        complete_denominator={axis:totals["false"]["inclusive_total"][axis]+material[axis] for axis in AXES},
        production_rejection_over_complete_denominator={
            "cpu_ns":ratio(prod,full+material["cpu_ns"]),
            "wall_ns":ratio(prod_wall,totals["false"]["inclusive_total"]["wall_ns"]+material["wall_ns"])},
        still_excludes="JSONL evidence serialization, enclosing wire/transport envelope and send, live admission, scheduling, queueing, storage, receiver network work, later retained-buffer destruction",
        included_wire_bytes="canonical A/B public proof-prefix serialization during setup and the complete winning-buffer clone inside search are already charged",
        material_generation_is_not_proven_necessary_for_an_attacker_with_a_public_task=True)
    findings=dict(schema="independent-C4-finite-strategy-findings-v1", source_commit=r["source_commit"],source_tree=r["source_tree"],
        independent_raw_report_sha256=hashlib.sha256(report_bytes).hexdigest(), totals=totals,
        legal_fixed_cohort_bests=legal_rows, reused_fixed_cohort_bests=reused_rows,
        from_zero_full_cost_amplification=attack_rows, product_mutation_denominators=repeated,
        legal_cross_horizon_dedup=r["legal"]["cross_horizon_dedup"],
        legal_best_arm_counts=dict(Counter(x["observed_best_fixed_arm"] for x in legal_rows)),
        numerical_summary={
            "legal_best_fixed_arm_cpu_per_nonce_range_ns":[min(c["inclusive_cpu_per_nonce_ns"] for c in legal_rows),max(c["inclusive_cpu_per_nonce_ns"] for c in legal_rows)],
            "legal_eager_transposed_over_observed_best_cpu_range":[min(c["baseline_cpu_over_best"]["value"] for c in legal_rows),max(c["baseline_cpu_over_best"]["value"] for c in legal_rows)],
            "from_zero_production_reject_over_full_attacker_cpu_range":[min(c["path_ratios"]["production"]["cpu_ns"]["value"] for c in attack_rows),max(c["path_ratios"]["production"]["cpu_ns"]["value"] for c in attack_rows)],
            "mutation_only_production_reject_over_mutator_cpu_range":[min(c["production_rejection_over_mutation_only"]["value"] for c in repeated),max(c["production_rejection_over_mutation_only"]["value"] for c in repeated)],
            "factorial_ratio_ranges":{label:[min(c["paired_factorial_ratios"][label]["value"] for c in legal_rows),max(c["paired_factorial_ratios"][label]["value"] for c in legal_rows)] for label in legal_rows[0]["paired_factorial_ratios"]},
        },
        no_native_reexecution=True, no_original_reader_reexecution=True, global_cheapest_bound=False,
        public_service_qualification=False, network_or_hardware_independence=False, qualification_status="HOLD")
    (HERE/"cost-findings.json").write_text(json.dumps(findings,indent=2,sort_keys=True)+"\n")
    lines=["# C4 finite strategy cost tables", "", "All totals below are native **thread CPU** unless the column explicitly says wall. `ms/nonce` divides the complete measured producer cohort, including actual setup and every failed nonce, by all recorded nonces. Arm selection uses one arm over eight samples retrospectively; it is neither a per-attempt oracle nor a future cheapest-work guarantee.", "", "## Legal-v3: 30 matched factorial shards", "", "Target 0 is `7f…ff` (required weight 2); target 1 is `07…ff` (required weight 32). Each row includes eight actual setups and eight × H searches. Shared H prefixes are correlated, not additional independent work.", ""]
    lines.append(table(["Class","Target","H","Observed lowest fixed arm","Nonces / misses","Setup ms","Full CPU ms","Full wall ms","CPU ms/nonce","CPU ms/hit","Eager transposed / best"],
        [[x["class_name"],x["target_index"],x["horizon"],x["observed_best_fixed_arm"],f'{x["nonce_attempts"]} / {x["misses"]}',f'{x["setup"]["cpu_ns"]/1e6:.6f}',f'{x["inclusive_total"]["cpu_ns"]/1e6:.6f}',f'{x["inclusive_total"]["wall_ns"]/1e6:.6f}',f'{x["inclusive_cpu_per_nonce_ns"]/1e6:.6f}',f'{x["inclusive_cpu_per_hit_ns"]/1e6:.6f}',f'{x["baseline_cpu_over_best"]["value"]:.6f}'] for x in legal_rows]))
    lines.extend(["", "## Reused-v3: 13 arms, target 0, actual H4", "", "Each eligible row retains eight setups, 32 searches, all failed nonces and 32 candidates. Unsupported constructor calls are paid observations and excluded from the cheapest legal arm selection. These are different challenge domains and timer scopes from legal-v3; the tables are not a cross-suite speedup experiment.", ""])
    lines.append(table(["Class","Observed lowest fixed arm","Supported / unsupported arms","Nonces / misses","Setup ms","Full CPU ms","Full wall ms","CPU ms/nonce","CPU ms/hit","Generic / best"],
        [[x["class_name"],x["observed_best_fixed_arm"],f'{x["supported_arms"]} / {x["unsupported_arms"]}',f'{x["nonce_attempts"]} / {x["misses"]}',f'{x["setup"]["cpu_ns"]/1e6:.6f}',f'{x["inclusive_total"]["cpu_ns"]/1e6:.6f}',f'{x["inclusive_total"]["wall_ns"]/1e6:.6f}',f'{x["inclusive_cpu_per_nonce_ns"]/1e6:.6f}',f'{x["inclusive_cpu_per_hit_ns"]/1e6:.6f}',f'{x["generic_over_best_cpu"]["value"]:.6f}'] for x in reused_rows]))
    lines.extend(["", "## From-zero false trace: full attacker denominator", "", "Each row measures eight real public-prefix setups, 32 false-trace searches and all losing hash trials. The complete attacker total includes those phases, winner-buffer cloning and retained trial evidence. It does not charge acquisition of a valid proof. Each receiver ratio uses only that one verifier label, not the sum of five labels. `production` and `full-limb-experimental` are two invocations of the same arithmetic kernel.", ""])
    lines.append(table(["Class","Nonces / misses","Setup µs","Search µs","Full attacker CPU µs","Full attacker wall µs","Production rejection CPU ms / 32","Reject / full attacker CPU","Reject / full attacker wall"],
        [[x["class_name"],f'{x["nonce_attempts"]} / {x["misses"]}',f'{x["setup"]["cpu_ns"]/1e3:.3f}',f'{x["search"]["cpu_ns"]/1e3:.3f}',f'{x["inclusive_attacker_total"]["cpu_ns"]/1e3:.3f}',f'{x["inclusive_attacker_total"]["wall_ns"]/1e3:.3f}',f'{x["production_rejection"]["cpu_ns"]/1e6:.6f}',f'{x["path_ratios"]["production"]["cpu_ns"]["value"]:.6f}',f'{x["path_ratios"]["production"]["wall_ns"]["value"]:.6f}'] for x in attack_rows]))
    lines.extend(["", "Raw bindings, all 120 factorial arm totals, all 117 reused class/arm totals, native outcome counts, per-sample denominators, verifier distributions and CPU/wall phase arithmetic are retained in `independent-strategy-recomputation.json`. Every raw stream hash and complete candidate proof was reconstructed locally before comparison with the saved original reader output. No W1 transcript replay or native measurement was performed by this review.", ""])
    (HERE/"cost-tables.md").write_text("\n".join(lines))
    print(json.dumps(dict(numerical_summary=findings["numerical_summary"], totals=totals),indent=2))


if __name__ == "__main__":
    main()
