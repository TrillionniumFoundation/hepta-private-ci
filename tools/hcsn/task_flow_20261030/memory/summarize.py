"""Report fixed quality and function-family comparisons, including failures."""
import json
from pathlib import Path
import sys

import numpy as np
from scipy.stats import t

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from third.memory.execution import atomic_json
from task_flow_20261030.memory.freeze import verify, sha


def main():
    verify()
    result = json.loads((HERE / "results.json").read_text())
    audit = json.loads((HERE / "audit.json").read_text())
    p, rows = result["protocol"], result["runs"]
    index = {(r["task"], r["seed"], r["variant"]): r for r in rows}
    def scores(task, variant, split):
        return np.array([index[task, seed, variant]["metrics"][split]["accuracy"] for seed in p["seeds"]])
    gate = dict(matrix_complete=result["complete"], numerical_and_replay=audit["passed"])
    for task, threshold in (("memory", .95), ("retrieval", .9)):
        gate[task + "128_every_seed"] = bool(np.all(scores(task, "full_delta", "test128") >= threshold))
    gate["memory512_improvement"] = bool(np.mean(scores("memory", "full_delta", "test512")
                                                  - scores("memory", "full_fixed", "test512")) >= .02)
    gate["retrieval512_nonregression"] = bool(np.mean(scores("retrieval", "full_delta", "test512")
                                                       - scores("retrieval", "full_fixed", "test512")) >= -.01)
    contrasts, summaries = [], []
    quantile = float(t.ppf(1 - .05 / (2 * 8), len(p["seeds"]) - 1))
    for task in p["tasks"]:
        splits = ["test128", "test512"] + (["capacity8_512", "overwrite128", "interference128"] if task == "retrieval" else [])
        for split in splits:
            for variant in p["variants"]:
                a = scores(task, variant, split)
                summaries.append(dict(task=task, split=split, variant=variant, mean=float(a.mean()),
                                      sd=float(a.std(ddof=1)), minimum=float(a.min()), seed_scores=a.tolist()))
        for split in ("test128", "test512"):
            for control in ("sigmoid_delta", "c1_delta"):
                difference = scores(task, "full_delta", split) - scores(task, control, split)
                mean = float(difference.mean())
                half = quantile * float(difference.std(ddof=1)) / np.sqrt(len(difference))
                contrasts.append(dict(task=task, split=split, control=control, mean_difference=mean,
                                      bonferroni95_interval=[mean - half, mean + half],
                                      passed=bool(mean >= .01 and mean - half > 0)))
    costs = dict(complete_run_wall_seconds=sum(r["run_wall_seconds"] for r in rows),
                 complete_run_cpu_seconds=sum(r["run_cpu_seconds"] for r in rows),
                 compilation_seconds=sum(r["training"]["compilation_seconds"] for r in rows),
                 optimizer_seconds=sum(r["training"]["optimizer_seconds"] for r in rows),
                 validation_seconds=sum(r["training"]["validation_seconds"] for r in rows),
                 candidates_saved=sum(r["training"]["candidates_retained"] for r in rows),
                 peak_process_rss=max(r["process_peak_rss_bytes"] for r in rows),
                 audit_cpu_seconds=audit["cpu_seconds"], audit_wall_seconds=audit["wall_seconds"])
    output = dict(quality_gate=dict(passed=all(gate.values()), checks=gate), summaries=summaries,
                  shape_contrasts=contrasts, positive_shape_gates=sum(c["passed"] for c in contrasts),
                  costs=costs, results_sha256=sha(HERE / "results.json"), audit_sha256=sha(HERE / "audit.json"),
                  interpretation="Three paired seeds, fixed synthetic tasks; no population-level equivalence, GPU, energy or backbone claim")
    atomic_json(HERE / "summary.json", output)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
