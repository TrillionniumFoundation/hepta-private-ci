"""Tiny development-only API/serialization check; no confirmatory namespace use."""

import argparse
import copy
import importlib
import json
from pathlib import Path
import time

import torch

from .protocol import STAGES, record_failures, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    if torch.get_num_interop_threads() != 1:
        torch.set_num_interop_threads(1)
    plan = copy.deepcopy(json.loads(Path(args.plan).read_text()))
    plan["namespace"] = "hcsn-mechanism-v2-development/20261122-e29f-api-smoke-01"
    plan["seeds"] = [101, 102, 103, 104, 105]
    for stage in ("representation", "readout", "profiled"):
        plan[stage].update(train=8, dev=8, final=8, length=4)
    plan["readout"].update(max_iterations=24, max_evaluations=64)
    plan["profiled"].update(max_steps=2, checkpoints=[0, 1, 2], arm_wall_seconds=60.0)
    plan["control"].update(
        intervals=[0.5],
        logit_limits=[2.0],
        train_count=8,
        dev_count=8,
        final_count=8,
        max_steps=2,
        checkpoints=[0, 1, 2],
    )
    plan["clock"].update(final=4, segments=4, refinement=2)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    summary = {
        "scope": "development API execution only; no performance/quality inference",
        "cases": [],
    }
    for stage in STAGES:
        module = importlib.import_module(f"qualification.hcsn_mechanism_v2.{stage}_run")
        cfg = {**plan, **plan[stage], "namespace": plan["namespace"] + "/" + stage}
        task, seed = ("held_hazard" if stage == "clock" else "first_passage"), 101
        started = time.perf_counter()
        fit = (
            module.fit_case(seed, cfg)
            if stage == "control"
            else module.fit_case(task, seed, cfg)
        )
        final = (
            module.final_case(fit, seed, cfg)
            if stage == "control"
            else module.final_case(fit, task, seed, cfg)
        )
        save(output / f"{stage}.json", {"fit": fit, "final": final})
        failures = record_failures(fit) + record_failures(final)
        summary["cases"].append(
            {
                "stage": stage,
                "seconds": time.perf_counter() - started,
                "failures": failures,
            }
        )
        if failures:
            raise ValueError(
                f"development case failure, raw record retained: {failures}"
            )
    save(output / "summary.json", summary)
    print(json.dumps(summary, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
