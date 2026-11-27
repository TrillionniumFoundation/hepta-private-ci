#!/usr/bin/env python3
"""Offline arithmetic audit of already published outcomes; no training or new acceptance.

Reads retained evidence and pinned local Git objects. It does not import project/model
code, access a network, change a model, select a policy or expose a fresh holdout.
"""

import collections
import gzip
import subprocess
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def input_bytes(path):
    if path.is_file():
        return path.read_bytes()
    specification = json.loads((ROOT / "EVIDENCE_INPUTS.json").read_text())[path.name]
    packed = subprocess.check_output([
        "git", "-C", str(ROOT), "show", specification["ref"] + ":" + specification["path"]])
    assert hashlib.sha256(packed).hexdigest() == specification["stored_sha256"]
    raw = gzip.decompress(packed) if specification["decode_gzip"] else packed
    assert len(raw) == specification["bytes"]
    assert hashlib.sha256(raw).hexdigest() == specification["sha256"]
    return raw


def read(name):
    return json.loads(input_bytes(ROOT / name))


def sha(path):
    return hashlib.sha256(input_bytes(path)).hexdigest()


def mean(values):
    return math.fsum(values) / len(values)


def verify_evolution_inputs():
    inventory = read("evolution-inventory.json")
    verified = {}
    for original, local in [("prediction_ledger.json", "evolution-ledger.json"),
                            ("report.json", "evolution-report.json"),
                            ("plan.json", "evolution-plan.json")]:
        entry, = [e for e in inventory["files"] if e["source_path"] == original]
        assert sha(ROOT / local) == entry["original_sha256"]
        assert len(input_bytes(ROOT / local)) == entry["original_bytes"]
        if entry["compression"] == "gzip":
            assert sha(ROOT / (local + ".gz")) == entry["stored_sha256"]
        verified[original] = entry["original_sha256"]
    plan = read("evolution-plan.json")
    source = {}
    for name in ("real_evolution_probe.py", "cell_evolution_training.py", "cell_evolution_snapshot.py"):
        actual = sha(ROOT / ("source-" + name))
        assert actual == plan["code_file_sha256"][name]
        source[name] = actual
    return {"original_inputs": verified, "executed_source_hashes_verified": source,
            "source_commit_with_matching_bytes": "a0a92fcbd2a688b948fca96cea16f6f41d6a2bd6"}


def outcomes(entry):
    rows = {}
    for identity, label, probabilities, route in zip(
            entry["source_group_ids"], entry["labels"], entry["task_probabilities"], entry["routes"]):
        assert identity not in rows
        assert len(probabilities) == 4 and all(math.isfinite(x) and x >= 0 for x in probabilities)
        # Pooled Head probabilities are serialized float32; do not renormalize them.
        assert abs(math.fsum(probabilities) - 1) < 1e-6
        prediction = max(range(4), key=lambda i: probabilities[i])
        selected, = route["selected"]
        assert route["actual_calls"] == [selected]
        rows[identity] = {"label": label, "prediction": prediction,
                          "correct": int(prediction == label),
                          "nll": -math.log(max(probabilities[label], 1e-12)),
                          "selected": selected}
    assert len(rows) == len(entry["labels"])
    return rows


def evolution():
    verified = verify_evolution_inputs()
    ledger = read("evolution-ledger.json")
    reports = {r["seed"]: r for r in read("evolution-report.json")["seeds"]}
    filtered = [r for r in ledger if r["phase"] == "evaluation"]
    assert len(ledger) == 69 and len(filtered) == 36
    indexed = {(e["seed"], e["arm"], e["split"]): outcomes(e) for e in filtered}
    assert len(indexed) == 36
    metrics = []
    for (seed, arm, split), rows in indexed.items():
        measured = {"accuracy": mean([r["correct"] for r in rows.values()]),
                    "nll": mean([r["nll"] for r in rows.values()])}
        for metric, value in measured.items():
            assert abs(value - reports[seed]["arms"][arm]["metrics"][split][metric]) < 1e-12
        metrics.append({"seed": seed, "arm": arm, "split": split,
                        "rows": len(rows), **measured})

    paired, summaries = [], []
    seeds = sorted(reports)
    for split in ("future_1", "future_2", "ood"):
        ids = sorted(indexed[(seeds[0], "static", split)])
        per_class = collections.defaultdict(lambda: {"source_seed_evaluations": 0,
            "split_correct": 0, "static_correct": 0, "split_only_correct": 0,
            "static_only_correct": 0, "nll_delta_sum": 0.0})
        all_seed_row_deltas = {identity: [] for identity in ids}
        for seed in seeds:
            left, right = indexed[(seed, "split", split)], indexed[(seed, "static", split)]
            assert sorted(left) == sorted(right) == ids
            wins = losses = ties = slot_changes = 0
            nll_delta, accuracy_delta = [], []
            route_histograms = {"split": collections.Counter(), "static": collections.Counter()}
            for identity in ids:
                a, b = left[identity], right[identity]
                assert a["label"] == b["label"]
                delta = a["correct"] - b["correct"]
                loss_delta = a["nll"] - b["nll"]
                accuracy_delta.append(delta); nll_delta.append(loss_delta)
                wins += delta > 0; losses += delta < 0; ties += delta == 0
                all_seed_row_deltas[identity].append(delta)
                for arm, row in [("split", a), ("static", b)]:
                    route_histograms[arm][row["selected"]] += 1
                # Slots correspond to replay partitions, not equivalent expert functions.
                slot_changes += a["selected"].removeprefix("child_") != b["selected"].removeprefix("head_")
                cls = per_class[a["label"]]
                cls["source_seed_evaluations"] += 1
                cls["split_correct"] += a["correct"]; cls["static_correct"] += b["correct"]
                cls["split_only_correct"] += delta > 0; cls["static_only_correct"] += delta < 0
                cls["nll_delta_sum"] += loss_delta
            old_contrasts = reports[seed]["comparisons"][split]
            for metric, observed in [("accuracy", mean(accuracy_delta)), ("nll", mean(nll_delta))]:
                assert abs(old_contrasts["split_minus_static_" + metric]["difference"] - observed) < 1e-12
            paired.append({"seed": seed, "split": split, "unique_sources": len(ids),
                "split_only_correct": wins, "static_only_correct": losses, "tied_correctness": ties,
                "split_minus_static_accuracy": mean(accuracy_delta),
                "split_minus_static_nll": mean(nll_delta),
                "published_accuracy_interval": old_contrasts["split_minus_static_accuracy"]["descriptive_95_percent_interval"],
                "published_nll_interval": old_contrasts["split_minus_static_nll"]["descriptive_95_percent_interval"],
                "slot_assignment_changes": slot_changes,
                "routes": {k: dict(v) for k, v in route_histograms.items()}})
        class_rows = []
        for label, counts in sorted(per_class.items()):
            n = counts["source_seed_evaluations"]
            class_rows.append({"label": label, **counts,
                "split_minus_static_accuracy": (counts["split_correct"] - counts["static_correct"]) / n,
                "split_minus_static_nll": counts["nll_delta_sum"] / n})
        selected = [r for r in paired if r["split"] == split]
        summaries.append({"split": split, "unique_sources": len(ids), "fixed_fit_seeds": seeds,
            "mean_split_minus_static_accuracy": mean([r["split_minus_static_accuracy"] for r in selected]),
            "mean_split_minus_static_nll": mean([r["split_minus_static_nll"] for r in selected]),
            "split_only_correct_source_seed_pairs": sum(r["split_only_correct"] for r in selected),
            "static_only_correct_source_seed_pairs": sum(r["static_only_correct"] for r in selected),
            "sources_split_worse_in_all_three_fits": sum(all(x < 0 for x in ds) for ds in all_seed_row_deltas.values()),
            "sources_split_better_in_all_three_fits": sum(all(x > 0 for x in ds) for ds in all_seed_row_deltas.values()),
            "per_class": class_rows})
    return {**verified, "original_batches": 69, "evaluation_batches": 36,
        "excluded_nonindependent_reload_mechanics_recovery_batches": 33,
        "every_recomputed_report_metric_matches_to": 1e-12,
        "metrics": metrics, "split_static_pairs": paired, "summaries": summaries,
        "limitations": ["Already exposed historical source cohort; diagnostic only.",
            "Three fixed fits share sources; source-seed pairs are not independent sources.",
            "Stored probabilities cover only the selected expert. Slot changes cannot identify routing error or expert causality.",
            "Published intervals are descriptive per-seed story bootstrap, not new inference or multiplicity-adjusted acceptance."]}


def pft():
    audit = read("pft-math-audit.json")
    runs = audit["per_run"]
    assert len(runs) == 60
    indexed = {(r["head"], r["mask"], r["seed"], r["policy"]): r for r in runs}
    decompositions = []
    for head in ("linear", "gated"):
        chosen = [r for r in runs if r["head"] == head and r["mask"] == "all" and r["policy"] == "loss2"]
        parts = {k: mean([r["cost_parts_delta_vs_zero"][k] for r in chosen])
                 for k in ("current_tracking", "old_tracking", "effort", "total")}
        assert abs(parts["current_tracking"] + parts["old_tracking"] + parts["effort"] - parts["total"]) < 1e-12
        decompositions.append({"head": head, "mask": "all", "policy": "loss2", "reference": "zero additional control, ordinary Adam still active",
            "cost_parts_delta_vs_zero": parts,
            "old_term_fraction_of_tracking_reduction": parts["old_tracking"] / (parts["old_tracking"] + parts["current_tracking"]),
            "current_probe_nll_delta": mean([r["current_probe_delta_vs_zero"] for r in chosen]),
            "old_probe_nll_delta": mean([r["old_probe_delta_vs_zero"] for r in chosen])})
    losses = []
    for (head, mask, seed, policy), r in indexed.items():
        if policy != "loss2": continue
        losses.append({"head": head, "mask": mask, "seed": seed,
            "loss2_minus_myopic_J": r["nonlinear_cost"]["total"] - indexed[(head,mask,seed,"myopic")]["nonlinear_cost"]["total"],
            "extended_minus_loss2_J": indexed[(head,mask,seed,"extended")]["nonlinear_cost"]["total"] - r["nonlinear_cost"]["total"]})
    future = [r for r in audit["external_pointwise_contrasts"] if r["mask"] == "all" and r["left"] == "loss2"
              and r["right"] == "myopic" and r["metric"] == "nll" and r["role"] in ("future_may","future_june")]
    assert len(future) == 4
    return {"input_sha256": sha(ROOT / "pft-math-audit.json"), "reaggregation_scope": "published audit per-run records; not a second audit of raw NPZ arrays",
        "runs": 60, "warm_start_fits": 6,
        "loss2_J_better_than_myopic_count": sum(x["loss2_minus_myopic_J"] < 0 for x in losses),
        "extended_J_worse_than_loss2_count": sum(x["extended_minus_loss2_J"] > 0 for x in losses),
        "comparison_count": len(losses), "cost_decompositions": decompositions,
        "published_conditional_future_contrasts": future,
        "target_identity": "old tracking error = L_old(controlled) - L_old(initial); its square penalizes improvement and deterioration alike",
        "causal_limit": "This directly explains objective incentive, not sole cause of heldout regression. Probes, projection and temporal shift remain."}


def main():
    output = {"schema": "hepta.exposed-evidence-offline-diagnostic.v1",
        "status": "posthoc descriptive audit only; no new acceptance",
        "execution": {"training_updates": 0, "encoder_calls": 0, "model_calls": 0,
                      "remote_workers": 0, "source_code_imports": 0,
                      "script_sha256": sha(Path(__file__).resolve())},
        "evolution": evolution(), "parameter_field": pft(),
        "population_budget_arithmetic": {
            "source": "07df4a9cc385375cddded5b5e3b99632ce0652ec:scripts/memory_cell_population/population_training.py",
            "matched_aggregate_adapter_bytes": 1843200,
            "single_byte_optimizer_step_proxy": 1843200 * 1024,
            "two_children_byte_optimizer_step_proxy": 2 * (1843200 // 2) * 512,
            "single_to_children_active_parameter_step_ratio": 2.0,
            "scope": "Derived private-parameter-update proxy only, not measured FLOPs. Same aggregate input tokens/base model work; split also charges router and 64 gradient probes."}}
    target = ROOT / "offline-diagnostic.json"
    target.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    compact = {"evolution": [{k:v for k,v in row.items() if k != "per_class"} for row in output["evolution"]["summaries"]],
        "evolution_class_deltas": {r["split"]: [(c["label"], c["split_minus_static_accuracy"], c["split_minus_static_nll"]) for c in r["per_class"]] for r in output["evolution"]["summaries"]},
        "pft": {k:v for k,v in output["parameter_field"].items() if k not in ("published_conditional_future_contrasts",)},
        "output_sha256": sha(target)}
    print(json.dumps(compact, indent=2))


if __name__ == "__main__":
    main()
