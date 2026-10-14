"""Actual independent-Head training on bundled real handwritten digit images.

Raw 8x8 pixels / 16 are the frozen features: NO pretrained or learned Encoder.
Public-row holdout, not writer-disjoint/future Hepta efficacy. Same immutable
initial Heads, training rows, minibatch seeds and steps in both optimizer arms.
"""
import argparse
from importlib.resources import files
from pathlib import Path
import platform
import statistics

import torch

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell import head_training as h


def split_pixels(pixels, cells):
    """Hash only the raw image, never its label; duplicates retain one fold/Cell."""
    e.integer(cells, 1, 128, "study Cells")
    identities = [e.sha(row.to(torch.uint8).numpy().tobytes()) for row in pixels]
    return identities, tuple(int(v[:8], 16) % 5 == 0 for v in identities), tuple(
        int(v[8:16], 16) % cells for v in identities)


def study(output, *, cells=8, steps=80, repetitions=7):
    import sklearn
    from sklearn.datasets import load_digits

    e.integer(steps, 1, 1000, "study steps")
    e.integer(repetitions, 1, 9, "study repetitions")
    output.mkdir(parents=True, exist_ok=False)
    try:
        data = load_digits()
        pixels = torch.tensor(data.data, dtype=torch.float32)
        identities, holdout, owners = split_pixels(pixels, cells)
        x = pixels / 16.0  # fixed normalization, no train/test fitted transform
        train_ids = tuple(torch.tensor([i for i in range(len(x)) if not holdout[i] and owners[i] == c],
                                       dtype=torch.long) for c in range(cells))
        test_ids = [i for i in range(len(x)) if holdout[i]]
        plan = {"dataset": "sklearn bundled UCI handwritten digits", "sklearn": sklearn.__version__,
            "bundled_csv_sha256": e.sha(files("sklearn.datasets.data").joinpath("digits.csv.gz").read_bytes()),
            "feature_sha256": e.tensor_digest(x), "cells": cells, "steps": steps,
            "repetitions": repetitions, "features": "raw 8x8 pixels divided by 16, no Encoder",
            "partition": "image SHA256 first 32bits mod5=0 holdout, next32bits mod Cells routes",
            "cohort": [[v, "holdout" if holdout[i] else "train", owners[i]] for i, v in enumerate(identities)],
            "input_rows": len(x), "train_rows": sum(map(len, train_ids)), "holdout_rows": len(test_ids),
            "kind": "gated", "classes": 10, "rank": 8, "seed": 20261013,
            "atol": h.ATOL, "rtol": h.RTOL, "pretrained_weights_used": False,
            "writer_disjoint_verified": False, "future_window": False,
            "source_sha256": {n: e.sha((Path(__file__).parent / n).read_bytes())
                              for n in ("execution.py", "head_training.py", "head_training_study.py")}}
        e.write_once(output / "plan.json", plan)
        # Only training labels are passed to either fitter; scoring follows sealing.
        y = torch.tensor(data.target, dtype=torch.long)
        targets = tuple(y[r] for r in train_ids)
        seeds = tuple(20261013 + c for c in range(cells))
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(20261013)
            initial = tuple(e.Head(64, 10, "gated", 8).eval() for _ in range(cells))
        all_x = tuple(x[[i for i in test_ids if owners[i] == c]] for c in range(cells))
        timings, reports, final = {"scalar": [], "grouped": []}, [], {}
        # Symmetric explicit warmup; exclude only this declared unrelated tiny fit.
        e.fit(initial[0], x[train_ids[0]], targets[0], steps=1, seed=seeds[0])
        h.fit_cells(initial[:1], x, train_ids[:1], targets[:1], seeds=seeds[:1], step_counts=(1,))
        for repeat in range(repetitions):
            for arm in (("scalar", "grouped") if repeat % 2 == 0 else ("grouped", "scalar")):
                with e.measured() as cost:
                    if arm == "scalar":
                        fitted = [e.fit(m, x[r], t, steps=steps, seed=s)
                                  for m, r, t, s in zip(initial, train_ids, targets, seeds)]
                        models = tuple(v[0] for v in fitted)
                        detail = {"cells": [v[1] for v in fitted]}
                    else:
                        models, detail = h.fit_cells(initial, x, train_ids, targets,
                            seeds=seeds, step_counts=(steps,) * cells)
                timings[arm].append(cost["wall_ns"])
                with torch.no_grad():
                    logits = [m(t).tolist() for m, t in zip(models, all_x)]
                final[arm] = (models, detail, logits)
                e.write_once(output / f"{repeat}-{arm}.json", {"timing": cost, "training": detail, "logits": logits})
            left, right = final["scalar"], final["grouped"]
            delta = max(float((p-q).abs().max().detach()) for a, b in zip(left[0], right[0])
                        for p, q in zip(a.parameters(), b.parameters()))
            reports.append({"repeat": repeat, "max_parameter_difference": delta,
                "parameter_parity": all(torch.allclose(p, q, atol=h.ATOL, rtol=h.RTOL)
                    for a, b in zip(left[0], right[0]) for p, q in zip(a.parameters(), b.parameters())),
                "minibatch_hashes_match": [c["minibatch_sha256"] for c in left[1]["cells"]] ==
                    [c["minibatch_sha256"] for c in right[1]["cells"]]})
        with torch.no_grad():
            frozen = [m(t).tolist() for m, t in zip(initial, all_x)]
        ordered_ids = [i for c in range(cells) for i in test_ids if owners[i] == c]
        payload = {"row_ids": ordered_ids, "frozen": frozen,
                   "scalar": final["scalar"][2], "grouped": final["grouped"][2]}
        seal = e.write_once(output / "predictions.json", payload)
        p = e.decode(e.bound_file(output / "predictions.json", seal))
        values = {arm: torch.tensor([row for block in p[arm] for row in block])
                  for arm in ("frozen", "scalar", "grouped")}
        report = {"prediction_sha256": seal, "repetitions": reports, "raw_wall_ns": timings,
            "median_wall_ns": {a: statistics.median(v) for a,v in timings.items()},
            "holdout_rows": len(ordered_ids),
            "accuracy": {a: float((v.argmax(-1) == y[ordered_ids]).float().mean()) for a,v in values.items()},
            "argmax_changes": int((values["scalar"].argmax(-1) != values["grouped"].argmax(-1)).sum()),
            "logit_parity": bool(torch.allclose(values["scalar"], values["grouped"], atol=h.ATOL, rtol=h.RTOL)),
            "python": platform.python_version(), "torch": torch.__version__, "threads": torch.get_num_threads(),
            "independent_evaluation": False, "encoder_calls": 0, "production_accepted": False}
        report["numerical_contract_passed"] = report["logit_parity"] and all(
            r["parameter_parity"] and r["minibatch_hashes_match"] for r in reports)
        e.write_once(output / "report.json", report)
        if not report["numerical_contract_passed"]:
            raise e.InputError("training contract mismatch; unmodified measurements retained")
        return report
    except Exception as error:
        e.write_once(output / "failure.json", {"error": type(error).__name__, "message": str(error)})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cells", type=int, choices=(8, 32), default=8)
    args = parser.parse_args()
    torch.set_num_threads(1)
    study(args.output, cells=args.cells)
