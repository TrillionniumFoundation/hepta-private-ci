"""Reproduce the normalization mechanism and inspect already-exposed old tests."""
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from benchmarks.data import make_data, fingerprint
from third.memory.reference import forward, readout, closed_write


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def mechanism():
    rows = []
    for n in (0, 31, 127, 511, 4095):
        r = 1/(2+n)
        g = np.diag([1., float(n)])*r
        h = np.array([r, 0.])
        row = dict(orthogonal_distractors=n)
        for mode, ridge in (("fixed", .01), ("mass", .01*r)):
            matrix = g+ridge*np.eye(2)
            row[mode] = dict(read=float(np.linalg.solve(matrix, h)[0]),
                             condition=float(np.linalg.cond(matrix)))
        rows.append(row)
    return rows


def write_diagnostics():
    rows = []
    for kind in ("full_hx", "hcsn", "sigmoid", "ridge_memory_only"):
        for seed in range(5):
            path = ROOT/f"next/ridge/checkpoints/memory_{kind}_seed{seed}.npz"
            p = dict(np.load(path))
            filler = np.zeros((4, 17), np.float32)
            filler[np.arange(4), np.arange(4)] = 1.
            filler[:, -1] = np.log(2.)
            marker = filler.copy()
            marker[:, 4] = 1.
            w = closed_write(filler @ p["write"]+p["write_bias"]).ravel()
            marked = closed_write(marker @ p["write"]+p["write_bias"]).ravel()
            rows.append(dict(kind=kind, seed=seed, checkpoint_sha256=sha(path),
                filler_write=w.tolist(), marked_write=marked.tolist(),
                all_four_filler_writes_zero=bool(np.all(w == 0)),
                expected_effective_ridge128=float(.01*(1+126*w.mean()+marked.mean())),
                expected_effective_ridge512=float(.01*(1+510*w.mean()+marked.mean()))))
    return rows


def main():
    start = time.perf_counter()
    old = json.loads((ROOT/"next/ridge/results.json").read_text())
    challenges = json.loads((ROOT/"next/ridge/challenge_results.json").read_text())
    rows = []
    for kind, name in (("full_hx", "full"), ("sigmoid", "legacy_sigmoid")):
        for seed in range(5):
            path = ROOT/f"next/ridge/checkpoints/memory_{kind}_seed{seed}.npz"
            recorded = next(r for r in old["runs"] if (r["kind"], r["task"], r["seed"]) == (kind, "memory", seed))
            if sha(path) != recorded["checkpoint_sha256"]:
                raise RuntimeError("Old checkpoint differs from recorded evidence")
            p = dict(np.load(path))
            for length, count, rng in ((128, 1024, 2700000+1000*seed+428),
                                       (512, 256, 2800000+1000*seed)):
                data = make_data("memory", rng, count, length)
                original = recorded["metrics"]["test_128"] if length == 128 else next(
                    r["metrics"] for r in challenges["runs"] if
                    (r["kind"], r["seed"], r["challenge"]) == (kind, seed, "memory_512"))
                metrics = {mode: dict(correct=0, maximum_condition=0., maximum_relative_residual=0.,
                                     maximum_read=0., maximum_write_mass=0.) for mode in ("fixed", "mass")}
                for offset in range(0, count, 32):
                    state = forward(p, data["x"][offset:offset+32], data["dt"][offset:offset+32], name)
                    for mode in metrics:
                        logits, detail = readout(p, state, mode)
                        metrics[mode]["correct"] += int(np.sum(logits.argmax(1) == data["y"][offset:offset+32]))
                        for key, value in detail.items():
                            metrics[mode][key] = max(metrics[mode][key], value)
                for value in metrics.values():
                    value["accuracy"] = value.pop("correct")/count
                rows.append(dict(kind=kind, seed=seed, length=length, examples=count,
                    data_sha256=fingerprint(data), checkpoint_sha256=sha(path),
                    original_recorded_accuracy=original["accuracy"],
                    original_accuracy_reproduced=metrics["fixed"]["accuracy"] == original["accuracy"],
                    modes=metrics))
                print(json.dumps({k: rows[-1][k] for k in ("kind", "seed", "length", "modes")}), flush=True)
    result = dict(schema="hcsn.memory.mechanism.diagnostic.v1", exploratory=True,
        old_tests_already_exposed=True, retrained=False, new_acceptance_claim=False,
        explanation="G=r*S,H=r*T. Fixed normalized ridge implies unnormalized lambda/r. "
                    "Mass-scaled ridge removes this normalization effect only; conditioning and interference remain.",
        orthogonal_counterexample=mechanism(), checkpoint_write_diagnostics=write_diagnostics(),
        old_checkpoint_counterfactuals=rows,
        all_old_accuracies_reproduced=all(r["original_accuracy_reproduced"] for r in rows),
        elapsed_seconds=time.perf_counter()-start,
        source_sha256={str(p.relative_to(ROOT)): sha(p) for p in
                       (Path(__file__), HERE/"reference.py", ROOT/"benchmarks/data.py",
                        ROOT/"next/ridge/results.json", ROOT/"next/ridge/challenge_results.json")})
    (HERE/"diagnostic_results.json").write_text(json.dumps(result, indent=2)+"\n")
    if not result["all_old_accuracies_reproduced"]:
        raise RuntimeError("NumPy reproduction differs; inspect before making a causal claim")


if __name__ == "__main__":
    main()
