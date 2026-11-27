"""Analyze saved TRAIN outputs; bounded initial gate only after oracle headroom."""

import json
from pathlib import Path
import sys
import time

import numpy as np

from content_control.refiner import PATHS, Refiner, forward_work
from content_control.run import observe
from data import prepare_decoded_observer
from independent.accounting import WorkLedger
from independent.evaluation import paired_interval
from independent.learning import setup_work
from independent.run import write_json
from model import JointModel, softmax


def analyze(run):
    started = time.process_time()
    run = Path(run)
    build = json.loads((run / "build.json").read_text())
    result = json.loads((run / "train-result.json").read_text())
    arrays = result["per_row"]
    summary = {"scope": "selected TRAIN inner-validation only; descriptive intervals, no confirmation", "comparisons": {}}
    for left, right in (("A", "H"), ("A_R", "H_R"), ("A_R", "A"), ("A_R", "S")):
        summary["comparisons"][left + "-" + right] = {
            metric: paired_interval([r[metric] for r in arrays[left]], [r[metric] for r in arrays[right]],
                build["inner_rows_source_ids"], seeds=[11, 23, 47], replicates=2000, bootstrap_seed=77431)
            for metric in ("task_utility", "joint_success", "greedy_joint_success")}
    summary["arms"] = {}
    reference = build["calibration"]["cpu_ns"] / build["calibration"]["rows"]
    for arm, reports in result["reports"].items():
        metrics = {k: float(np.mean([r["means"][k] for r in reports])) for k in reports[0]["means"]}
        build_cpu = build["costs"][arm]["complete_cpu"]
        metrics["cpu_net_utility"] = float(np.mean([r["means"]["task_utility"] - .02 * (
            r["service"]["cpu_ns"] / r["service"]["rows"] + r["service"]["prepare_cpu_ns"] / 100000
            + build_cpu * 1e9 / 3 / 100000) / reference for r in reports]))
        summary["arms"][arm] = {"means": metrics, "per_seed": reports, "build_cpu": build_cpu,
            "units": build["ledgers"][arm]["totals"]["consumed_units"],
            "selected": result["selected"][arm], "reference_cpu_ns": reference}
    ids = np.array(build["inner_rows_source_ids"])
    choice = result["selected"]["A_R"]
    path_values, source_gaps, row_gaps, winners = [], [], [], []
    for seed in (11, 23, 47):
        folder = run / f"A_R-{seed}-{choice['lr']}"
        with np.load(folder / "validation-paths.npz", allow_pickle=False) as raw:
            table = np.column_stack([raw[p + "/task_utility"] for p in PATHS])
        path_values.append(table)
        grouped = np.stack([table[ids == g].mean(0) for g in sorted(set(ids))])
        source_gaps.append(float(np.mean(grouped.max(1) - grouped[:, PATHS.index(choice["path"])])))
        row_gaps.append(float(np.mean(table.max(1) - table[:, PATHS.index(choice["path"])])))
        winners.append({p: int(np.sum(grouped.argmax(1) == j)) for j, p in enumerate(PATHS)})
    summary["action_crossing"] = {"paths": PATHS, "per_seed_source_oracle_gap": source_gaps,
        "per_seed_row_oracle_gap": row_gaps, "source_winner_counts": winners,
        "oracle_semantics": "uses labels; not an observable/achievable routing gain", "initial_gate_trained": False}
    gate_ledger = WorkLedger("initial-gate-development", 12_000_000_000)
    if np.mean(source_gaps) > .002:
        gate_start, gate_reports = time.process_time(), []
        with np.load(run / "train-inputs.npz", allow_pickle=False) as data:
            labels = data["fit_labels"]
        for seed, inner_table in zip((11, 23, 47), path_values):
            base, refiner = JointModel.load(run / f"base-{seed}.npz"), Refiner()
            with np.load(run / f"A_R-{seed}-{choice['lr']}/refiner.npz", allow_pickle=False) as saved:
                refiner.params = {k: saved[k].copy() for k in refiner.params}
            with np.load(run / f"features-{seed}.npz", allow_pickle=False) as features:
                fit = tuple(features["fit_" + k].copy() for k in ("h", "t", "i"))
                inner = tuple(features["inner_" + k].copy() for k in ("h", "t", "i"))
            gate_ledger.charge_kernel("counterfactual", "observer", **setup_work(base.dimensions, "A"))
            observer = prepare_decoded_observer(base)
            targets = []
            for path in PATHS:
                gate_ledger.charge_kernel("counterfactual", "forward", **forward_work(len(labels), path))
                p, q = refiner.forward(fit, path)
                targets.append(observe(p, q, labels, observer, gate_ledger, "counterfactual")["task_utility"])
            z = []
            for part in (fit, inner):
                n = len(part[0])
                gate_ledger.charge_kernel("initial_features", "two_softmax", scalar_ops=4*n*12-2*n,
                    exp_ops=2*n*12, div_ops=2*n*12, compare_ops=2*n*11)
                z.append(np.column_stack((part[0], softmax(part[1]), softmax(part[2]), np.ones(n))))
            n, d = z[0].shape
            gate_ledger.charge_kernel("ridge", "fit", macs=n*d*d+n*d*5+d**3//3+5*d*d,
                                     scalar_ops=d*d, counts={"ridge_fits": 1})
            weights = np.linalg.solve(z[0].T @ z[0] + 1e-3*np.eye(d), z[0].T @ np.column_stack(targets))
            gate_ledger.charge_kernel("gate", "predict", macs=len(z[1])*d*5, compare_ops=4*len(z[1]))
            selected = (z[1] @ weights).argmax(1)
            achieved = inner_table[np.arange(len(selected)), selected]
            gate_reports.append({"seed": seed, "gain_over_static": float(np.mean(achieved-inner_table[:,PATHS.index(choice['path'])])),
                                 "chosen_path_counts": {p: int(np.sum(selected==j)) for j,p in enumerate(PATHS)}})
            np.savez_compressed(run / f"initial-gate-{seed}.npz", weights=weights, choices=selected)
        summary["action_crossing"].update(initial_gate_trained=True, gate_reports=gate_reports,
                                          gate_development_cpu=time.process_time()-gate_start)
    summary["gate_ledger"] = gate_ledger.snapshot()
    summary["analysis_cpu_before_receipt"] = time.process_time() - started
    summary["gate_cost_scope"] = "additional R&D, outside qualified static builds; no complete conditional-system claim"
    write_json(run / "analysis.json", summary)
    print(json.dumps({"arms": {k: {x:v for x,v in r.items() if x != "per_seed"} for k,r in summary["arms"].items()},
                      "comparisons": summary["comparisons"], "crossing": summary["action_crossing"]}, indent=2))


if __name__ == "__main__":
    analyze(sys.argv[1])
