#!/usr/bin/env python3
"""Actual original neural worker in the observed child, with one 600s budget.

Nine interpreter incarnations share one PID, one birth identity and one original
wait4/pidfd observer. Each calls the unmodified worker with at most 60 requests;
the original 64-request limit is retained. Labels never enter this process.
"""

import argparse
import ctypes
import gc
import hashlib
import importlib
import json
import os
from pathlib import Path
import resource
import signal
import socket
import stat
import sys
import threading
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hepta_smollm_execution_source_v1 as execution_source

SCHEMA = "hepta-neural-positive-forward-v1"
EXECUTION_SOURCE_PROFILE = os.environ.get("HEPTA_PAIRED_EXECUTION_PROFILE")
CHAIN = execution_source.selected_commit(
    "c96022b897c1235fdbdbfcfa32764403511c6aab", EXECUTION_SOURCE_PROFILE
)
COUNT = 512
BATCH = 60
LOADS = (COUNT + BATCH - 1) // BATCH
WORKER_SCHEMA = "hepta-smollm-neural-read-worker-v1"


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON member")
        result[key] = value
    return result


def checked(pin, maximum=8 * 1024 * 1024):
    require(type(pin) is dict and set(pin) == {"path", "sha256"}, "closed file pin")
    path = Path(pin["path"])
    require(path.is_absolute(), "absolute pinned path")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as source:
        metadata = os.fstat(source.fileno())
        require(
            stat.S_ISREG(metadata.st_mode) and 0 < metadata.st_size <= maximum,
            "bounded regular pinned file",
        )
        raw = source.read(maximum + 1)
    require(
        len(raw) == metadata.st_size and sha(raw) == pin["sha256"],
        "pinned bytes changed",
    )
    return raw


def object_at(pin, maximum=8 * 1024 * 1024):
    return json.loads(
        checked(pin, maximum),
        object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )


def save(path, value):
    raw = canonical(value)
    with Path(path).open("xb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    descriptor = os.open(Path(path).parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return {"path": str(path), "sha256": sha(raw)}


def arm_parent(expected):
    """Bind this helper to its actual birth parent; never signal another PID."""
    require(
        type(expected) is int and expected > 1 and os.getppid() == expected,
        "original parent already lost",
    )
    libc = ctypes.CDLL(None, use_errno=True)
    require(libc.prctl(1, signal.SIGKILL, 0, 0, 0) == 0, "PDEATHSIG unavailable")
    require(os.getppid() == expected, "parent died while arming")


def birth():
    raw = Path("/proc/self/stat").read_text()
    return {
        "pid": os.getpid(),
        "start_ticks": int(raw[raw.rfind(")") + 2 :].split()[19]),
    }


def process_cost():
    value = resource.getrusage(resource.RUSAGE_SELF)
    return {"cpu_ns": time.process_time_ns(), "peak_rss_bytes": value.ru_maxrss * 1024}


def exchange(directory_fd, value, deadline):
    require(time.monotonic_ns() < deadline, "single phase deadline")
    raw = canonical(value)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(
            min(10, max(0.001, (deadline - time.monotonic_ns()) / 1e9))
        )
        # Same-process retained directory FD avoids sun_path length and the
        # original worker's chdir. No shared pathname listener is introduced.
        connection.connect(f"/proc/self/fd/{directory_fd}/model.sock")
        connection.sendall(raw + b"\n")
        if value.get("stop") is True:
            return None
        response = bytearray()
        while len(response) <= 128 * 1024:
            part = connection.recv(min(4096, 128 * 1024 + 1 - len(response)))
            if not part:
                break
            response.extend(part)
            if b"\n" in part:
                break
    require(
        0 < len(response) <= 128 * 1024
        and response.endswith(b"\n")
        and response.count(b"\n") == 1,
        "bounded original response frame",
    )
    return raw, bytes(response[:-1]), json.loads(response, object_pairs_hook=unique)


def run(args):
    source = Path(__file__).resolve()
    config_pin = {"path": str(Path(args.input).resolve()), "sha256": args.input_sha256}
    config = object_at(config_pin)
    require(
        set(config)
        == {
            "schema",
            "source_sha256",
            "chain",
            "chain_commit",
            "sources",
            "materials",
            "parent",
            "worker_plan",
            "tasks",
            "output",
            "owner_pid",
            "deadline_monotonic_ns",
            "budget",
            "phase_id",
            "model",
            "window_id",
        },
        "closed actual forward input",
    )
    require(
        config["schema"] == SCHEMA
        and sha(source.read_bytes()) == config["source_sha256"]
        and config["chain_commit"] == CHAIN
        and config["budget"] == {"wall_seconds": 600, "rss_bytes": 8 * 1024**3},
        "original source and whole-phase budget",
    )
    arm_parent(config["owner_pid"])
    own_birth = birth()
    deadline = config["deadline_monotonic_ns"]
    require(
        type(deadline) is int and time.monotonic_ns() < deadline,
        "phase already expired",
    )
    chain = Path(config["chain"])
    require(
        chain.is_absolute() and Path(config["materials"]).is_absolute(),
        "absolute runtime",
    )
    for relative, digest in config["sources"].items():
        checked({"path": str(chain / relative), "sha256": digest}, 4 * 1024 * 1024)
    execution_source.verify_selected(chain, EXECUTION_SOURCE_PROFILE)
    sys.path.insert(0, str(chain / "scripts"))
    worker = importlib.import_module("llm_neural_read_worker")
    require(worker.MAX_REQUESTS == 64, "original worker request cap")
    parent = worker.inherited.validate_parent(object_at(config["parent"]))
    plan = object_at(config["worker_plan"])
    require(
        plan["parent"] == parent
        and plan["worker_source"] == sha(Path(worker.__file__).read_bytes())
        and plan["inherited_sources"] == worker.inherited.source_pins(),
        "original worker plan",
    )
    tasks = object_at(config["tasks"])
    require(
        type(tasks) is list
        and len(tasks) == COUNT
        and all(type(row) is dict and set(row) == {"id", "prompt"} for row in tasks)
        and len({row["id"] for row in tasks}) == COUNT,
        "512 distinct label-free tasks",
    )
    root = Path(config["output"])
    require(root.is_absolute(), "absolute observed child output")
    rows, chain_pins, index = [], [], 0
    if args.resume:
        resume_pin = {
            "path": str(Path(args.resume).resolve()),
            "sha256": args.resume_sha256,
        }
        resume = object_at(resume_pin, 32 * 1024 * 1024)
        require(
            resume["schema"] == SCHEMA + "-prefix"
            and resume["input"] == config_pin
            and resume["birth"] == own_birth
            and resume["source_sha256"] == config["source_sha256"],
            "same-source same-birth continuation",
        )
        index, rows, chain_pins = resume["next_batch"], resume["rows"], resume["chain"]
        require(
            type(index) is int
            and 1 <= index < LOADS
            and len(rows) == index * BATCH
            and [row["task"] for row in rows]
            == [task["id"] for task in tasks[: len(rows)]],
            "exact completed prefix",
        )
        for pin in chain_pins:
            checked(pin, 32 * 1024 * 1024)
        cost = process_cost()
        require(
            cost["cpu_ns"] >= resume["cost"]["cpu_ns"]
            and cost["peak_rss_bytes"] >= resume["cost"]["peak_rss_bytes"],
            "process costs reset",
        )
        chain_pins.append(resume_pin)
    else:
        root.mkdir(mode=0o700, parents=False, exist_ok=False)
    directory = root / f"worker-{index}"
    directory.mkdir(mode=0o700)
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    failure, produced, ready_value = [], [], []
    finished = threading.Event()

    def client():
        try:
            ready_path = directory / "ready.json"
            while not ready_path.is_file():
                require(
                    not finished.is_set() and time.monotonic_ns() < deadline,
                    "worker exited or phase expired before ready",
                )
                time.sleep(0.005)
            ready_raw = ready_path.read_bytes()
            ready = json.loads(ready_raw, object_pairs_hook=unique)
            require(
                ready["schema"] == WORKER_SCHEMA
                and ready["actual_loaded_parent"] == parent["adapter"]
                and ready["file_sha256"] == parent["file_sha256"]
                and ready["contract"] == parent["contract"]
                and ready["generation"] == parent["generation"]
                and ready["source_pins"] == plan["inherited_sources"]
                and ready["worker_source"] == plan["worker_source"]
                and ready["actions"] == plan["actions"]
                and ready["authority"] == worker.inherited.NO_AUTHORITY,
                "actual loaded model binding",
            )
            ready_value.append(
                {
                    "path": str(ready_path),
                    "sha256": sha(ready_raw),
                    "observation": ready,
                }
            )
            for task in tasks[index * BATCH : (index + 1) * BATCH]:
                at = time.time_ns() // 1000
                request, response_raw, response = exchange(
                    directory_fd,
                    {
                        "schema": "hepta-smollm-inference-input-v1",
                        "request_id": task["id"],
                        "prompt": task["prompt"],
                    },
                    deadline,
                )
                require(
                    response["schema"] == WORKER_SCHEMA
                    and response["request_id"] == task["id"]
                    and response["input_sha256"] == sha(request)
                    and response["file_sha256"] == parent["file_sha256"]
                    and response["artifact"] == parent["adapter"]
                    and response["contract"] == parent["contract"]
                    and response["profile"]
                    == "hepta-smollm-single-token-action-score-v1"
                    and response["action_ids"]
                    == [action["action_id"] for action in plan["actions"]]
                    and len(response["scores_q32"]) == 2
                    and all(
                        type(score) is int and -(1 << 63) <= score < (1 << 63)
                        for score in response["scores_q32"]
                    )
                    and response["authority"] == worker.inherited.NO_AUTHORITY,
                    "actual forward response",
                )
                produced.append(
                    {
                        "task": task["id"],
                        "query_sha256": sha(task["prompt"].encode()),
                        "request_bytes_hex": request.hex(),
                        "response_bytes_hex": response_raw.hex(),
                        "response_sha256": sha(response_raw),
                        "response": response,
                        "decision_at": at,
                        "observed_at": time.time_ns() // 1000,
                    }
                )
        except BaseException as error:
            failure.append(f"{type(error).__name__}: {error}")
        finally:
            if ready_value:
                try:
                    exchange(
                        directory_fd, {"schema": WORKER_SCHEMA, "stop": True}, deadline
                    )
                except BaseException as error:
                    failure.append(f"stop: {type(error).__name__}: {error}")

    client_thread = threading.Thread(target=client, name="actual-neural-forward-client")
    client_thread.start()
    try:
        worker.worker(
            SimpleNamespace(
                plan=config["worker_plan"]["path"],
                plan_sha256=config["worker_plan"]["sha256"],
                output=str(directory),
                materials=config["materials"],
            )
        )
    finally:
        finished.set()
        client_thread.join(timeout=12)
        os.close(directory_fd)
    require(
        not client_thread.is_alive() and not failure,
        "joined original worker/client: " + repr(failure),
    )
    require(
        len(produced) == len(tasks[index * BATCH : (index + 1) * BATCH]),
        "complete batch",
    )
    rows.extend(produced)
    gc.collect()
    libc = ctypes.CDLL(None, use_errno=True)
    require(hasattr(libc, "malloc_trim"), "explicit glibc live-release capability")
    libc.malloc_trim(0)
    if len(rows) < COUNT:
        pin = save(
            root / f"prefix-{index + 1}.json",
            {
                "schema": SCHEMA + "-prefix",
                "input": config_pin,
                "source_sha256": config["source_sha256"],
                "birth": own_birth,
                "next_batch": index + 1,
                "rows": rows,
                "chain": chain_pins,
                "cost": process_cost(),
                "actual_ready": ready_value[0],
            },
        )
        os.execve(
            sys.executable,
            [
                sys.executable,
                "-I",
                "-B",
                str(source),
                "--input",
                config_pin["path"],
                "--input-sha256",
                config_pin["sha256"],
                "--resume",
                pin["path"],
                "--resume-sha256",
                pin["sha256"],
            ],
            os.environ.copy(),
        )
    require(
        len(rows) == COUNT and index == LOADS - 1 and len(chain_pins) == LOADS - 1,
        "complete nine-load phase",
    )
    save(
        root / "forward-result.json",
        {
            "schema": SCHEMA + "-result",
            "input": config_pin,
            "birth": own_birth,
            "source_sha256": config["source_sha256"],
            "phase_id": config["phase_id"],
            "model": config["model"],
            "window_id": config["window_id"],
            "parent": parent,
            "tasks": config["tasks"],
            "rows": rows,
            "prefix_chain": chain_pins,
            "loads": LOADS,
            "forwards": COUNT,
            "last_ready": ready_value[0],
            "cost": process_cost(),
            "budget": config["budget"],
            "supervisor_restarted": False,
            "scope": "actual unmodified neural worker forwards inside one direct observed child; no qualification or installation authority",
        },
    )


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--input-sha256", required=True)
    parser.add_argument("--resume")
    parser.add_argument("--resume-sha256")
    run(parser.parse_args())
