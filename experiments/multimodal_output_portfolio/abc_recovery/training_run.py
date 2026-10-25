"""Run the frozen five-seed, three-arm training census with full process cost."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
import traceback


MODULE = "experiments.multimodal_output_portfolio.abc_recovery.training_run"
AREA = Path(__file__).resolve().parents[1]
ROOT = AREA.parents[1]
ORIGINAL_SUPERVISED_SHA = "12cd2560b03acd23cdf52d56aedc025bbc2663d58d6b7979fffd26a1fbc7c464"


def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def pins():
    dependencies = {
        "abc_recovery": ("training_run", "output_training", "warm_start", "runtime", "emission", "media"),
        "v7": ("data", "model", "snapshot", "sources", "training", "evaluation"),
        "v6": ("data", "neural", "observer"),
    }
    return {f"{directory}/{name}.py": file_sha(AREA / directory / f"{name}.py")
            for directory, names in dependencies.items() for name in names}


def freeze(args):
    protocol = json.loads(args.protocol.read_text())
    qualification = json.loads(args.qualification.read_text())
    if (protocol["training_seeds"] != [17, 29, 43, 59, 71]
            or protocol["training"]["arms"] != ["sft_continuation", "output_mean", "output_ndu"]
            or file_sha(args.manifest) != protocol["source_manifest_file_sha256"]
            or qualification["protocol_sha256"] != file_sha(args.protocol)
            or not qualification["both_qualified"]
            or qualification["primary_file_sha256"] != file_sha(args.primary)
            or file_sha(args.warm_start) != ORIGINAL_SUPERVISED_SHA):
        raise ValueError("Frozen protocol, source, qualification or original warm start differs")
    amendment = args.protocol.with_name("protocol-amendment-001.json")
    if json.loads(amendment.read_text())["base_protocol_sha256"] != file_sha(args.protocol):
        raise ValueError("Prospective amendment is not bound to this protocol")
    args.output.mkdir(parents=True, exist_ok=False)
    registration = {
        "schema": "hepta.abc.training-census-registration.v1",
        "registered_unix_ns": time.time_ns(), "source_sha256": pins(),
        "paths": {name: str(getattr(args, name).resolve()) for name in
                  ("cache", "manifest", "protocol", "qualification", "primary", "warm_start", "output")},
        "files_sha256": {name: file_sha(getattr(args, name)) for name in
                         ("manifest", "protocol", "qualification", "primary", "warm_start")},
        "amendment_sha256": file_sha(amendment),
        "primary_parameter_sha256": qualification["observers"]["primary"]["parameter_sha256"],
        "deterministic_algorithms": False,
        "source_roles_read": ["train"],
        "warm_start_seed17": "reuse exactly recovered published S checkpoint; its measured recovery cost is separate",
        "other_warm_starts": "matched S-only 2000-update training, with complete optimizer checkpoints",
        "fine_tuning_census": {"training_seeds": protocol["training_seeds"], "arms": protocol["training"]["arms"]},
        "new_task_outcomes_opened": False,
    }
    write_json(args.output / "registration.json", registration)
    return args.output / "registration.json"


def execute(registration_path):
    registration = json.loads(Path(registration_path).read_text())
    paths = {name: Path(value) for name, value in registration["paths"].items()}
    output = paths["output"]
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    completed = []
    try:
        if pins() != registration["source_sha256"] or any(file_sha(paths[name]) != sha
                    for name, sha in registration["files_sha256"].items()):
            raise ValueError("Prospectively frozen training inputs changed")
        import torch
        from ..v7.evaluation import load_reward
        from ..v7.snapshot import Snapshot
        from ..v7.sources import load_roles
        from .output_training import fit_arm
        from .warm_start import fit_supervised
        protocol = json.loads(paths["protocol"].read_text())
        protocol["primary_observer_parameter_sha256"] = registration["primary_parameter_sha256"]
        torch.set_num_threads(protocol["threads"])
        torch.use_deterministic_algorithms(registration["deterministic_algorithms"])
        corpus = load_roles(paths["cache"], paths["manifest"], roles=("train",))
        observer, _ = load_reward(paths["primary"], registration["files_sha256"]["primary"])
        for seed in protocol["training_seeds"]:
            if seed == 17:
                warm = Snapshot.load(paths["warm_start"], expected_file_sha256=ORIGINAL_SUPERVISED_SHA)
                warm_report = {"reused": True, "file_sha256": ORIGINAL_SUPERVISED_SHA,
                               "source": str(paths["warm_start"]), "new_optimizer_updates": 0}
            else:
                def progress(profile, row):
                    print(json.dumps({"phase": "warm_start", "seed": seed, **row}), flush=True)
                warm, warm_report = fit_supervised(corpus, output / f"seed-{seed}" / "warm_start",
                                                   seed, protocol, progress=progress)
            for arm in protocol["training"]["arms"]:
                destination = output / f"seed-{seed}" / arm
                snapshot, report = fit_arm(warm, corpus, observer, destination, seed, arm, protocol)
                row = {"seed": seed, "arm": arm, "snapshot_sha256": snapshot.fingerprint,
                       "model_file_sha256": report["checkpoint_file_sha256"],
                       "summary_file_sha256": file_sha(destination / "summary.json"),
                       "model_path": str(destination / "model.pt"),
                       "warm_start": warm_report if arm == protocol["training"]["arms"][0] else "same seed warm start",
                       "actual_output_score_gradient": report["output_score_gradient_abs_sum_max"]}
                completed.append(row)
                write_json(output / f"completed-{len(completed):02d}.json", row)
                print(json.dumps({"phase": "arm_complete", "seed": seed, "arm": arm,
                                  "snapshot": snapshot.fingerprint}), flush=True)
        if pins() != registration["source_sha256"]:
            raise RuntimeError("Training dependencies changed during execution")
        write_json(output / "result.json", {"status": "completed", "models": completed,
                   "model_count": len(completed), "optimizer_updates_fine_tuning": 15 * 400,
                   "terminal_training_output_rows": 15 * 400 * 16 * 8,
                   "execution_wall_ns": time.perf_counter_ns() - wall,
                   "execution_cpu_ns": time.process_time_ns() - cpu,
                   "new_task_outcomes_opened": False})
    except BaseException as error:
        write_json(output / "failure.json", {"status": "failed", "error": repr(error),
                   "traceback": traceback.format_exc(), "completed_models": len(completed),
                   "wall_ns": time.perf_counter_ns() - wall,
                   "cpu_ns": time.process_time_ns() - cpu})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", type=Path)
    for name in ("cache", "manifest", "protocol", "qualification", "primary", "warm-start", "output"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    if args.child:
        execute(args.child)
        return
    if any(getattr(args, name) is None for name in
           ("cache", "manifest", "protocol", "qualification", "primary", "warm_start", "output")):
        parser.error("All frozen training inputs and a new output directory are required")
    start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    registration = freeze(args)
    with (args.output / "process.log").open("x") as log:
        child = subprocess.Popen([sys.executable, "-B", "-m", MODULE, "--child", str(registration)],
                                 cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in child.stdout:
            log.write(line)
            log.flush()
            print(line, end="", flush=True)
        returncode = child.wait()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    write_json(args.output / "whole-process-cost.json", {
        "schema": "hepta.abc.training-process-cost.v1", "exit_code": returncode,
        "wall_ns": time.perf_counter_ns() - start_wall,
        "parent_cpu_ns": time.process_time_ns() - start_cpu,
        "child_cpu_seconds": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
        "child_peak_rss_bytes": after.ru_maxrss * 1024,
        "includes": "registration, imports, data loading, actual training and checkpoints, media IO, scorers, ledgers, hashes, final reports and child exit",
        "failed_attempt_cost_retained": returncode != 0,
    })
    raise SystemExit(returncode)


if __name__ == "__main__":
    main()
