"""Own one newly frozen E4 control run while retaining the unchanged E2 candidate."""

import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import tarfile
import time

ROOT = Path("/dev/shm/hepta-cell-experiments-v3-20261116-0c078a")
RUNTIME = Path("/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a")
MODULE = ROOT / "round03-source-20261118-392934-b"
PREVIOUS = ROOT / "operations/round03-owned-20261118-392934-b"
COMPARISON = ROOT / "research-round03-20261118-392934-b/COMPARISON.json"
SOURCE = ROOT / "e4-controls-source-20261118-392934"
OUTPUT = ROOT / "research-e4-controls-20261118-392934"
OWNED = ROOT / "operations/e4-controls-owned-20261118-392934"
ARCHIVE = RUNTIME / "operations/e4-controls-checkpoint-20261118-392934"


def sha(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            result.update(block)
    return result.hexdigest()


def exact_module(path, expected, name):
    if sha(path) != expected:
        raise ValueError("frozen source differs: " + str(path))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def admission(expected, full):
    protocol_path = SOURCE / "PROTOCOL.json"
    if sha(protocol_path) != expected:
        raise ValueError("explicit protocol SHA differs")
    protocol = json.loads(protocol_path.read_text())
    if {p.name for p in SOURCE.iterdir()} != set(protocol["source_sha256"]) | {
        "PROTOCOL.json"
    }:
        raise ValueError("additional source inventory differs")
    for name, value in protocol["source_sha256"].items():
        if sha(SOURCE / name) != value:
            raise ValueError("additional source bytes differ")
    if (
        Path(__file__).resolve() != SOURCE / "run_extended_circuit_once.py"
        or sha(Path(__file__))
        != protocol["source_sha256"]["run_extended_circuit_once.py"]
    ):
        raise ValueError("executing launcher is not the frozen source file")
    sequence = PREVIOUS / "SEQUENCE.json"
    if (
        sha(sequence)
        != "f273cbd7e7f8921ac3d2bcbdcea4b596bf39f27acd72b064a4ab3231d140056c"
    ):
        raise ValueError("original owner sequence differs")
    release = json.loads((PREVIOUS / "SEQUENCE_COMPLETE.json").read_text())
    if (
        release.get("all_jobs_wait_returncode_zero") is not True
        or release.get("GPU_released") is not True
    ):
        raise ValueError("E2 owner has not released its GPU")
    guard_path = ROOT / "operations/launch_round03_392934_b.py"
    guard = exact_module(
        guard_path,
        "d312c41a5fa1a2fda266c1e2ceb8c9033eb67f5b582dbe4a0b2806d8c276fbac",
        "e4_b_guard",
    )
    if full:
        guard.verify_full_closure()
    inventory = MODULE / "SOURCE.json"
    if (
        sha(inventory)
        != "928aaa75c75023954432302b46d2064311ccf5e290e3e605e82193e4c7ba7814"
    ):
        raise ValueError("original B source inventory differs")
    for item in json.loads(inventory.read_text())["files"]:
        path = MODULE / "online_v4" / item["path"]
        if path.stat().st_size != item["bytes"] or sha(path) != item["sha256"]:
            raise ValueError("original B module differs")
    if (
        sha(COMPARISON)
        != "0df69a16fce8cd24f6a1cf0fe65b552b57e35da7bc381b7246408585a17169ce"
    ):
        raise ValueError("original B comparison differs")
    wrapper = ROOT / "operations/launch_qwen_research_owned_v1_02.py"
    owner = exact_module(
        wrapper,
        json.loads(sequence.read_text())["owned_wrapper_sha256"],
        "e4_original_owner",
    )
    return protocol, guard, owner, wrapper


def worker(expected):
    protocol, guard, owner, wrapper = admission(expected, full=True)
    source_inventory = json.loads((MODULE / "SOURCE.json").read_text())
    cli_sha = next(
        item["sha256"]
        for item in source_inventory["files"]
        if item["path"] == "round03_cli.py"
    )
    cli = exact_module(
        MODULE / "online_v4/round03_cli.py", cli_sha, "e4_original_bootstrap"
    )
    cli.bootstrap(ROOT, MODULE)
    from cell_experiments import data
    from cell_experiments.online_v4.onpolicy_backend import ResearchBackend
    from cell_experiments.online_v4.round03_plan import (
        check_comparison,
        material_inputs,
    )

    context, manifests = material_inputs(ROOT)
    backend = ResearchBackend(context, ROOT)
    comparison = data._parse(COMPARISON.read_bytes())
    gate = data._parse((COMPARISON.parent / "ENGINEERING_GATE.json").read_bytes())
    if gate["status"] != "PASSED" or gate["source_inventory"] != backend.sources():
        raise ValueError("unchanged source numerical admission differs")
    entrypoint = {
        "round03_cli.py": cli_sha,
        "engineering_gate_digest": data.digest(gate),
    }
    check_comparison(comparison, context, manifests, backend, entrypoint)
    controls = exact_module(
        SOURCE / "circuit_controls_v4.py",
        protocol["source_sha256"]["circuit_controls_v4.py"],
        "cell_experiments.online_v4.circuit_controls_v4",
    )
    OUTPUT.mkdir(exist_ok=False)
    with (COMPARISON.parent / "WORKER.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        owner.write_new(
            OUTPUT / "WORKER_INTENT.json",
            {
                "protocol_sha256": expected,
                "pid": os.getpid(),
                "deadline_seconds": 7200,
                "comparison_digest": comparison["comparison_digest"],
                "automatic_retry": False,
                "started_at_ns": time.time_ns(),
                "source_inventory_sha256": sha(MODULE / "SOURCE.json"),
            },
        )

        def expired(signum, frame):
            raise cli.Deadline("own extended E4 worker elapsed deadline reached")

        previous = signal.signal(signal.SIGALRM, expired)
        signal.alarm(7200)
        started = time.monotonic()
        try:
            result = controls.run_extended_circuit(
                context, manifests, ROOT, comparison, OUTPUT / "circuit", expected
            )
            admission(expected, full=False)
            check_comparison(comparison, context, manifests, backend, entrypoint)
            owner.write_new(
                OUTPUT / "COMPLETE.json",
                {
                    "status": "COMPLETE",
                    "result_digest": data.digest(result),
                    "protocol_sha256": expected,
                    "worker_wall_seconds": time.monotonic() - started,
                    "full_system_cost_known": False,
                    "scientific_qualification": False,
                },
            )
        except BaseException as failure:
            owner.write_new(
                OUTPUT / "FAILED.json",
                {
                    "status": "FAILED_PRESERVED",
                    "error_type": type(failure).__name__,
                    "error": str(failure),
                    "worker_wall_seconds": time.monotonic() - started,
                    "call_totals_complete": False,
                    "automatic_retry": False,
                },
            )
            raise
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
            fcntl.flock(lock, fcntl.LOCK_UN)


def launch(expected):
    protocol, guard, owner, wrapper = admission(expected, full=False)
    OWNED.mkdir(exist_ok=False)
    ARCHIVE.mkdir(exist_ok=False)
    environment = dict(os.environ)
    for key, name in (
        ("TMPDIR", "tmp"),
        ("XDG_CACHE_HOME", "cache"),
        ("CUDA_CACHE_PATH", "cuda-cache"),
        ("TRITON_CACHE_DIR", "triton-cache"),
        ("TORCH_HOME", "torch-cache"),
        ("HF_HOME", "hf-cache"),
    ):
        environment[key] = str(ROOT / name)
    environment.update(
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1",
        TOKENIZERS_PARALLELISM="false",
        PYTHONDONTWRITEBYTECODE="1",
        OMP_NUM_THREADS="2",
        OPENBLAS_NUM_THREADS="2",
    )
    argv = [
        str(RUNTIME / "venv/bin/python"),
        "-I",
        "-B",
        str(Path(__file__)),
        "worker",
        expected,
    ]
    owner.write_new(
        OWNED / "INTENT.json",
        {
            "protocol_sha256": expected,
            "argv": argv,
            "automatic_retry": False,
            "original_sequence_sha256": sha(PREVIOUS / "SEQUENCE.json"),
            "original_release_sha256": sha(PREVIOUS / "SEQUENCE_COMPLETE.json"),
            "owned_wrapper_sha256": sha(wrapper),
            "independent_sample_increment": 0,
        },
    )
    code, error, started = None, None, time.monotonic()
    try:
        code = owner.run_owned(
            OWNED / "worker",
            argv,
            ROOT,
            environment,
            {
                "role": "extended-e4",
                "operation_key": "e4-controls-20261118-392934",
                "protocol_sha256": expected,
                "automatic_retry": False,
            },
        )
    except BaseException as failure:
        error = {"type": type(failure).__name__, "message": str(failure)}
        owner.write_new(OWNED / "LAUNCH_FAILED.json", error)
    finally:
        worker_seconds = time.monotonic() - started
        archive = ARCHIVE / "e4-originals.tar.gz"
        with tarfile.open(archive, "x:gz") as stream:
            for path in (
                SOURCE,
                OUTPUT,
                OWNED,
                MODULE,
                guard.CLOSURE,
                guard.RESTORATION,
                ROOT / "operations/launch_round03_392934_b.py",
                wrapper,
            ):
                if path.exists():
                    stream.add(path, arcname=path.name)
            stream.add(COMPARISON, arcname="B_COMPARISON.json")
            stream.add(
                COMPARISON.parent / "ENGINEERING_GATE.json",
                arcname="B_ENGINEERING_GATE.json",
            )
            stream.add(
                ROOT / "research-sft-02/INPUTS.json",
                arcname="research-sft-02/INPUTS.json",
            )
            for dirname in json.loads(guard.CLOSURE.read_text())[
                "complete_directory_file_hashes"
            ]:
                stream.add(ROOT / dirname, arcname=dirname)
            for mode in ("final_answer", "trajectory", "controlled_correction"):
                manifest_path = (
                    ROOT
                    / "research-sft-02/workers"
                    / (mode + "-primary/research-model/manifest.json")
                )
                stream.add(
                    manifest_path, arcname=manifest_path.relative_to(ROOT).as_posix()
                )
                adapter = (
                    ROOT / json.loads(manifest_path.read_text())["adapter_directory"]
                )
                training = adapter.parent / "TRAINING.json"
                stream.add(training, arcname=training.relative_to(ROOT).as_posix())
            for name in ("SEQUENCE.json", "SEQUENCE_COMPLETE.json"):
                stream.add(PREVIOUS / name, arcname="previous-owner/" + name)
        owner.write_new(
            ARCHIVE / "RESULT.json",
            {
                "wait_returncode": code,
                "launch_error": error,
                "worker_wall_seconds": worker_seconds,
                "archive_bytes": archive.stat().st_size,
                "archive_sha256": sha(archive),
                "full_system_cost_known": False,
                "business_result": "inspect fresh repository verifiers",
            },
        )
    print((ARCHIVE / "RESULT.json").read_text(), flush=True)
    return 1 if code is None else code if code >= 0 else 128 - code


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("launch", "worker"):
        raise ValueError("explicit launch or worker plus frozen protocol SHA required")
    if sys.argv[1] == "worker":
        worker(sys.argv[2])
    else:
        raise SystemExit(launch(sys.argv[2]))
