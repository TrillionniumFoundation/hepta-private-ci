"""Own the original future 8+12+12 calls under the existing shared GPU lock."""

import argparse
import fcntl
import os
import resource
import signal
import subprocess
import sys
import time
import traceback

import run_future as future


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
        "scope": "Only this owner's known child process group.",
    }


def own(commit):
    ctx, _, _, _, _, declared = future.admission(commit)
    owned = ctx.WORK / "owned-evaluation-future-1"
    owned.mkdir(exist_ok=False)
    # The A runner retains its original executable and owner. This owner follows
    # its actual completed 24-call record; no A output is used to select tasks.
    a_complete = ctx.WORK / "owned-evaluation_A-1/COMPLETE.json"
    a_complete_sha = ctx.sha(a_complete)
    a_owner = ctx.read(a_complete)
    a_generations = sorted((ctx.WORK / "evaluation-A").rglob("GENERATION_STARTED.json"))
    a_generation_inventory = [
        {"path": str(path), "sha256": ctx.sha(path)} for path in a_generations
    ]
    ctx.require(
        a_owner["status"] == "COMPLETE"
        and a_owner["actual_new_generations"] == 24
        and len(a_generations) == 24,
        "original A 24-call owner is incomplete",
    )
    codec, _, _, _ = ctx.originals()
    sys.modules["native_sandbox"] = codec.native_module()
    utility_path = "/home/qian-qi/work/hepta-upstream-current-policy-20261118-2e9b/execution-code/owner.py"
    utility_sha = "fc9ec2aa4600b8d554f4a9ef9ee802bf196cc68e8fad890a4090538497bb0ac1"
    utilities = ctx.load("future_original_owner_utilities", utility_path, utility_sha)
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
            "phase": "evaluation_future",
            "source_commit": commit,
            "training_source_commit": future.TRAIN_COMMIT,
            "prior_A_complete_path": str(a_complete),
            "prior_A_complete_sha256": a_complete_sha,
            "prior_A_generation_started_files": a_generation_inventory,
            "panel_files": declared["panel_files"],
            "stage_exits": stages,
            "finished_at_ns": str(time.time_ns()),
            "owner_wall_seconds": time.perf_counter() - started,
            "energy_samples": len(energies),
            "whole_host_cpu_package_energy": totals,
            "energy_scope": "Whole-host packages including unrelated activity; not net model-only energy.",
            "gpu_energy_joules": None,
            "network_energy_joules": None,
            "monetary_cost": None,
            "full_system_cost_known": False,
            "nested_windows_not_additive": True,
            "old_NoUpdate_unchanged": True,
            "new_training_updates": 0,
        }

    with lock.open("a+b") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        ctx.write(
            owned / "INTENT.json",
            {
                "source_commit": commit,
                "started_at_ns": str(time.time_ns()),
                "panel_files": declared["panel_files"],
                "lock": str(lock),
                "automatic_retry": False,
                "new_generation_schedule": [
                    {"mode": mode, "calls": 8 if mode == "P" else 12}
                    for mode in future.MODES
                ],
                "new_generation_cap": 32,
                "prior_A_actual_calls": 24,
                "prior_A_complete_sha256": a_complete_sha,
                "prior_A_generation_started_files": a_generation_inventory,
                "global_new_generation_cap": 56,
                "energy_sample_seconds": 20,
                "cuda_memory_fraction": 0.70,
                "allocator": "expandable_segments:True",
            },
        )
        try:
            for mode in future.MODES:
                future.admission(commit)
                folder = owned / mode
                folder.mkdir()
                ctx.write(folder / "GPU_ADMISSION.json", utilities.gpu_admission())
                argv = [
                    ctx.PYTHON,
                    "-B",
                    str(future.HERE / "run_future.py"),
                    "--mode",
                    mode,
                    "--source-commit",
                    commit,
                ]
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
                        cwd=future.HERE,
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
                            "timeout_seconds": 1800,
                        },
                    )
                    timed_out = False
                    while True:
                        remaining = 1800 - (time.perf_counter() - began)
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
                    "CPU_scope": "Observed reaped owner children only; does not establish completeness for namespace grandchildren and is not added to their inner CPU receipts.",
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
                    "actual stage failed; no automatic retry",
                )
            count = sum(
                ctx.read(ctx.WORK / "evaluation-future" / mode / "RESULT.json")[
                    "actual_model_calls"
                ]
                for mode in future.MODES
            )
            ctx.require(
                count == 32
                and len(
                    list(
                        (ctx.WORK / "evaluation-future").rglob(
                            "GENERATION_STARTED.json"
                        )
                    )
                )
                == 32,
                "actual future generation count differs",
            )
            ctx.require(
                ctx.sha(a_complete) == a_complete_sha
                and sorted((ctx.WORK / "evaluation-A").rglob("GENERATION_STARTED.json"))
                == a_generations
                and all(
                    ctx.sha(row["path"]) == row["sha256"]
                    for row in a_generation_inventory
                ),
                "original A completed-call evidence changed during future evaluation",
            )
            result = complete("COMPLETE")
            result.update(
                actual_new_generations=count, actual_global_new_generations=24 + count
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
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    value = own(args.source_commit)
    print(value["status"], flush=True)
