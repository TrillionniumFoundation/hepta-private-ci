"""R10 96-case refinement/monitor allocation sweep with sealed endpoints."""
from __future__ import annotations

import os
for _key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_key, "1")

import argparse
import csv
import hashlib
import itertools
import json
import platform
import resource
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import torch
from scipy.stats import qmc

from refine import (
    ROOT,
    METHODS,
    SCHEDULES,
    MONITORS,
    FIT_CAP,
    SWITCH_AT,
    WidePolicy,
    gaussian_rule,
    fit,
    rule,
    make_problem,
    evaluate,
    SCALE,
)

torch.set_num_threads(1)
HERE = Path(__file__).resolve().parent
PROTOCOL_COMMIT = "e40eb5297bdc1969b8492e448207a2b3bd4d943d"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dump(path: Path, value) -> str:
    data = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    with open(path, "xb") as stream:
        stream.write(data)
    return digest(data)


def save(path: Path, arrays: dict[str, np.ndarray]) -> None:
    with open(path, "xb") as stream:
        np.savez_compressed(stream, **arrays)


def sources() -> dict[str, str]:
    directories = (HERE, ROOT / "scaling", ROOT / "allocation", ROOT / "continuous", ROOT / "nonquadratic")
    return {
        str(path.relative_to(ROOT)): digest(path.read_bytes())
        for directory in directories
        for path in sorted(directory.glob("*.py"))
    }


def specs() -> list[dict]:
    settings = list(itertools.product(METHODS, SCHEDULES, MONITORS))
    cases = []
    for width_index, width in enumerate((64, 256)):
        for seed_index, seed in enumerate((11, 23, 47)):
            rotation = (5 * seed_index + 7 * width_index) % len(settings)
            for method, schedule, monitor in settings[rotation:] + settings[:rotation]:
                cases.append(
                    dict(width=width, seed=seed, method=method, schedule=schedule, monitor=monitor)
                )
    return cases


def name_for(case: dict) -> str:
    return f"w{case['width']}-{case['method']}-{case['schedule']}-{case['monitor']}-s{case['seed']}"


def evaluation_panels():
    # Same parent law; independent post-fit numerical diagnostics.
    for name in ("cc5", "cc9", "cc17", "gl9"):
        states, weights = rule(name)
        yield name, states, weights, make_problem()
    states, weights = gaussian_rule(5)
    yield "gl5", states, weights, make_problem()
    for replicate in range(4):
        states = (2*qmc.Sobol(4, scramble=True, seed=2026101501+replicate).random_base2(10)-1)*SCALE
        yield f"qmc{replicate}", states, np.full(len(states), 1/len(states)), make_problem()
    states = (2*qmc.Sobol(4, scramble=True, seed=2026101501).random_base2(7)-1)*SCALE
    for name, points, change in (
        ("scale", 2*states, "base"),
        ("dynamics", states, "dynamics"),
        ("horizon4", states, "horizon"),
    ):
        yield name, points, np.full(len(points), 1/len(points)), make_problem(change)


def trial(out: Path, case: dict) -> None:
    out.mkdir(parents=True, exist_ok=False)
    wall_zero, cpu_zero = time.perf_counter(), time.process_time()
    plan = dict(
        schema="hepta.ndu.refinement.r10",
        case=case,
        source=sources(),
        protocol_commit=PROTOCOL_COMMIT,
        fit_cap=FIT_CAP,
        switch_at=SWITCH_AT,
        final_gate="max(CC5,CC9)<=.04850 and abs(CC9-CC5)<=1e-6",
    )
    plan_hash = dump(out / "PLAN.json", plan)
    policy = WidePolicy(case["width"], case["seed"])
    save(out / "INITIAL.npz", {"theta": policy.initial})
    dump(out / "STARTED.json", {"plan_sha256": plan_hash})

    theta, monitors, switches, fit_report = fit(**case)
    save(out / "WEIGHTS.npz", {"theta": theta})
    save(out / "MONITOR_CHECKPOINTS.npz", {"theta": monitors})
    save(out / "SWITCH_WEIGHTS.npz", {"theta": switches})
    fit_hash = dump(out / "FIT.json", fit_report)
    dump(
        out / "FIT_SEAL.json",
        dict(
            fit_sha256=fit_hash,
            weights_sha256=digest(theta.astype("<f8", copy=False).tobytes()),
            monitors_sha256=digest((out / "MONITOR_CHECKPOINTS.npz").read_bytes()),
            switches_sha256=digest((out / "SWITCH_WEIGHTS.npz").read_bytes()),
        ),
    )

    # Weights are sealed before all dense/post-fit evaluation.
    eval_cpu = time.process_time()
    raw, costs = {}, {}
    tensor = torch.tensor(theta, dtype=torch.float64)
    for name, states, weights, problem in evaluation_panels():
        raw[name] = evaluate(policy, tensor, problem, states, chunk=256)
        if not np.isfinite(raw[name]).all():
            raise FloatingPointError(name)
        costs[name] = float(weights @ raw[name].mean(1))
    save(out / "PREDICTIONS.npz", raw)
    if sources() != plan["source"]:
        raise ValueError("source drift")

    report = dict(
        case=case,
        plan_sha256=plan_hash,
        source=plan["source"],
        parameters=len(theta),
        initial_sha256=digest(policy.initial.astype("<f8", copy=False).tobytes()),
        weights_sha256=digest(theta.astype("<f8", copy=False).tobytes()),
        predictions_sha256=digest((out / "PREDICTIONS.npz").read_bytes()),
        changed=not np.array_equal(theta, policy.initial),
        fit=fit_report,
        costs=costs,
        evaluation_cpu=time.process_time()-eval_cpu,
        total_main_wall=time.perf_counter()-wall_zero,
        total_main_cpu=time.process_time()-cpu_zero,
        process_peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        environment=dict(
            python=sys.version,
            numpy=np.__version__,
            torch=torch.__version__,
            platform=platform.platform(),
            threads=torch.get_num_threads(),
        ),
        flops=None,
        energy_joules=None,
        production_authorized=False,
        project_cloud=False,
    )
    dump(out / "REPORT.json", report)
    print(
        json.dumps(
            dict(
                name=name_for(case),
                qualified=fit_report["final_qualification"],
                cc17=costs["cc17"],
                fit_wall=fit_report["fit_wall"],
                monitors=len(fit_report["monitor_checks"]),
            ),
            sort_keys=True,
        ),
        flush=True,
    )


def sweep(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=False)
    laws = {}
    for name in ("gl3", "gl5"):
        states, weights = gaussian_rule(3 if name == "gl3" else 5)
        laws[name+"_states"], laws[name+"_weights"] = states, weights
    for name in ("cc5", "cc9"):
        states, weights = rule(name)
        laws[name+"_states"], laws[name+"_weights"] = states, weights
    save(out / "LAWS.npz", laws)
    plan = dict(
        schema="hepta.ndu.refinement.sweep.r10",
        cases=specs(),
        source=sources(),
        protocol_commit=PROTOCOL_COMMIT,
        fit_cap=FIT_CAP,
        switch_at=SWITCH_AT,
        law_sha256=digest((out / "LAWS.npz").read_bytes()),
        primary="width256 terminal-only: staged GL3->GL5 versus fixed GL5, all solvers/seeds",
        secondary="width256 fixed GL5: terminal-only versus frequent exact-lazy monitoring",
    )
    plan_hash = dump(out / "PLAN.json", plan)
    started = time.perf_counter()
    census = []
    for case in specs():
        name = name_for(case)
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        wall = time.perf_counter()
        command = [sys.executable, str(Path(__file__).resolve()), "trial", "--out", str(out/name)]
        for key, value in case.items():
            command += ["--"+key, str(value)]
        row = dict(name=name, case=case)
        with open(out/(name+".log"), "xb") as log:
            try:
                result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=240)
                row.update(returncode=result.returncode, status="completed" if result.returncode == 0 else "failed")
            except (subprocess.TimeoutExpired, OSError) as exc:
                row.update(returncode=None, status="failed", error=str(exc))
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        row.update(
            child_wall=time.perf_counter()-wall,
            child_cpu=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
        )
        if row["status"] == "completed":
            row["report_sha256"] = digest((out/name/"REPORT.json").read_bytes())
        census.append(row)
        dump(out/(name+".completion.json"), row)
        print(json.dumps(row, sort_keys=True), flush=True)
    failures = sum(row["status"] != "completed" for row in census)
    dump(
        out / "COMPLETE.json",
        dict(
            plan_sha256=plan_hash,
            census=census,
            completed=len(census)-failures,
            failed=failures,
            wall=time.perf_counter()-started,
            child_cpu=sum(row["child_cpu"] for row in census),
        ),
    )
    if failures:
        raise SystemExit("execution failures retained")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("trial", "sweep"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--width", type=int, default=64)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--method", choices=METHODS, default="adam")
    parser.add_argument("--schedule", choices=SCHEDULES, default="fixed_gl5")
    parser.add_argument("--monitor", choices=MONITORS, default="terminal_only")
    args = parser.parse_args()
    if args.mode == "sweep":
        sweep(args.out)
    else:
        trial(
            args.out,
            {key: getattr(args, key) for key in ("width", "seed", "method", "schedule", "monitor")},
        )
