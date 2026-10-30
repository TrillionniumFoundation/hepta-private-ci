"""Exploratory diagnosis only if the declared retrieval development gate fails."""
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from third.memory.audit_development import metrics
from third.memory.data import make_suite
from third.memory.execution import atomic_json
from third.memory.freeze import verify, sha
from third.memory.reference import forward, readout


def main():
    verify()
    plan = json.loads((HERE/"retrieval_counterfactual_plan.json").read_text())
    if plan["source_sha256"] != sha(Path(__file__)) or plan["scientific_freeze_sha256"] != sha(HERE/"freeze.json"):
        raise RuntimeError("Exploratory diagnosis plan source changed")
    result = json.loads((HERE/"development_results.json").read_text())
    audit = json.loads((HERE/"development_audit.json").read_text())
    if not result["complete"] or not audit["passed"]:
        raise RuntimeError("Requires the complete, independently replayed matrix")
    gate = result["development_gate"]["checks"]
    if gate["retrieval128_every_seed"] and gate["retrieval512_delta"]:
        raise RuntimeError("No declared retrieval failure; do not add optional diagnostic work")
    rows = []
    for row in result["runs"]:
        if row["task"] != "retrieval" or not row["variant"].startswith("full_"):
            continue
        path = HERE/row["checkpoint_file"]
        if sha(path) != row["checkpoint_sha256"]:
            raise RuntimeError("Checkpoint changed")
        params = dict(np.load(path))
        _, suite, hashes = make_suite("retrieval", row["seed"], result["protocol"])
        if hashes != row["data_sha256"]:
            raise RuntimeError("Development input changed")
        original_mode = row["variant"].split("_")[1]
        for split in ("diagnostic128", "diagnostic512"):
            data = suite[split]
            outputs = {mode:[] for mode in ("fixed", "mass")}
            diagnostics = {mode:[] for mode in outputs}
            for offset in range(0, len(data["y"]), 32):
                state = forward(params, data["x"][offset:offset+32], data["dt"][offset:offset+32], "full")
                for mode in outputs:
                    logits, aux = readout(params, state, mode, solver_dtype=np.float64)
                    outputs[mode].append(logits)
                    diagnostics[mode].append(aux)
            observed = {mode:metrics(np.concatenate(values), data["y"]) for mode, values in outputs.items()}
            original_error = max(abs(observed[original_mode][k]-v) for k, v in row["metrics"][split].items())
            summaries = {mode:{k:max(a[k] for a in values) for k in values[0]} for mode, values in diagnostics.items()}
            rows.append(dict(seed=row["seed"], trained_variant=row["variant"], split=split,
                checkpoint_sha256=row["checkpoint_sha256"], metrics_by_read=observed,
                diagnostics_by_read=summaries, original_metric_maximum_error=original_error,
                original_reproduced=original_error < 5e-5))
            print("COUNTERFACTUAL", row["seed"], row["variant"], split,
                  {mode:m["accuracy"] for mode,m in observed.items()}, flush=True)
    report = dict(originals_reproduced=all(r["original_reproduced"] for r in rows), rows=rows,
        original_development_gate_unchanged=result["development_gate"],
        development_results_sha256=sha(HERE/"development_results.json"), source_sha256=sha(Path(__file__)),
        exploratory_plan_sha256=sha(HERE/"retrieval_counterfactual_plan.json"),
        retrained=False, new_confirmation_data_constructed=False,
        scope="Exploratory failure diagnosis on already exposed development samples. Each checkpoint keeps identical states/keys/writes/weights and changes only final ridge convention. No gate or model selection changes.")
    atomic_json(HERE/"retrieval_counterfactual.json", report)
    if not report["originals_reproduced"]:
        raise RuntimeError("Counterfactual original-score reproduction failed")


if __name__ == "__main__":
    main()
