"""Frozen-source equivalence and interleaved complete forward/backward timing."""

import argparse
from dataclasses import fields
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import statistics
import sys
import time
import traceback
import types

import torch

from .cells import ValueKernelCell
from . import tensor as hx


BASELINE_SHA256 = {"cells.py": "9a2cd6b059b5b01532c1bb920196c34960b8013825068fc7a8762640ad2459d6",
                   "tensor.py": "624d293a9d3a7afa7e32be3e9133ac18cc0f90e49e7bdc5ff9a3b25c4563bddc"}


def run(baseline):
    for name, expected in BASELINE_SHA256.items():
        if hashlib.sha256((baseline/name).read_bytes()).hexdigest() != expected:
            raise ValueError("baseline source differs from frozen 456c0d56bd")
    package = types.ModuleType("hx_reuse_baseline")
    package.__path__ = [str(baseline)]
    sys.modules[package.__name__] = package
    spec = importlib.util.spec_from_file_location(package.__name__+".cells", baseline/"cells.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    torch.set_num_threads(1)
    cases = []

    def sample(model, inputs):
        model.zero_grad(set_to_none=True)
        inputs = inputs.detach().clone().requires_grad_()
        start = time.perf_counter()
        cpu_start = time.process_time()
        output = model(inputs)
        output.square().mean().backward()
        seconds = time.perf_counter()-start
        cpu_seconds = time.process_time()-cpu_start
        return seconds, cpu_seconds, [output.detach(), inputs.grad] + [None if p.grad is None else p.grad.clone()
                                                                     for p in model.parameters()]

    shapes = [(dtype, 8, length, 16, 4) for dtype in (torch.float32, torch.float64) for length in (1, 8, 32)]
    shapes.append((torch.float32, 32, 16, 8, 2))
    for dtype, batch, length, width, channels in shapes:
            torch.manual_seed(823)
            direct = module.ValueKernelCell(channels, width).to(dtype=dtype)
            prepared = ValueKernelCell(channels, width, equity_evaluation="prepared").to(dtype=dtype)
            prepared.load_state_dict(direct.state_dict())
            inputs = torch.randn(batch, length, channels, dtype=dtype)
            _, _, reference = sample(direct, inputs)
            _, _, candidate = sample(prepared, inputs)
            tolerance = 3e-5 if dtype == torch.float32 else 3e-11
            for got, wanted in zip(candidate, reference):
                if got is None or wanted is None:
                    if got is not None or wanted is not None:
                        raise AssertionError("direct/prepared gradient availability differs")
                else:
                    torch.testing.assert_close(got, wanted, atol=tolerance, rtol=tolerance)
            times = {"direct": [], "prepared": []}
            cpu_times = {"direct": [], "prepared": []}
            for repetition in range(7):
                order = (("direct", direct), ("prepared", prepared))
                for name, model in (order if repetition % 2 == 0 else reversed(order)):
                    seconds, cpu_seconds, _ = sample(model, inputs)
                    times[name].append(seconds)
                    cpu_times[name].append(cpu_seconds)
            cases.append({"dtype": str(dtype), "batch": batch, "time": length, "hidden": width, "input": channels,
                          "parameter_count": sum(p.numel() for p in direct.parameters()),
                          "max_output_abs": float((candidate[0]-reference[0]).abs().max()),
                          "max_gradient_abs": max(float((a-b).abs().max()) for a, b in zip(candidate[1:], reference[1:])
                                                  if a is not None),
                          "unused_gradients": sum(a is None for a in reference[1:]),
                          "seconds": times, "cpu_seconds": cpu_times,
                          "median_speedup": statistics.median(times["direct"])/statistics.median(times["prepared"]),
                          "median_cpu_speedup": statistics.median(cpu_times["direct"])/statistics.median(cpu_times["prepared"])})
    # This extra stress case predates reuse. Preserve actual nonfinite
    # derivatives rather than counting equal NaNs as a correctness success.
    stress = {"dtype": "torch.float32", "margin": 12., "maturity": .05, "resolved": False}
    for name in ("direct", "prepared"):
        theta = torch.tensor([.05,.02,.2,5.,100.,.05,.25,.6,.01], dtype=torch.float32, requires_grad=True)
        margin = torch.tensor(12., dtype=torch.float32, requires_grad=True)
        p = hx.HXParams(**dict(zip((f.name for f in fields(hx.HXParams)), theta)))
        value = (hx.hx_equity(margin, p) if name == "direct" else
                 hx.prepared_hx_equity(margin, hx.prepare_hx_equity(p)))
        gradients = torch.autograd.grad(value, (margin, theta))
        encode = lambda x: float(x) if math.isfinite(float(x)) else str(float(x))
        stress[name] = {"value": float(value.detach()), "margin_gradient": encode(gradients[0]),
                        "parameter_gradients": [encode(v) for v in gradients[1]],
                        "finite_gradients": all(bool(torch.isfinite(g).all()) for g in gradients)}
    here = Path(__file__).parent
    return {"scope": "unchanged HX feature-cell function; fresh full forward graph and backward each sample",
            "timing_excludes": ["imports", "initialization", "zero_grad", "input clone", "result comparison"],
            "baseline_sha256": BASELINE_SHA256,
            "source_sha256": {n: hashlib.sha256((here/n).read_bytes()).hexdigest()
                              for n in ("tensor.py", "cells.py", "baselines.py", "equity_reuse_study.py")},
            "torch": torch.__version__, "threads": 1, "cases": cases,
            "cell_equivalence_passed": True, "unresolved_legacy_stress": stress}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8") as target:
        try:
            result = run(args.baseline_package)
        except Exception:
            result = {"cell_equivalence_passed": False, "error": traceback.format_exc(),
                      "study_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        json.dump(result, target, separators=(",", ":"), allow_nan=False)
        target.write("\n")
    if not result["cell_equivalence_passed"]:
        print(result["error"])
        raise SystemExit(1)
    print(json.dumps({"cell_equivalence_passed": result["cell_equivalence_passed"],
                      "speedups": [case["median_speedup"] for case in result["cases"]],
                      "legacy_stress_resolved": result["unresolved_legacy_stress"]["resolved"]}))
