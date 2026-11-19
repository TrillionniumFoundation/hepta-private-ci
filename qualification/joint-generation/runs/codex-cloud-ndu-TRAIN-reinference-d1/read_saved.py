"""Supplementary readout of this completed diagnostic's arrays; no model imports."""

import hashlib
import json
from pathlib import Path
import time

import numpy as np

from independent.accounting import WorkLedger


HERE = Path(__file__).resolve().parent
ledger = WorkLedger("shared-saved-array-readout", total_cap=20_000_000)


def mean_delta(a, n, take=None):
    if take is not None:
        a, n = a[take], n[take]
    ledger.charge_kernel(
        "saved_array_readout",
        "difference_mean",
        scalar_ops=2 * a.size - 1,
        div_ops=1,
    )
    return float((n.astype(float) - a.astype(float)).mean())


def count(take):
    ledger.charge_kernel(
        "saved_array_readout",
        "boolean_count",
        scalar_ops=take.size - 1,
    )
    return int(take.sum())


def load(name):
    with np.load(HERE / name, allow_pickle=False) as data:
        return {key: data[key] for key in data.files}


def main():
    result = json.loads((HERE / "result.json").read_text())
    mapping = json.loads((HERE / "TRAIN-map.json").read_text())
    inputs = load("TRAIN-inputs.npz")
    labels = inputs["labels"]
    report = {
        "identity": "saved-array-readout-of-new-TRAIN-reinference-d1",
        "uses_original_row_logs": False,
        "additional_forward_or_training_calls": 0,
        "rows_per_model": 3072,
        "physical_sources": 192,
        "comparisons": {},
        "endpointwise_greedy_baseline": {},
        "warning": "descriptive fixed-model paired readout; all sources retained; no inference over training seeds",
    }
    models = {}
    for kind in ("iid", "stratified"):
        for seed in (11, 23, 47):
            a = load(f"requests-A-{kind}-{seed}.npz")
            n = load(f"requests-N-{kind}-{seed}.npz")
            models[f"A-{kind}-{seed}"] = a
            models[f"N-{kind}-{seed}"] = n
            comparison = result["all_source_mechanism"][f"{kind}-{seed}"]
            changed = sorted(
                set(
                    comparison["greedy_became_wrong_rows"]
                    + comparison["greedy_rescued_rows"]
                )
            )
            rows = []
            for row in changed:
                source = mapping["source_ids"][int(inputs["row_source_index"][row])]
                rows.append(
                    {
                        "row": row,
                        "source_id": source,
                        "source_attributes": mapping["sources"][source],
                        "target": int(labels[row]),
                        "command": inputs["commands"][row].tolist(),
                        "A_greedy": [
                            int(a["greedy_text"][row]),
                            int(a["greedy_image"][row]),
                        ],
                        "N_greedy": [
                            int(n["greedy_text"][row]),
                            int(n["greedy_image"][row]),
                        ],
                        **{
                            f"{arm}_{key}": float(data[key][row])
                            for arm, data in (("A", a), ("N", n))
                            for key in (
                                "text_true_margin",
                                "image_true_margin",
                                "greedy_reward",
                            )
                        },
                        **{
                            f"{arm}_{head}_attribute_errors": data[
                                f"{head}_attribute_errors"
                            ][row].tolist()
                            for arm, data in (("A", a), ("N", n))
                            for head in ("text", "image")
                        },
                    }
                )
            delta = {}
            for key in (
                "task_utility",
                "joint_success",
                "consistency",
                "pixel_mse",
                "CE_rho",
                "negative_reward_mass",
                "negative_reward_expectation",
                "greedy_reward",
                "text_true_probability",
                "image_true_probability",
                "greedy_joint_success",
            ):
                delta[key] = mean_delta(a[key], n[key])
            attributes = {
                head: [
                    mean_delta(
                        a[f"{head}_attribute_errors"][:, j],
                        n[f"{head}_attribute_errors"][:, j],
                    )
                    for j in range(3)
                ]
                for head in ("text", "image")
            }
            components = [
                mean_delta(a["reward_components"][:, j], n["reward_components"][:, j])
                for j in range(5)
            ]
            strata = {}
            for field in ("labels", "source_scene"):
                strata[field] = []
                for value in range(12):
                    ledger.charge_kernel(
                        "saved_array_readout",
                        "stratum_membership",
                        compare_ops=len(labels),
                    )
                    take = inputs[field] == value
                    strata[field].append(
                        {
                            "value": value,
                            "rows": count(take),
                            "delta_utility": mean_delta(
                                a["task_utility"], n["task_utility"], take
                            ),
                            "delta_text_probability": mean_delta(
                                a["text_true_probability"],
                                n["text_true_probability"],
                                take,
                            ),
                            "delta_image_probability": mean_delta(
                                a["image_true_probability"],
                                n["image_true_probability"],
                                take,
                            ),
                            "delta_greedy_joint": mean_delta(
                                a["greedy_joint_success"],
                                n["greedy_joint_success"],
                                take,
                            ),
                        }
                    )
            source_deltas = [
                entry["delta_utility"] for entry in comparison["all_sources"]
            ]
            ledger.charge_kernel(
                "saved_array_readout",
                "source_signs_range",
                compare_ops=4 * len(source_deltas),
            )
            source_summary = {
                "positive_utility_sources": sum(v > 0 for v in source_deltas),
                "negative_utility_sources": sum(v < 0 for v in source_deltas),
                "minimum_source_utility_delta": min(source_deltas),
                "maximum_source_utility_delta": max(source_deltas),
                "all_192_source_table": f"result.json:all_source_mechanism/{kind}-{seed}/all_sources",
            }
            report["comparisons"][f"{kind}-{seed}"] = {
                "mean_deltas": delta,
                "reward_component_deltas": components,
                "attribute_error_rate_deltas": attributes,
                "source_summary": source_summary,
                "all_target_and_source_classes": strata,
                "all_changed_greedy_rows": rows,
                "head_transition_counts": comparison["head_transition_counts"],
                "timing_four_waves": comparison["timing_waves"],
            }
    for seed in (11, 23, 47):
        successes = {
            key: count(models[f"{key}-{seed}"]["greedy_joint_success"])
            for key in ("A-iid", "A-stratified", "N-iid", "N-stratified")
        }
        ledger.charge_kernel(
            "saved_array_readout",
            "endpointwise_comparison",
            compare_ops=1,
            scalar_ops=1,
        )
        report["endpointwise_greedy_baseline"][str(seed)] = {
            "joint_correct_counts_of_3072": successes,
            "N_stratified_minus_best_A_correct_count": successes["N-stratified"]
            - max(successes["A-iid"], successes["A-stratified"]),
        }
    report["shared_operator_work"] = ledger.snapshot()
    report["complete_units_with_readout"] = {
        arm: data["consumed_units"] + ledger.consumed_units
        for arm, data in result["actual_units"].items()
    }
    target = HERE / "saved-array-readout.json"
    with target.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    # Includes imports from process start and all input/output I/O up to this point.
    receipt = {
        "readout_process_cpu_seconds_before_receipt": time.process_time(),
        "full_shared_attribution_to_each_arm": True,
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "output_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "shared_operator_units": ledger.consumed_units,
        "scope": "new saved-array readout only; run-d1.txt retains diagnostic process final-write CPU",
    }
    with (HERE / "saved-array-readout-execution.json").open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({**receipt, "cpu_after_receipt": time.process_time()}))


if __name__ == "__main__":
    main()
