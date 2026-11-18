"""Durably own each bounded phase under the original shared GPU lock."""

import argparse
import fcntl
import os
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import time

import layout_context as ctx

LOCK = ctx.ARTIFACT / "research-round03-20261118-392934-b/WORKER.lock"
OLD_OWNER_SHA = "fc9ec2aa4600b8d554f4a9ef9ee802bf196cc68e8fad890a4090538497bb0ac1"


def retain(source, destination):
    if not source.exists():
        return {}
    if destination.exists():
        raise ValueError("retained artifact already exists")
    shutil.copytree(source, destination)
    rows = {}
    for item in sorted(source.rglob("*")):
        if item.is_file():
            relative = item.relative_to(source)
            if item.is_symlink() or ctx.sha(item) != ctx.sha(destination / relative):
                raise ValueError("retained file mismatch")
            rows[str(relative)] = {
                "sha256": ctx.sha(item),
                "bytes": item.stat().st_size,
            }
    ctx.write(destination.parent / (destination.name + "-RETENTION.json"), rows)
    return rows


def own(phase, binding):
    protocol = ctx.read(ctx.HERE / "prepared/PROTOCOL.json")
    deployment_path = ctx.WORK / "DEPLOYMENT.json"
    deployment = ctx.read(deployment_path)
    if ctx.sha(ctx.HERE / "prepared/PROTOCOL.json") != deployment["protocol_sha256"]:
        raise ValueError("published protocol changed")
    if deployment["files"] != protocol["candidate_files"]:
        raise ValueError("published source closure changed")
    for name, expected in deployment["files"].items():
        if ctx.sha(ctx.HERE / name) != expected:
            raise ValueError("published file changed: " + name)
    old_owner = ctx.load(
        "layout_original_owner_utilities",
        ctx.COLLECTION / "execution-code/owner.py",
        OLD_OWNER_SHA,
    )
    if phase == "training":
        stages = [
            ("calibration", ["--stage", "calibrate"], 1800),
            (
                "document_evidence",
                ["--stage", "train", "--mode", "document_evidence"],
                7200,
            ),
            (
                "native_feedback",
                ["--stage", "train", "--mode", "native_feedback"],
                7200,
            ),
            ("weights_freeze", ["--stage", "audit"], 300),
        ]
    else:
        panel = "A" if phase == "evaluation_A" else "B3"
        modes = (
            ("document_evidence", "native_feedback")
            if panel == "A"
            else ("P", "document_evidence", "native_feedback")
        )
        stages = [
            (mode, ["--stage", "evaluate", "--panel", panel, "--mode", mode], 3600)
            for mode in modes
        ]
        if panel == "B3":
            if binding is None:
                raise ValueError("B3 requires a released material binding")
            stages = [
                (name, arguments + ["--b3-binding", str(binding)], timeout)
                for name, arguments, timeout in stages
            ]
    owned = ctx.WORK / ("owned-" + phase + "-1")
    owned.mkdir(exist_ok=False)
    started, samples, exits = time.perf_counter(), [], []

    def sample():
        measured = old_owner.energy_sample()
        samples.append(measured)
        ctx.write(owned / ("ENERGY-" + str(len(samples) - 1) + ".json"), measured)

    try:
        if not LOCK.is_file() or LOCK.is_symlink():
            raise ValueError("existing shared lock required")
        with LOCK.open("a+b") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            ctx.write(
                owned / "INTENT.json",
                {
                    "source_commit": deployment["source_commit"],
                    "deployment_sha256": ctx.sha(deployment_path),
                    "protocol_sha256": deployment["protocol_sha256"],
                    "phase": phase,
                    "lock": str(LOCK),
                    "started_at_ns": time.time_ns(),
                    "automatic_retry": False,
                    "energy_sample_interval_seconds": 20,
                    "RAPL_scope": "whole host package window, including unrelated background work",
                },
            )
            for name, arguments, timeout in stages:
                folder = owned / name
                folder.mkdir()
                for filename, expected in deployment["files"].items():
                    if ctx.sha(ctx.HERE / filename) != expected:
                        raise ValueError("source changed before stage: " + filename)
                if name != "weights_freeze":
                    ctx.write(folder / "GPU_ADMISSION.json", old_owner.gpu_admission())
                command = [
                    ctx.PYTHON,
                    "-B",
                    str(ctx.HERE / "run_layout.py"),
                    "--source-commit",
                    deployment["source_commit"],
                    *arguments,
                ]
                env = {
                    key: value
                    for key, value in os.environ.items()
                    if key not in ("PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME")
                }
                env.update(
                    HF_HUB_OFFLINE="1",
                    TRANSFORMERS_OFFLINE="1",
                    HF_DATASETS_OFFLINE="1",
                    PYTHONDONTWRITEBYTECODE="1",
                    PYTHONNOUSERSITE="1",
                    TOKENIZERS_PARALLELISM="false",
                    OMP_NUM_THREADS="2",
                    OPENBLAS_NUM_THREADS="1",
                )
                tick, before = (
                    time.perf_counter(),
                    resource.getrusage(resource.RUSAGE_CHILDREN),
                )
                sample()
                timed_out = False
                with (
                    (folder / "STDOUT.txt").open("xb") as stdout,
                    (folder / "STDERR.txt").open("xb") as stderr,
                ):
                    child = subprocess.Popen(
                        command,
                        cwd=ctx.HERE,
                        env=env,
                        stdout=stdout,
                        stderr=stderr,
                        start_new_session=True,
                    )
                    ctx.write(
                        folder / "STARTED.json",
                        {
                            "pid": child.pid,
                            "process_group_id": child.pid,
                            "argv": command,
                            "started_at_ns": time.time_ns(),
                            "timeout_seconds": timeout,
                        },
                    )
                    while True:
                        try:
                            code = child.wait(timeout=20)
                            break
                        except subprocess.TimeoutExpired:
                            sample()
                            if time.perf_counter() - tick > timeout:
                                timed_out = True
                                os.killpg(child.pid, signal.SIGTERM)
                                try:
                                    code = child.wait(timeout=10)
                                except subprocess.TimeoutExpired:
                                    os.killpg(child.pid, signal.SIGKILL)
                                    code = child.wait(timeout=10)
                                break
                sample()
                after = resource.getrusage(resource.RUSAGE_CHILDREN)
                record = {
                    "stage": name,
                    "wait_returncode": code,
                    "timed_out": timed_out,
                    "exit_source": "subprocess.Popen.wait",
                    "finished_at_ns": time.time_ns(),
                    "wall_seconds": time.perf_counter() - tick,
                    "observed_child_cpu_seconds_including_energy_reads": after.ru_utime
                    + after.ru_stime
                    - before.ru_utime
                    - before.ru_stime,
                    "stdout_sha256": ctx.sha(folder / "STDOUT.txt"),
                    "stderr_sha256": ctx.sha(folder / "STDERR.txt"),
                    "full_system_cost_known": False,
                }
                ctx.write(folder / "EXIT.json", record)
                exits.append(record)
                print(ctx.data.canonical(record).decode(), flush=True)
                if phase == "training" and name in (
                    "calibration",
                    "document_evidence",
                    "native_feedback",
                ):
                    source = (
                        ctx.FIT_ROOT / "calibration"
                        if name == "calibration"
                        else ctx.FIT_ROOT / "training" / name
                    )
                    retain(source, ctx.WORK / "retained" / name)
                if phase == "training" and name == "weights_freeze" and code == 0:
                    frozen = ctx.FIT_ROOT / "WEIGHTS_FROZEN.json"
                    target = ctx.WORK / "retained/WEIGHTS_FROZEN.json"
                    with target.open("xb") as stream:
                        stream.write(frozen.read_bytes())
                    if ctx.sha(target) != ctx.sha(frozen):
                        raise ValueError("weight freeze retention differs")
                if code or timed_out:
                    ctx.write(owned / "FAILED.json", record)
                    return 1
            totals = []
            for index in (0, 1):
                rows = [sample["domains"][index] for sample in samples]
                if (
                    all(row.get("exit_code") == 0 for row in rows)
                    and len({sample["boot_id"] for sample in samples}) == 1
                    and len({row["max_energy_range_uj"] for row in rows}) == 1
                ):
                    maximum = rows[0]["max_energy_range_uj"]
                    deltas = [
                        (right["energy_uj"] - left["energy_uj"]) % maximum
                        for left, right in zip(rows, rows[1:])
                    ]
                    totals.append(
                        {
                            "domain_name": rows[0]["domain_name"],
                            "host_window_joules": sum(deltas) / 1e6,
                            "modular_deltas_uj": deltas,
                            "samples": len(rows),
                            "no_multiple_wraps_between_samples_assumption": True,
                        }
                    )
            ctx.write(
                owned / "COMPLETE.json",
                {
                    "status": "COMPLETE",
                    "phase": phase,
                    "stage_exits": exits,
                    "source_commit": deployment["source_commit"],
                    "finished_at_ns": time.time_ns(),
                    "owner_wall_seconds": time.perf_counter() - started,
                    "whole_host_cpu_package_energy": totals,
                    "energy_samples": len(samples),
                    "energy_scope": "whole host packages; no idle subtraction or model-only claim",
                    "gpu_energy_joules": None,
                    "network_energy_joules": None,
                    "monetary_cost": None,
                    "full_system_cost_known": False,
                    "nested_windows_are_not_additive": True,
                },
            )
        return 0
    except BaseException as error:
        ctx.write(
            owned / "WRAPPER_FAILED.json",
            {
                "error_type": type(error).__name__,
                "error": str(error),
                "stage_exits": exits,
                "energy_samples": len(samples),
                "wall_seconds": time.perf_counter() - started,
                "automatic_retry": False,
            },
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase", choices=("training", "evaluation_A", "evaluation_B3"), required=True
    )
    parser.add_argument("--b3-binding", type=Path)
    args = parser.parse_args()
    raise SystemExit(own(args.phase, args.b3_binding))
