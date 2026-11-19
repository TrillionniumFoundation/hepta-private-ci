"""Read stored tensors and independently check Adam arithmetic; no model import."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import time

import torch


def review(attempt):
    started, cpu = time.perf_counter(), time.process_time()
    raw = attempt / "RAW"
    source = json.loads((raw / "SOURCE.json").read_text())
    root = Path(__file__).resolve().parents[2]
    for path, expected in source["files"].items():
        if hashlib.sha256((root / path).read_bytes()).hexdigest() != expected:
            raise ValueError(f"executed source changed: {path}")
    rows = json.loads((raw / "TRAINING.json").read_text())
    if len(rows) != 60:
        raise ValueError("wrong actual update count")
    first, second = [0.] * 8, [0.] * 8
    previous = rows[0]["parameters_before"]
    errors = {"parameter": 0., "exp_avg": 0., "exp_avg_sq": 0.}
    for step, row in enumerate(rows, 1):
        if row["step"] != step or row["parameters_before"] != previous:
            raise ValueError("broken parameter/update chain")
        for i, gradient in enumerate(row["gradient"]):
            first[i] = .9 * first[i] + .1 * gradient
            second[i] = .999 * second[i] + .001 * gradient**2
            parameter = previous[i] - .03 * first[i] / (1 - .9**step) / (math.sqrt(second[i] / (1 - .999**step)) + 1e-8)
            errors["parameter"] = max(errors["parameter"], abs(parameter - row["parameters_after"][i]))
            errors["exp_avg"] = max(errors["exp_avg"], abs(first[i] - row["exp_avg"][i]))
            errors["exp_avg_sq"] = max(errors["exp_avg_sq"], abs(second[i] - row["exp_avg_sq"][i]))
        previous = row["parameters_after"]
    if max(errors.values()) > 2e-13:
        raise ValueError("Adam arithmetic disagrees")
    warm = torch.load(raw / "WARM.pt", weights_only=True)
    cold = torch.load(raw / "COLD.pt", weights_only=True)
    compared = 0
    def compare(left, right):
        nonlocal compared
        if isinstance(left, torch.Tensor):
            if left.dtype != right.dtype or left.shape != right.shape or left.contiguous().numpy().tobytes() != right.contiguous().numpy().tobytes():
                raise ValueError("cold tensor mismatch")
            compared += left.numel()
        elif isinstance(left, dict):
            if left.keys() != right.keys():
                raise ValueError("cold metadata keys mismatch")
            for key in left:
                compare(left[key], right[key])
        elif isinstance(left, list):
            if len(left) != len(right):
                raise ValueError("cold list length mismatch")
            for a, b in zip(left, right):
                compare(a, b)
        elif left != right:
            raise ValueError("cold metadata value mismatch")
    compare(warm, cold)
    final = torch.load(raw / "FINAL.pt", weights_only=True)
    inputs = torch.load(raw / "INPUT.pt", weights_only=True)
    mse = float((final["prediction"][:, :, 1:] - inputs["target"][:, :, 1:]).square().mean())
    result = json.loads((raw / "RESULT.json").read_text())
    if mse != result["final_loss"] or compared != result["cold_compared_coordinates"]:
        raise ValueError("stored result arithmetic mismatch")
    report = {"status": "PASS_STORED_ARITHMETIC_AND_COMPLETE_COLD_RECORD", "optimizer_calls": 0,
              "model_forwards": 0, "model_backwards": 0, "adam_coordinate_comparisons": 60 * 8 * 3,
              "adam_max_abs_errors": errors, "cold_tensor_coordinates": compared, "cold_metadata_exact": True,
              "final_mse_recomputed": mse, "executed_source_hashes_verified": len(source["files"]),
              "body_wall_seconds_after_imports": time.perf_counter() - started,
              "body_cpu_seconds_after_imports": time.process_time() - cpu,
              "limits": ["Recorded gradients are not regenerated", "No held-out benefit is established",
                         "Uninstrumented initialization/balance/warm exponentials are not counted as zero"]}
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("attempt", type=Path)
    review(parser.parse_args().attempt)
