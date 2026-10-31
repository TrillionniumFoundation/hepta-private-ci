"""Measure fresh resident costs after the training and control jobs finish."""

import argparse
import json
from pathlib import Path
import resource
import subprocess
import sys
import time
import traceback

from .training_run import AREA, ROOT, file_sha, write_json


MODULE = "experiments.multimodal_output_portfolio.abc_recovery.timing_run"


def execute(registration_path):
    registration = json.loads(Path(registration_path).read_text())
    paths = {name: Path(value) for name, value in registration["paths"].items()}
    output = paths["output"]
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    try:
        if any(file_sha(AREA / name) != value for name, value in registration["source_sha256"].items()):
            raise ValueError("Timing wrapper dependencies changed")
        for key, expected in registration["completion_file_sha256"].items():
            if file_sha(paths[key] / "result.json") != expected:
                raise ValueError("An upstream completion receipt changed")
        if any(file_sha(path) != expected for path, expected in registration["bound_input_sha256"].items()):
            raise ValueError("A bound timing input changed")
        import torch
        from ..v7.evaluation import load_reward
        from ..v7.snapshot import Snapshot
        from ..v7.sources import load_roles
        from .control_run import load_bundle
        from .timing import benchmark_resident
        protocol = json.loads(paths["protocol"].read_text())
        torch.set_num_threads(protocol["threads"])
        training = json.loads((paths["training"] / "result.json").read_text())
        control = json.loads((paths["control"] / "result.json").read_text())
        frozen = {(row["seed"], row["arm"]): row for row in control["fitted"]}
        models, bundles = {}, {}
        load_wall, load_cpu = time.perf_counter_ns(), time.process_time_ns()
        for row in training["models"]:
            key = (row["seed"], row["arm"])
            models[key] = Snapshot.load(row["model_path"], expected_file_sha256=row["model_file_sha256"])
            directory = Path(frozen[key]["directory"]) / "policies"
            if file_sha(directory / "policy-freeze.json") != frozen[key]["policy_freeze_sha256"]:
                raise ValueError("Policy freeze identity changed")
            bundles[key] = load_bundle(directory)
        qualified = json.loads((paths["qualification"] / "result.json").read_text())
        observers = {
            "primary": load_reward(paths["primary"], qualified["primary_file_sha256"])[0],
            "secondary": load_reward(paths["qualification"] / "secondary-observer.pt", qualified["secondary_file_sha256"])[0],
        }
        corpus = load_roles(paths["cache"], paths["manifest"], roles=("development",))
        write_json(output / "resident-load-cost.json", {"wall_ns": time.perf_counter_ns() - load_wall,
                   "cpu_ns": time.process_time_ns() - load_cpu,
                   "includes": "15 generator snapshots, all policy heads, both offline observers and source input corpus",
                   "amortized_into_episode_latency": False})
        report = benchmark_resident(models, bundles, corpus, observers, output / "benchmark", protocol,
                                    view_profile=registration["view_profile"])
        if any(file_sha(AREA / name) != value for name, value in registration["source_sha256"].items()):
            raise RuntimeError("Timing dependencies changed during execution")
        write_json(output / "result.json", {"status": "completed",
                   "benchmark_summary_sha256": file_sha(output / "benchmark/summary.json"),
                   "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
                   "benchmark": report})
    except BaseException as error:
        write_json(output / "failure.json", {"status": "failed", "error": repr(error),
                   "traceback": traceback.format_exc(), "wall_ns": time.perf_counter_ns() - wall,
                   "cpu_ns": time.process_time_ns() - cpu})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", type=Path)
    parser.add_argument("--view-profile", choices=("registered_three", "supplementary_all"), default="registered_three")
    names = ("cache", "manifest", "protocol", "training", "control", "qualification", "primary", "output")
    for name in names:
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    if args.child:
        execute(args.child)
        return
    if any(getattr(args, name) is None for name in names):
        parser.error("Complete frozen inputs and a new output directory are required")
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    for key in ("training", "control"):
        if json.loads((getattr(args, key) / "result.json").read_text())["status"] != "completed":
            raise ValueError("Complete upstream jobs before measuring resident latency")
    control_registration = json.loads((args.control / "registration.json").read_text())
    qualification = json.loads((args.qualification / "result.json").read_text())
    required = {"training_result_sha256": file_sha(args.training / "result.json"),
                "protocol_sha256": file_sha(args.protocol), "manifest_sha256": file_sha(args.manifest),
                "qualification_result_sha256": file_sha(args.qualification / "result.json")}
    if any(control_registration[key] != value for key, value in required.items()):
        raise ValueError("Timing inputs combine different training/control/qualification runs")
    if (control_registration["observer_file_sha256"]["primary"] != file_sha(args.primary)
            or control_registration["observer_file_sha256"]["secondary"] != qualification["secondary_file_sha256"]):
        raise ValueError("Timing observers differ from the frozen control experiment")
    for name in ("abc_recovery/runtime.py", "abc_recovery/emission.py", "abc_recovery/planning.py", "v7/model.py"):
        if file_sha(AREA / name) != control_registration["source_sha256"][name]:
            raise ValueError("Timing and evaluation generation laws differ")
    args.output.mkdir(parents=True, exist_ok=False)
    dependencies = ("abc_recovery/timing_run.py", "abc_recovery/timing.py", "abc_recovery/episodes.py",
                    "abc_recovery/control_run.py", "abc_recovery/training_run.py")
    registration = {"schema": "hepta.abc.resident-timing-process.v1", "registered_unix_ns": time.time_ns(),
        "paths": {name: str(getattr(args, name).resolve()) for name in names},
        "source_sha256": {name: file_sha(AREA / name) for name in dependencies},
        "completion_file_sha256": {key: file_sha(getattr(args, key) / "result.json") for key in ("training", "control")},
        "bound_input_sha256": {str(path.resolve()): file_sha(path) for path in
            (args.control / "registration.json", args.qualification / "result.json", args.protocol, args.manifest,
             args.primary, args.qualification / "secondary-observer.pt", args.protocol.with_name("protocol-amendment-002.json"))},
        "view_profile": args.view_profile,
        "protocol_sha256": file_sha(args.protocol),
        "known_training_and_tree_collection_processes_finished": True,
        "resident_latency_excludes_cold_load_and_offline_scoring": True}
    write_json(args.output / "registration.json", registration)
    with (args.output / "process.log").open("x") as log:
        child = subprocess.Popen([sys.executable, "-B", "-m", MODULE, "--child", str(args.output / "registration.json")],
                                 cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in child.stdout:
            log.write(line)
            log.flush()
            print(line, end="", flush=True)
        code = child.wait()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    write_json(args.output / "whole-process-cost.json", {"exit_code": code,
        "wall_ns": time.perf_counter_ns() - wall, "parent_cpu_ns": time.process_time_ns() - cpu,
        "child_cpu_seconds": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
        "child_peak_rss_bytes": after.ru_maxrss * 1024,
        "includes": "load, preparation, every resident request, physical outputs, offline scoring, ledgers, statistics, final report and child exit"})
    raise SystemExit(code)


if __name__ == "__main__":
    main()
