"""Read only old build receipts/models and reconstruct CORE TRAIN, never tests."""

import hashlib
import json
from pathlib import Path
import time

import numpy as np

from independent.accounting import WorkLedger
from independent.data_v2 import dataset, manifest
from independent.learning import CachedObjective, objective_work
from model import JointModel


ROOT = Path(__file__).resolve().parents[1]


def diagnose(out):
    started = time.process_time()
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    run = ROOT / "runs/codex-cloud-core-c1-t2"
    plan_path = ROOT / "core_confirmation/plan.json"
    plan = json.loads(plan_path.read_text())
    data = dataset("train", plan["data_profile"])
    ledger = WorkLedger("old-train-diagnosis")
    rows, provenance = [], {}
    for arm in ("anchor", "additive"):
        receipt = run / (arm + "-build.json")
        build = json.loads(receipt.read_text())
        provenance[receipt.relative_to(ROOT).as_posix()] = hashlib.sha256(receipt.read_bytes()).hexdigest()
        for selected in build["selected"]:
            seed = selected["seed"]
            for filename in (f"base-{seed}.npz", selected["model_file"]):
                if filename in provenance:
                    continue
                path = run / filename
                provenance[filename] = hashlib.sha256(path.read_bytes()).hexdigest()
                model = JointModel.load(path)
                ledger.model_forward("diagnosis", rows=len(data["labels"]), input_dim=202, hidden=32, classes=12)
                p, q = model.forward(data["full"])
                h = CachedObjective("H", model, ce_anchor=plan["ce_anchor"])
                a = CachedObjective("A", model, ce_anchor=plan["ce_anchor"], ledger=ledger, stage="diagnosis")
                for code in ("H", "A"):
                    ledger.charge_kernel("diagnosis", "objective_" + code, **objective_work(code, len(p)))
                _, ht, hi = h.policy_gradients(p, q, data["labels"])
                _, at, ai = a.policy_gradients(p, q, data["labels"])
                ce = np.column_stack((ht, hi))
                utility = np.column_stack((at - ht, ai - hi))
                truth = (p[np.arange(len(p)), data["labels"]] + q[np.arange(len(q)), data["labels"]]) / 2
                strata = []
                for lo, high in ((0, .1), (.1, .5), (.5, .9), (.9, 1.0000001)):
                    take = (truth >= lo) & (truth < high)
                    if take.any():
                        c, u = ce[take], utility[take]
                        strata.append({"target_probability_range": [lo, high], "rows": int(take.sum()),
                            "utility_to_ce_logit_norm": float(np.linalg.norm(u) / np.linalg.norm(c)),
                            "cosine": float(np.sum(c * u) / (np.linalg.norm(c) * np.linalg.norm(u))),
                            "opposed_row_fraction": float(np.mean(np.sum(c * u, axis=1) < 0))})
                rows.append({"file": filename, "seed": seed, "mean_target_probability": float(truth.mean()),
                    "strata": strata, "utility_range": [float(a.reward.min()), float(a.reward.max())]})
        provenance[arm] = {"selected": [{k: row[k] for k in ("seed", "updates", "learning_rate", "model_file")}
                                       for row in build["selected"]],
                           "complete_cpu_seconds": build["cost"]["cpu_seconds"],
                           "complete_operator_units": build["ledger"]["totals"]["consumed_units"],
                           "candidate_count": len(build["all_candidates"])}
    report = {"scope": "CORE TRAIN diagnostic only; no formal input/result read", "data": manifest(data),
        "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(), "rows": rows,
        "provenance": provenance, "kernel_ledger": ledger.snapshot(),
        "unpriced_work": "input generation, public validation, probability strata, norm/cosine diagnostics, IO/hash/JSON; all included in actual CPU",
        "ce_anchor": plan["ce_anchor"], "cpu_seconds_before_receipt": time.process_time() - started}
    (out / "diagnosis.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"cpu_seconds_before_receipt": report["cpu_seconds_before_receipt"], "rows": rows}, indent=2))


if __name__ == "__main__":
    import sys
    diagnose(sys.argv[1])
