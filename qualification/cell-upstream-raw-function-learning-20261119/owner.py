"""Own bounded fresh fits or A evaluation under the unchanged shared GPU lock."""

import argparse
import fcntl
import os
import resource
import shutil
import signal
import subprocess
import sys
import time
import traceback

import raw_context as ctx
import run_raw


def stop(child):
    if child is None or child.poll() is not None:
        return None
    os.killpg(child.pid, signal.SIGTERM)
    try:
        result = child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
        result = child.wait(timeout=10)
    return {
        "pid": child.pid,
        "actual_wait_returncode": result,
        "scope": "only this owner's known child process group",
    }


def own(phase, commit):
    run_raw.deployment(commit)
    owned = ctx.WORK / ("owned-" + phase + "-1")
    owned.mkdir(exist_ok=False)
    codec, _, _, _ = ctx.originals()
    sys.modules["native_sandbox"] = codec.native_module()
    utility_path = "/home/qian-qi/work/hepta-upstream-current-policy-20261118-2e9b/execution-code/owner.py"
    utility_sha = "fc9ec2aa4600b8d554f4a9ef9ee802bf196cc68e8fad890a4090538497bb0ac1"
    utilities = ctx.load(
        "raw_function_original_owner_utilities", utility_path, utility_sha
    )
    lock = ctx.ARTIFACT / "research-round03-20261118-392934-b/WORKER.lock"
    ctx.require(
        lock.is_file() and not lock.is_symlink(), "existing shared GPU lock required"
    )
    stages, energies = [], []
    child = None
    started = time.perf_counter()

    def energy():
        sample = utilities.energy_sample()
        energies.append(sample)
        ctx.write(owned / ("ENERGY-" + str(len(energies) - 1) + ".json"), sample)

    def complete(status):
        totals = []
        for index in (0, 1):
            values = [row["domains"][index] for row in energies]
            if (
                len(values) >= 2
                and all(row.get("exit_code") == 0 for row in values)
                and len({row["boot_id"] for row in energies}) == 1
                and len({row["max_energy_range_uj"] for row in values}) == 1
            ):
                maximum = values[0]["max_energy_range_uj"]
                deltas = [
                    (right["energy_uj"] - left["energy_uj"]) % maximum
                    for left, right in zip(values, values[1:])
                ]
                totals.append(
                    {
                        "domain_name": values[0]["domain_name"],
                        "host_window_joules": sum(deltas) / 1e6,
                        "modular_deltas_uj": deltas,
                        "samples": len(values),
                        "no_multiple_wraps_between_samples_assumption": True,
                    }
                )
        return {
            "status": status,
            "phase": phase,
            "source_commit": commit,
            "protocol_sha256": ctx.sha(ctx.HERE / "prepared/PROTOCOL.json"),
            "stage_exits": stages,
            "finished_at_ns": str(time.time_ns()),
            "owner_wall_seconds": time.perf_counter() - started,
            "energy_samples": len(energies),
            "whole_host_cpu_package_energy": totals,
            "energy_scope": "whole-host packages including unrelated activity; not net model-only energy",
            "gpu_energy_joules": None,
            "network_energy_joules": None,
            "monetary_cost": None,
            "full_system_cost_known": False,
            "nested_windows_not_additive": True,
            "old_NoUpdate_unchanged": True,
            "future_panel_calls": 0,
        }

    with lock.open("a+b") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        ctx.write(
            owned / "INTENT.json",
            {
                "phase": phase,
                "source_commit": commit,
                "protocol_sha256": ctx.sha(ctx.HERE / "prepared/PROTOCOL.json"),
                "started_at_ns": str(time.time_ns()),
                "lock": str(lock),
                "automatic_retry": False,
                "training_updates_planned": 64 if phase == "training" else 0,
                "generation_calls_planned": 24 if phase == "evaluation_A" else 0,
                "energy_sample_seconds": 20,
                "cuda_memory_fraction": 0.70,
                "allocator": "expandable_segments:True",
            },
        )
        schedule = (
            [("train", mode) for mode in run_raw.fit.MODES] + [("audit_weights", None)]
            if phase == "training"
            else [("evaluation_A", mode) for mode in run_raw.fit.MODES]
        )
        try:
            for action, mode in schedule:
                run_raw.deployment(commit)
                name = action + ("-" + mode if mode else "")
                folder = owned / name
                folder.mkdir()
                if action != "audit_weights":
                    ctx.write(folder / "GPU_ADMISSION.json", utilities.gpu_admission())
                argv = [
                    ctx.PYTHON,
                    "-B",
                    str(ctx.HERE / "run_raw.py"),
                    "--phase",
                    action,
                    "--source-commit",
                    commit,
                ]
                if mode:
                    argv += ["--mode", mode]
                environment = {
                    **os.environ,
                    "HF_HUB_OFFLINE": "1",
                    "TRANSFORMERS_OFFLINE": "1",
                    "TOKENIZERS_PARALLELISM": "false",
                    "OMP_NUM_THREADS": "2",
                    "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
                }
                environment.pop("PYTORCH_ALLOC_CONF", None)
                began = time.perf_counter()
                cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
                energy()
                with (
                    (folder / "STDOUT.txt").open("xb") as out,
                    (folder / "STDERR.txt").open("xb") as err,
                ):
                    child = subprocess.Popen(
                        argv,
                        cwd=ctx.HERE,
                        env=environment,
                        stdout=out,
                        stderr=err,
                        start_new_session=True,
                    )
                    ctx.write(
                        folder / "STARTED.json",
                        {
                            "argv": argv,
                            "pid": child.pid,
                            "started_at_ns": str(time.time_ns()),
                            "timeout_seconds": 3600
                            if action == "train"
                            else 1800
                            if action == "evaluation_A"
                            else 180,
                        },
                    )
                    timeout = (
                        3600
                        if action == "train"
                        else 1800
                        if action == "evaluation_A"
                        else 180
                    )
                    timed_out = False
                    while True:
                        remaining = timeout - (time.perf_counter() - began)
                        if remaining <= 0:
                            timed_out = True
                            stopped = stop(child)
                            code = (
                                stopped["actual_wait_returncode"]
                                if stopped
                                else child.wait()
                            )
                            break
                        try:
                            code = child.wait(timeout=min(20, remaining))
                            break
                        except subprocess.TimeoutExpired:
                            energy()
                energy()
                after = resource.getrusage(resource.RUSAGE_CHILDREN)
                receipt = {
                    "phase": action,
                    "mode": mode,
                    "pid": child.pid,
                    "wait_returncode": code,
                    "timed_out": timed_out,
                    "exit_source": "subprocess.Popen.wait",
                    "wall_seconds": time.perf_counter() - began,
                    "observed_child_cpu_seconds_including_energy_reads": after.ru_utime
                    + after.ru_stime
                    - cpu.ru_utime
                    - cpu.ru_stime,
                    "finished_at_ns": str(time.time_ns()),
                    "stdout_sha256": ctx.sha(folder / "STDOUT.txt"),
                    "stderr_sha256": ctx.sha(folder / "STDERR.txt"),
                    "full_system_cost_known": False,
                }
                ctx.write(folder / "EXIT.json", receipt)
                stages.append(receipt)
                child = None
                print(ctx.canonical(receipt).decode(), flush=True)
                ctx.require(
                    code == 0 and not timed_out,
                    "actual child stage failed; no automatic retry",
                )
                if action == "train":
                    destination = ctx.WORK / "retained/training" / mode
                    shutil.copytree(ctx.FIT_ROOT / "training" / mode, destination)
                    for original in (ctx.FIT_ROOT / "training" / mode).rglob("*"):
                        if original.is_file():
                            ctx.require(
                                ctx.sha(original)
                                == ctx.sha(
                                    destination
                                    / original.relative_to(
                                        ctx.FIT_ROOT / "training" / mode
                                    )
                                ),
                                "durable training copy differs",
                            )
                elif action == "audit_weights":
                    raw = (ctx.FIT_ROOT / "WEIGHTS_FROZEN.json").read_bytes()
                    with (ctx.WORK / "WEIGHTS_FROZEN.json").open("xb") as stream:
                        stream.write(raw)
            result = complete("COMPLETE")
            result["actual_optimizer_updates"] = (
                sum(
                    ctx.read(ctx.FIT_ROOT / "training" / mode / "TRAINING.json")[
                        "steps"
                    ]
                    for mode in run_raw.fit.MODES
                )
                if phase == "training"
                else 0
            )
            result["actual_new_generations"] = (
                sum(
                    ctx.read(ctx.WORK / "evaluation-A" / mode / "RESULT.json")[
                        "actual_model_calls"
                    ]
                    for mode in run_raw.fit.MODES
                )
                if phase == "evaluation_A"
                else 0
            )
            ctx.write(owned / "COMPLETE.json", result)
            return result
        except BaseException as error:
            stopped = stop(child)
            energy()
            ctx.write(
                owned / "FAILED.json",
                {
                    **complete("FAILED"),
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "traceback": traceback.format_exc(),
                    "owned_child_stop": stopped,
                    "partial_real_work_retained": True,
                },
            )
            raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, choices=("training", "evaluation_A"))
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    result = own(args.phase, args.source_commit)
    print(ctx.canonical(result).decode(), flush=True)
