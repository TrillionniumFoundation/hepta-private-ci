"""Linux research receipt for a distinct new crossed train/dev execution.

Publication identities are caller declarations, not remote authentication.
This never recovers the missing original, parses fit outcomes, reads old
confirmation material or grants promotion. File fsync does not establish
atomic publication or directory durability across power failure.
"""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
from time import perf_counter, process_time

from .crossed_design import validate_config
from .crossed_training import _source

THREADS = (
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _read(path):
    with Path(path).open("rb") as stream:
        encoded = stream.read(524_289)
    _require(len(encoded) <= 524_288, "registration/config byte limit exceeded")

    def pairs(items):
        value = {}
        for key, item in items:
            _require(key not in value, "duplicate JSON key")
            value[key] = item
        return value

    return encoded, json.loads(
        encoded,
        object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")),
    )


def _sha(path):
    digest = sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write(path, value):
    encoded = (
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()
    with Path(path).open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


def _process_identity(pid):
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        ticks = int(stat.rsplit(")", 1)[1].split()[19])
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except (OSError, ValueError, IndexError):
        ticks, boot = None, None
    return {"pid": pid, "linux_start_ticks": ticks, "boot_id": boot}


def run(registration, registration_commit, output):
    """Validate and freeze bytes before launch; retain terminal failures."""
    _require(sys.platform.startswith("linux"), "this research wrapper requires Linux")
    import resource

    wall, cpu = perf_counter(), process_time()
    _require(
        type(registration_commit) is str
        and re.fullmatch(r"[0-9a-f]{40}", registration_commit),
        "execution registration commit must be a full Git SHA",
    )
    registration = Path(registration).resolve(strict=True)
    registered_bytes, plan = _read(registration)
    fields = {
        "schema",
        "execution_id",
        "new_execution_only",
        "original_artifacts_status",
        "config_file",
        "config_sha256",
        "source_sha256",
        "timeout_seconds",
        "design_registration_commit",
        "execution_source_commit",
        "runner_sha256",
    }
    _require(type(plan) is dict and set(plan) == fields, "registration fields differ")
    _require(
        plan["schema"] == "pred1-crossed-reexecution-registration-v1"
        and plan["new_execution_only"] is True
        and plan["original_artifacts_status"] == "ORIGINAL_ARTIFACTS_NOT_LOCATED",
        "a distinct new execution must be registered",
    )
    for key in ("design_registration_commit", "execution_source_commit"):
        _require(
            type(plan[key]) is str and re.fullmatch(r"[0-9a-f]{40}", plan[key]),
            "design/source commit must be full Git SHA",
        )
    _require(
        type(plan["execution_id"]) is str
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", plan["execution_id"]),
        "invalid execution identity",
    )
    name = plan["config_file"]
    _require(
        type(name) is str
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name)
        and name not in (".", ".."),
        "config_file must be an adjacent basename",
    )
    timeout = plan["timeout_seconds"]
    _require(type(timeout) is int and 1 <= timeout <= 7200, "invalid child timeout")
    config_bytes, config = _read(registration.parent / name)
    validate_config(config)
    config_hash = sha256(config_bytes).hexdigest()
    source = _source()
    hashes = {name: sha256(value).hexdigest() for name, value in source.items()}
    _require(plan["config_sha256"] == config_hash, "registered config SHA256 differs")
    _require(plan["source_sha256"] == hashes, "registered nine-file source differs")
    _require(
        plan["runner_sha256"] == _sha(__file__), "registered runner SHA256 differs"
    )
    out = Path(output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    # Child imports copied bytes, unaffected by later source-path replacement.
    package = out / "scripts" / "hepta_pred1"
    package.mkdir(parents=True)
    for filename, encoded in source.items():
        (package / filename).write_bytes(encoded)
    config_path = out / "registered_config.json"
    config_path.write_bytes(config_bytes)
    (out / "registration.json").write_bytes(registered_bytes)
    argv = [
        sys.executable,
        "-B",
        "-m",
        "hepta_pred1.crossed_training",
        "--config",
        str(config_path),
        "--output",
        str(out / "campaign"),
    ]
    child_env = {
        **os.environ,
        **dict.fromkeys(THREADS, "1"),
        "PYTHONPATH": str(out / "scripts"),
    }
    started = {
        "schema": "pred1-crossed-new-execution-start-v1",
        "execution_id": plan["execution_id"],
        "new_execution_only": True,
        "original_execution_recovered": False,
        "registration_commit": plan["design_registration_commit"],
        "execution_source_commit": plan["execution_source_commit"],
        "execution_registration_commit": registration_commit,
        "registration_sha256": sha256(registered_bytes).hexdigest(),
        "runner_sha256": plan["runner_sha256"],
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "argv": argv,
        "config_sha256": config_hash,
        "source_sha256": hashes,
        "host": socket.gethostname(),
        "wrapper_process": _process_identity(os.getpid()),
        "environment": {k: child_env[k] for k in (*THREADS, "PYTHONPATH")},
    }
    _write(out / "EXECUTION_STARTED.json", started)
    usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    child, child_identity, error, code, status = None, None, None, None, "LAUNCH_FAILED"
    with (
        (out / "stdout.log").open("xb") as stdout,
        (out / "stderr.log").open("xb") as stderr,
    ):
        try:
            child = subprocess.Popen(
                argv,
                cwd=out,
                env=child_env,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            child_identity = _process_identity(child.pid)
            code = child.wait(timeout=timeout)
            status = "EXITED"
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as failure:
            status = (
                "TIMED_OUT"
                if isinstance(failure, subprocess.TimeoutExpired)
                else "INTERRUPTED"
            )
            if child is not None:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    code = child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    code = child.wait()
            error = type(failure).__name__
        except OSError as failure:
            error = {"type": type(failure).__name__, "message": str(failure)}
    usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    source_after, copied_after, source_errors = None, None, []
    try:
        source_after = {
            name: sha256(value).hexdigest() for name, value in _source().items()
        }
    except OSError as failure:
        source_errors.append(
            {
                "location": "repository_source",
                "type": type(failure).__name__,
                "message": str(failure),
            }
        )
    try:
        copied_after = {name: _sha(package / name) for name in source}
    except OSError as failure:
        source_errors.append(
            {
                "location": "executed_source",
                "type": type(failure).__name__,
                "message": str(failure),
            }
        )
    source_unchanged = not source_errors and hashes == source_after == copied_after
    if not source_unchanged and status == "EXITED":
        status = "SOURCE_CHANGED"
        error = {"type": "SourceClosureChanged", "read_errors": source_errors}
    wrapper_code = (
        code
        if status == "EXITED" and source_unchanged and code is not None and code >= 0
        else 1
    )
    result = out / "campaign" / "RESULT.json"
    inventory = []
    for path in sorted((out / "campaign" / "fits").glob("*.npz")):
        _require(
            path.is_file() and not path.is_symlink(),
            "checkpoint must be an ordinary file",
        )
        inventory.append(
            {"filename": path.name, "bytes": path.stat().st_size, "sha256": _sha(path)}
        )
    logs = {
        n: {"bytes": (out / n).stat().st_size, "sha256": _sha(out / n)}
        for n in ("stdout.log", "stderr.log")
    }
    result_present = result.is_file() and not result.is_symlink()
    result_hash = _sha(result) if result_present else None
    receipt = {
        **started,
        "schema": "pred1-crossed-new-execution-receipt-v1",
        "status": status,
        "exit_code": wrapper_code,
        "child_exit_code": code,
        "error": error,
        "child_process": child_identity,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "outer_wall_seconds": perf_counter() - wall,
        "wrapper_process_cpu_seconds": process_time() - cpu,
        "child_user_cpu_seconds": usage_after.ru_utime - usage_before.ru_utime,
        "child_system_cpu_seconds": usage_after.ru_stime - usage_before.ru_stime,
        "children_peak_rss_kib_highwater": usage_after.ru_maxrss,
        "resource_scope": "RUSAGE_CHILDREN CPU deltas; RSS is cumulative high-water, not an additive cost",
        "logs": logs,
        "source_sha256_after": source_after,
        "executed_source_sha256_after": copied_after,
        "source_read_errors": source_errors,
        "source_closure_unchanged": source_unchanged,
        "result_present": result_present,
        "result_sha256": result_hash,
        "checkpoint_inventory": inventory,
        "checkpoint_count": len(inventory),
        "fit_outcomes_parsed": False,
        "confirmation_data_read": False,
        "qualification": "HOLD_UNCHANGED",
        "physical_cost_complete": False,
        "timing_scope": "through child termination and artifact hashing; excludes final receipt serialization/fsync",
    }
    _write(out / "EXECUTION_RECEIPT.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registration", type=Path, required=True)
    parser.add_argument("--registration-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = run(args.registration, args.registration_commit, args.output)
    print(
        json.dumps({k: receipt[k] for k in ("status", "exit_code", "checkpoint_count")})
    )
    return receipt["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
