"""Independent NumPy checkpoint replay after the frozen matrix completes."""
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from third.memory.data import make_suite
from third.memory.freeze import verify, sha
from third.memory.reference import forward, readout
from third.memory.execution import atomic_json


def metrics(logits, labels):
    z = np.asarray(logits, np.float64)
    z = z-z.max(1, keepdims=True)
    logp = z-np.log(np.exp(z).sum(1, keepdims=True))
    prob = np.exp(logp)
    hit = prob.argmax(1) == labels
    confidence = prob.max(1)
    bins = np.minimum((confidence*10).astype(int), 9)
    ece = sum(float((bins == k).mean()*abs(hit[bins == k].mean()-confidence[bins == k].mean()))
              for k in range(10) if np.any(bins == k))
    return dict(accuracy=float(hit.mean()), loss=float(-logp[np.arange(len(labels)), labels].mean()),
                brier=float(np.mean(np.sum((prob-np.eye(prob.shape[1])[labels])**2, axis=1))), ece=ece)


def main():
    verify()
    result = json.loads((HERE/"development_results.json").read_text())
    if not result["complete"]:
        raise RuntimeError("Wait for the complete matrix")
    rows = []
    for row in result["runs"]:
        path = HERE/row["checkpoint_file"]
        if sha(path) != row["checkpoint_sha256"]:
            raise RuntimeError("Checkpoint hash changed")
        p = dict(np.load(path))
        _, suite, hashes = make_suite(row["task"], row["seed"], result["protocol"])
        if hashes != row["data_sha256"]:
            raise RuntimeError("Dataset changed")
        name, mode = row["variant"].split("_")
        errors = {}
        for split in ("diagnostic128", "diagnostic512"):
            data = suite[split]
            outputs = []
            for offset in range(0, len(data["y"]), 32):
                state = forward(p, data["x"][offset:offset+32], data["dt"][offset:offset+32], name)
                outputs.append(readout(p, state, mode, solver_dtype=np.float64)[0])
            observed = metrics(np.concatenate(outputs), data["y"])
            errors[split] = {k: abs(v-row["metrics"][split][k]) for k, v in observed.items()}
        passed = all(v < 5e-5 for split in errors.values() for v in split.values())
        rows.append(dict(task=row["task"], seed=row["seed"], variant=row["variant"], errors=errors, passed=passed))
        print("REPLAY", len(rows), row["variant"], passed, flush=True)
    initial = {}
    for row in result["runs"]:
        if not row["variant"].startswith("memory_"):
            initial.setdefault((row["task"], row["seed"]), set()).add(row["initial_parameters_sha256"])
    same_initial = all(len(hashes) == 1 for hashes in initial.values())
    report = dict(passed=all(r["passed"] for r in rows) and same_initial,
                  independent_numpy_replays=rows, dynamic_initial_parameters_identical=same_initial,
                  development_results_sha256=sha(HERE/"development_results.json"),
                  retrained=False, source=sha(Path(__file__)))
    atomic_json(HERE/"development_audit.json", report)
    if not report["passed"]:
        raise RuntimeError("Independent replay failed")


if __name__ == "__main__":
    main()
