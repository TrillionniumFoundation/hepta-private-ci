"""Actual 64..4096 Cell CPU Head microbenchmark on explicit synthetic features.

NOT pretrained Stem/learning/quality evidence. Every scale runs in a fresh process;
OS high-water RSS covers BOTH arms and packing, not separate-arm memory savings.
No system caches are flushed and no affinity/frequency/energy control is claimed.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys

import torch

from experiments.shared_stem_cell.execution import Head, integer
from experiments.shared_stem_cell.head_batch import compare_heads
from experiments.shared_stem_cell.wire import decode, sha, write_once

SCALES = (64, 256, 1024, 4096)


def worker(output, cells, repetitions):
    integer(cells, 1, 4096, "resident cells")
    torch.set_num_threads(1)
    torch.manual_seed(20261013 + cells)
    # Width/rank are fixed before measurement, not selected for a favorable result.
    entries = tuple((i, Head(384, 4, "gated", 8).eval()) for i in range(cells))
    features = torch.randn(cells, 384)
    output.mkdir(parents=True, exist_ok=False)
    write_once(output / "plan.json", {"cells": cells, "width": 384, "classes": 4, "rank": 8,
        "kind": "gated", "seed": 20261013 + cells, "repetitions": repetitions,
        "synthetic_features": True, "heads_trained": False, "pretrained_weights_used": False})
    summaries = []
    for stride in (16, 4, 1):
        ids = tuple(range(0, cells, stride))
        for copies in (1, 8):
            x = features[list(ids)].repeat((copies, 1))
            selected = ids * copies
            # This preregistered profile set excludes >16384-row workloads.
            if len(selected) > 16384:
                continue
            report = compare_heads(entries, x, selected, repetitions=repetitions)
            name = f"stride-{stride}-copies-{copies}"
            seal = write_once(output / f"{name}.json", report)
            summaries.append({"profile": name, "report_sha256": seal,
                "resident_cells": cells, "active_cells": len(ids), "input_copies": copies,
                "request_rows": len(selected), "quantiles_ns": report["quantiles_ns"],
                "packing_wall_ns": report["packing"]["wall_ns"],
                "pack_amortization_replays": report["pack_amortization_replays"],
                "numerical_parity_passed": report["numerical_parity_passed"],
                "argmax_changes": report["argmax_changes"],
                "max_absolute_logit_difference": report["max_absolute_logit_difference"],
                "counts": report["counts"]})
    # Linux ru_maxrss is in KiB; do not reinterpret other OS values.
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024 if sys.platform == "linux" else None
    return {"cases": summaries, "pid": os.getpid(), "process_peak_rss_both_arms_bytes": peak,
        "python": platform.python_version(), "torch": torch.__version__,
        "cpu_platform": platform.machine(), "threads": torch.get_num_threads(),
        "energy_joules": None, "encoder_calls": 0, "pretrained_weights_used": False,
        "head_training_performed": False, "whole_hepta_latency": False, "production_accepted": False}


def study(output, repetitions=7):
    integer(repetitions, 3, 101, "repetitions")
    output.mkdir(parents=True, exist_ok=False)
    write_once(output / "plan.json", {"scales": SCALES, "repetitions": repetitions,
        "source_sha256": sha(Path(__file__).read_bytes()), "features": "synthetic_float32",
        "profiles": "stride 16/4/1 x copies 1/8, only explicit <=16384-row profiles",
        "claim": "CPU Head arithmetic and wrapper resource comparison only"})
    reports = []
    for cells in SCALES:
        destination = output / f"cells-{cells}"
        with (output / f"cells-{cells}.log").open("xb") as log:
            result = subprocess.run([sys.executable, "-m", "experiments.shared_stem_cell.head_batch_study",
                "--synthetic", "--worker", str(cells), "--repetitions", str(repetitions),
                "--output", str(destination.absolute())], stdout=log, stderr=log,
                stdin=subprocess.DEVNULL, timeout=180, check=False)
        if result.returncode != 0:
            write_once(output / "failure.json", {"cells": cells, "exit_code": result.returncode})
            raise RuntimeError("actual Head scale subprocess failed; original logs retained")
        reports.append(decode((destination / "report.json").read_bytes()))
    report = {"scales": reports, "pretrained_weights_used": False, "independent_evaluation": False,
              "production_accepted": False}
    write_once(output / "report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--synthetic", action="store_true", required=True)
    parser.add_argument("--repetitions", type=int, default=7)
    parser.add_argument("--worker", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker is None:
        study(args.output, args.repetitions)
    else:
        write_once(args.output / "report.json", worker(args.output, args.worker, args.repetitions))
