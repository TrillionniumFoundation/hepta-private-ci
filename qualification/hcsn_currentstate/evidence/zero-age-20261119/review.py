"""Read all frozen synthetic outputs; no model, autograd or optimizer call."""

import argparse
import hashlib
import json
from pathlib import Path
import statistics

import torch


def review(root):
    plan_bytes = (root / "PLAN.json").read_bytes()
    plan = json.loads(plan_bytes)
    controller = json.loads((root / "CONTROLLER.json").read_text())
    if hashlib.sha256(plan_bytes).hexdigest() != controller["plan_sha256"]:
        raise ValueError("plan identity mismatch")
    roster = {(case["name"], engine) for case in plan["cases"] for engine in ("baseline", "candidate")}
    actual = [(entry["case"], entry["engine"]) for entry in controller["children"]]
    if len(actual) != len(roster) or set(actual) != roster or any(
            entry["exit_code"] != 0 or entry["timed_out"] for entry in controller["children"]):
        raise ValueError("incomplete successful roster")
    rows = []
    for case in plan["cases"]:
        raw, metrics = {}, {}
        for engine in ("baseline", "candidate"):
            directory = root / f"{case['name']}-{engine}"
            metrics[engine] = json.loads((directory / "RESULT.json").read_text())
            raw_path = directory / "RAW.pt"
            if hashlib.sha256(raw_path.read_bytes()).hexdigest() != metrics[engine]["raw_sha256"]:
                raise ValueError("raw hash mismatch")
            raw[engine] = torch.load(raw_path, map_location="cpu", weights_only=True)
        baseline, candidate = raw["baseline"], raw["candidate"]
        for field in ("state_time", "state_bytes", "pending_schedule"):
            if baseline[field] != candidate[field]:
                raise ValueError("complete-state metadata mismatch: " + field)
        if baseline["weights"].keys() != candidate["weights"].keys():
            raise ValueError("weight roster differs")
        pairs = [("inputs", baseline["inputs"], candidate["inputs"], True)]
        pairs.extend(("weight:" + name, value, candidate["weights"][name], True)
                     for name, value in baseline["weights"].items())
        pairs.extend((name, baseline[name], candidate[name], False) for name in ("logits", "input_gradient"))
        if baseline["parameter_gradients"].keys() != candidate["parameter_gradients"].keys():
            raise ValueError("gradient roster differs")
        pairs.extend(("gradient:" + name, value, candidate["parameter_gradients"][name], False)
                     for name, value in baseline["parameter_gradients"].items())
        if len(baseline["state_tensors"]) != len(candidate["state_tensors"]):
            raise ValueError("complete-state tensor roster differs")
        pairs.extend(("state:" + str(index), left, right, False) for index, (left, right) in
                     enumerate(zip(baseline["state_tensors"], candidate["state_tensors"])))
        differences = []
        for name, left, right, exact in pairs:
            if not bool(torch.isfinite(left).all()) or not bool(torch.isfinite(right).all()):
                raise ValueError("nonfinite tensor: " + name)
            torch.testing.assert_close(left, right, atol=0 if exact else plan["equivalence_atol"],
                                       rtol=0 if exact else plan["equivalence_rtol"])
            differences.append({"field": name, "coordinates": left.numel(),
                                "max_abs": float((left - right).abs().max()) if left.numel() else 0.})
        summary = {}
        for engine, measure in metrics.items():
            repetitions = measure["repetitions"]
            if len(repetitions) != plan["repetitions"] or measure["optimizer_calls"] or measure["dataset_rows_read"]:
                raise ValueError("execution count mismatch")
            summary[engine] = {"median_wall_seconds": statistics.median(r["wall_seconds"] for r in repetitions),
                               "median_cpu_seconds": statistics.median(r["cpu_seconds"] for r in repetitions),
                               **{field: repetitions[0][field] for field in
                                  ("autograd_saved_payload_bytes_with_repeats", "actual_forward_exponentials",
                                   "largest_exponential_dimension", "state_bytes")}}
        rows.append({"case": case, "tensor_comparisons": len(pairs),
                     "tensor_coordinates": sum(d["coordinates"] for d in differences),
                     "max_abs_difference": max(d["max_abs"] for d in differences),
                     "same_source_law_equivalence_pass": True, "differences": differences,
                     "measurements": summary,
                     "median_wall_ratio_baseline_over_candidate":
                         summary["baseline"]["median_wall_seconds"] / summary["candidate"]["median_wall_seconds"]})
    return {"schema": "hcsn-zero-age-synthetic-review-v1", "cases": rows,
            "models_executed_by_reader": 0, "global_numerical_qualification": False,
            "new_task_quality_measurement": False, "controller": controller}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(review(args.root), indent=2) + "\n")
