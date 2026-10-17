"""Physical local CPU P0 pilot (real computation, deliberately toy model)."""
from __future__ import annotations
import argparse
from dataclasses import asdict
from fractions import Fraction as F
import json
import os
from pathlib import Path
import tempfile
import time

from fabric import (Choice, Edge, FiniteNdu, Q24, certify_scalar_contraction,
                    percentile_ns, physical_shadow_bench, q24_dot, sha)
from native import CellProgram, NativeMotorShadow, compile_reviewed_source


def run_pilot(repetitions: int = 16) -> dict[str, object]:
    stem_results = [physical_shadow_bench(n, repetitions) for n in (64, 256, 1024, 4096)]
    graph = {"s": (
        Choice("stop", 1, (Edge(F(1), F(0), "end"),)),
        Choice("invest", 1, (Edge(F(1), F(0), "after"),))),
             "after": (
        Choice("stop", 1, (Edge(F(1), F(0), "end"),)),
        Choice("complete", 1, (Edge(F(1), F(2), "end"),)))}
    ndu = FiniteNdu(graph, {"end": F(0)}, max_depth=2).choose("s", 2)
    contraction = certify_scalar_contraction(fixed_reward=F(1, 4), q=F(1, 2))
    a = tuple((i - 8) * Q24 // 16 for i in range(16))
    b = tuple((8 - i) * Q24 // 16 for i in range(16))
    with tempfile.TemporaryDirectory(prefix="hepta-cell-aot-") as path:
        lib = Path(path) / "q24.so"
        compiler = compile_reviewed_source(Path(__file__).with_name("q24_native.c"), lib)
        kernel = NativeMotorShadow(lib, compiler["binary_sha256"])
        program = CellProgram(sha(b"test source (not OS-observed)"),
                              sha(b"toy model"), 1, "PURE_Q24_DOT16")
        typed_samples, native_samples = [], []
        for step in range(128):
            # Balanced alternating order; different code paths, so NOT matched full-service cost.
            if step % 2 == 0:
                start = time.perf_counter_ns()
                reference = q24_dot(a, b)
                typed_samples.append(time.perf_counter_ns() - start)
                start = time.perf_counter_ns()
                receipt = kernel.run(program, a, b)
                native_samples.append(time.perf_counter_ns() - start)
            else:
                start = time.perf_counter_ns()
                receipt = kernel.run(program, a, b)
                native_samples.append(time.perf_counter_ns() - start)
                start = time.perf_counter_ns()
                reference = q24_dot(a, b)
                typed_samples.append(time.perf_counter_ns() - start)
            if receipt.numeric_result != reference or receipt.authority != "DENY_ALL":
                raise AssertionError("numerical/effect mismatch")
    return {
        "source": "locally_executed_physical_cpu_on_synthetic_mechanism",
        "authority": "DENY_ALL", "promotion": "HOLD_NO_GO",
        "stem_fleet": stem_results,
        "ndu_finite_tree": {"chosen_action": ndu.action,
                            "exact_utility": str(ndu.value),
                            "visited_states": ndu.visited_states,
                            "not_full_fbsde": True},
        "scalar_contraction": {"approx": str(contraction.approximation),
                               "residual": str(contraction.residual),
                               "error_bound": str(contraction.error_bound),
                               "iterations": contraction.iterations,
                               "not_global_theorem": True},
        "native_aot": {**compiler, "iterations": 128,
                       "native_includes_reference_and_digest": True,
                       "python_reference_only": True,
                       "native_guarded_p50_ns": percentile_ns(native_samples, .50),
                       "native_guarded_p95_ns": percentile_ns(native_samples, .95),
                       "native_guarded_p99_ns": percentile_ns(native_samples, .99),
                       "python_ref_p50_ns": percentile_ns(typed_samples, .50),
                       "python_ref_p95_ns": percentile_ns(typed_samples, .95),
                       "python_ref_p99_ns": percentile_ns(typed_samples, .99)},
        "unsupported_claims": ["pretrained_encoder", "learned_cell_utility",
                               "image_audio_video_generation", "real_gui_effect",
                               "gpu_execution", "mcp_end_to_end_advantage",
                               "production_cell_split", "system2_general_reasoning"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=16)
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="New private output directory, never an existing data source")
    args = parser.parse_args()
    if args.output_dir.exists() or args.output_dir.is_symlink():
        raise ValueError("create-only output directory required")
    args.output_dir.mkdir(mode=0o700, parents=False)
    receipt = run_pilot(args.repetitions)
    data = json.dumps(receipt, sort_keys=True, indent=2, allow_nan=False).encode("utf-8")
    path = args.output_dir / "physical-shadow.json"
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
    finally:
        pass
    print(json.dumps({"receipt_sha256": sha(data), "bytes": len(data),
                      "cells": [x["cell_count"] for x in receipt["stem_fleet"]],
                      "authority": "DENY_ALL", "promotion": "HOLD_NO_GO"}, sort_keys=True))


if __name__ == "__main__":
    main()
