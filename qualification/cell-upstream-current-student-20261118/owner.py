"""Own two frozen collection processes under the original GPU lock, with raw costs."""

import argparse
import csv
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("xb") as stream:
        stream.write(
            json.dumps(value, sort_keys=True, allow_nan=False).encode() + b"\n"
        )
        stream.flush()
        os.fsync(stream.fileno())


def energy_sample():
    started = time.perf_counter()
    result = {
        "at_unix_ns": time.time_ns(),
        "monotonic_ns": time.monotonic_ns(),
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "scope": "whole-host CPU package counters; includes concurrent host work, not model-only energy",
        "domains": [],
        "gpu_energy_joules": None,
        "network_energy_joules": None,
        "monetary_cost": None,
    }
    for index in (0, 1):
        root = Path("/sys/class/powercap") / ("intel-rapl:" + str(index))
        command = ["/usr/bin/sudo", "-n", "/usr/bin/cat", str(root / "energy_uj")]
        row = {"path": str(root), "argv": command}
        try:
            measured = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=5,
                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            )
            row.update(
                exit_code=measured.returncode,
                stdout=measured.stdout,
                stderr=measured.stderr,
            )
            if measured.returncode == 0:
                row.update(
                    energy_uj=int(measured.stdout.strip()),
                    max_energy_range_uj=int(
                        (root / "max_energy_range_uj").read_text().strip()
                    ),
                    domain_name=(root / "name").read_text().strip(),
                )
        except BaseException as error:
            row.update(error_type=type(error).__name__, error=str(error))
        result["domains"].append(row)
    result["probe_wall_seconds"] = time.perf_counter() - started
    return result


def gpu_admission():
    record = subprocess.run(
        [
            "/usr/bin/nvidia-smi",
            "--query-compute-apps=pid,used_gpu_memory",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    )
    rows = []
    for values in csv.reader(record.stdout.splitlines()):
        if not values:
            continue
        pid = int(values[0].strip())
        try:
            name = (Path("/proc") / str(pid) / "comm").read_text().strip()
        except FileNotFoundError:
            continue
        rows.append({"pid": pid, "name": name, "gpu_memory_mib": values[1].strip()})
    unexpected = [
        row
        for row in rows
        if row["name"]
        not in ("chrome", "Telegram", "Xorg", "gnome-shell", "kwin_wayland")
    ]
    if unexpected:
        raise ValueError(
            "another GPU compute owner is active: " + json.dumps(unexpected)
        )
    free = subprocess.run(
        [
            "/usr/bin/nvidia-smi",
            "--query-gpu=memory.free",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    )
    if int(free.stdout.splitlines()[0]) < 4096:
        raise ValueError("insufficient unclaimed GPU memory")
    return {
        "active_existing_graphics": rows,
        "memory_free_mib": int(free.stdout.splitlines()[0]),
    }


def main(root):
    code = root / "execution-code"
    deployment = json.loads((root / "FINAL_DEPLOYMENT.json").read_text())
    owned = root / "owned-students-1"
    owned.mkdir(exist_ok=False)
    protocol = json.loads((root / "prepared/PROTOCOL.json").read_text())
    assert protocol["student_calls"] == 16 and protocol["total_model_call_cap"] == 24
    assert sha(root / "prepared/PROTOCOL.json") == deployment["protocol_sha256"]
    assert sha(root / "prepared/TASKS.json") == protocol["task_records_sha256"]
    lock = Path(
        "/dev/shm/hepta-cell-experiments-v3-20261116-0c078a/research-round03-20261118-392934-b/WORKER.lock"
    )
    assert lock.is_file() and not lock.is_symlink()
    samples, exits = [], []
    started = time.perf_counter()
    try:
        with lock.open("a+b") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            write(
                owned / "INTENT.json",
                {
                    "source_commit": deployment["source_commit"],
                    "deployment_sha256": sha(root / "FINAL_DEPLOYMENT.json"),
                    "protocol_sha256": deployment["protocol_sha256"],
                    "lock": str(lock),
                    "planned_student_calls": 16,
                    "planned_calls_per_model": 8,
                    "new_training_updates": 0,
                    "started_at_ns": time.time_ns(),
                    "automatic_retry": False,
                    "energy_sample_interval_seconds": 20,
                },
            )
            for mode in ("P", "C"):
                for name, expected in deployment["files"].items():
                    assert sha(code / name) == expected, (
                        "published source changed: " + name
                    )
                folder = owned / mode
                folder.mkdir(exist_ok=False)
                write(folder / "GPU_ADMISSION.json", gpu_admission())
                sample = energy_sample()
                samples.append(sample)
                write(owned / ("ENERGY-" + str(len(samples) - 1) + ".json"), sample)
                command = [
                    "/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a/venv/bin/python",
                    "-I",
                    "-B",
                    str(code / "run_students.py"),
                    "--root",
                    str(root),
                    "--mode",
                    mode,
                    "--source-commit",
                    deployment["source_commit"],
                ]
                env = dict(
                    os.environ,
                    HF_HUB_OFFLINE="1",
                    TRANSFORMERS_OFFLINE="1",
                    HF_DATASETS_OFFLINE="1",
                    PYTHONDONTWRITEBYTECODE="1",
                    TOKENIZERS_PARALLELISM="false",
                    OMP_NUM_THREADS="2",
                    OPENBLAS_NUM_THREADS="1",
                )
                tick, cpu = (
                    time.perf_counter(),
                    resource.getrusage(resource.RUSAGE_CHILDREN),
                )
                timed_out = False
                with (
                    (folder / "STDOUT.txt").open("xb") as stdout,
                    (folder / "STDERR.txt").open("xb") as stderr,
                ):
                    child = subprocess.Popen(
                        command,
                        cwd=code,
                        env=env,
                        stdout=stdout,
                        stderr=stderr,
                        start_new_session=True,
                    )
                    write(
                        folder / "STARTED.json",
                        {
                            "pid": child.pid,
                            "process_group_id": child.pid,
                            "argv": command,
                            "started_at_ns": time.time_ns(),
                        },
                    )
                    while True:
                        try:
                            returncode = child.wait(timeout=20)
                            break
                        except subprocess.TimeoutExpired:
                            sample = energy_sample()
                            samples.append(sample)
                            write(
                                owned / ("ENERGY-" + str(len(samples) - 1) + ".json"),
                                sample,
                            )
                            if time.perf_counter() - tick > 1800:
                                timed_out = True
                                os.killpg(child.pid, signal.SIGTERM)
                                try:
                                    returncode = child.wait(timeout=10)
                                except subprocess.TimeoutExpired:
                                    os.killpg(child.pid, signal.SIGKILL)
                                    returncode = child.wait(timeout=10)
                                break
                after = resource.getrusage(resource.RUSAGE_CHILDREN)
                sample = energy_sample()
                samples.append(sample)
                write(owned / ("ENERGY-" + str(len(samples) - 1) + ".json"), sample)
                exit_record = {
                    "mode": mode,
                    "wait_returncode": returncode,
                    "timed_out": timed_out,
                    "exit_source": "subprocess.Popen.wait",
                    "wall_seconds": time.perf_counter() - tick,
                    "completed_children_cpu_seconds_including_energy_reads": after.ru_utime
                    + after.ru_stime
                    - cpu.ru_utime
                    - cpu.ru_stime,
                    "stdout_sha256": sha(folder / "STDOUT.txt"),
                    "stderr_sha256": sha(folder / "STDERR.txt"),
                    "full_system_cost_known": False,
                    "nested_windows_are_not_additive": True,
                }
                write(folder / "EXIT.json", exit_record)
                exits.append(exit_record)
                print(json.dumps(exit_record), flush=True)
                if returncode or timed_out:
                    write(owned / "FAILED.json", exit_record)
                    return 1
                result = json.loads(
                    (root / "results" / mode / "RESULT.json").read_text()
                )
                assert (
                    result["status"] == "COMPLETE" and result["actual_model_calls"] == 8
                )
                assert (
                    len(
                        list(
                            (root / "results" / mode).glob(
                                "*/GENERATION_STARTED-*.json"
                            )
                        )
                    )
                    == 8
                )
            totals = []
            for index in (0, 1):
                rows = [sample["domains"][index] for sample in samples]
                if (
                    all(row.get("exit_code") == 0 for row in rows)
                    and len({sample["boot_id"] for sample in samples}) == 1
                ):
                    ranges = {row["max_energy_range_uj"] for row in rows}
                    assert len(ranges) == 1
                    maximum = ranges.pop()
                    deltas = [
                        (right["energy_uj"] - left["energy_uj"]) % maximum
                        for left, right in zip(rows, rows[1:])
                    ]
                    totals.append(
                        {
                            "domain_name": rows[0]["domain_name"],
                            "host_window_joules": sum(deltas) / 1e6,
                            "counter_range_uj": maximum,
                            "samples": len(rows),
                            "modular_deltas_uj": deltas,
                            "unobservable_multiple_wraps_between_samples_excluded_assumption": True,
                        }
                    )
            result = {
                "status": "COLLECTION_COMPLETE",
                "source_commit": deployment["source_commit"],
                "actual_student_model_calls": 16,
                "new_training_updates": 0,
                "stage_exits": exits,
                "whole_host_cpu_package_energy": totals,
                "energy_samples": len(samples),
                "energy_scope": "entire host package window; no idle subtraction or model-only energy claim",
                "gpu_energy_joules": None,
                "network_energy_joules": None,
                "monetary_cost": None,
                "owner_wall_seconds": time.perf_counter() - started,
                "full_system_cost_known": False,
                "research_NoUpdate_retained": True,
                "scientific_confirmation_qualified": False,
                "native_adoption": False,
            }
            write(owned / "COMPLETE.json", result)
        return 0
    except BaseException as error:
        write(
            owned / "WRAPPER_FAILED.json",
            {
                "error_type": type(error).__name__,
                "error": str(error),
                "completed_stages": len(exits),
                "energy_samples": len(samples),
                "owner_wall_seconds": time.perf_counter() - started,
                "automatic_retry": False,
            },
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    raise SystemExit(main(parser.parse_args().root.resolve(strict=True)))
