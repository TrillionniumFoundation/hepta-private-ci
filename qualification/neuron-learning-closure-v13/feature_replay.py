"""POSIX qualification: bounded real MiniLM replay or explicit HOLD/REJECTED.

Only the fixed V13 CPU profile is executable. Readback requires the caller's
retained receipt digest and never imports the encoder, adapter or executor.
"""

import argparse
from dataclasses import asdict, dataclass, fields
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback

from closure_common import canonical, digest_text, sha, strict_json
from closure_io import ClosureError, open_regular, read_capped


SCHEMA = "hepta.v13.feature-and-reference-replay.v1"


@dataclass(frozen=True)
class ReplayLimits:
    cpu_seconds: int = 60
    wall_seconds: int = 120
    address_space_bytes: int = 4 * 1024**3
    input_bytes: int = 512 * 1024**2
    output_bytes: int = 2 * 1024**2
    max_datasets: int = 8
    max_dataset_rows: int = 512

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is not int or not 1 <= value <= field.default:
                raise ClosureError(f"Invalid or enlarged replay limit: {field.name}")


def _unavailable(error):
    while error is not None:
        if isinstance(error, (FileNotFoundError, ModuleNotFoundError, ImportError)):
            return True
        error = error.__cause__
    return False


def _worker_main(config_path):
    result = {"schema": SCHEMA, "authority": "DENY_ALL", "status": "HOLD"}
    progress = {
        name: 0
        for name in (
            "admitted_source_copy_bytes",
            "staging_copy_bytes",
            "encoder_loads_attempted",
            "encoder_calls_attempted",
            "encoder_batches_attempted",
            "encoder_batches_completed",
            "adapter_calls_attempted",
            "executor_calls_attempted",
        )
    }
    result["progress"] = progress
    try:
        import resource

        config = strict_json(read_capped(config_path, 16_384))
        limits = ReplayLimits(**config.pop("limits"))
        for kind, maximum in (
            (resource.RLIMIT_AS, limits.address_space_bytes),
            (resource.RLIMIT_CPU, limits.cpu_seconds),
            (resource.RLIMIT_FSIZE, 128 * 1024**2),
            (resource.RLIMIT_CORE, 0),
        ):
            _, inherited = resource.getrlimit(kind)
            bound = (
                maximum
                if inherited == resource.RLIM_INFINITY
                else min(maximum, inherited)
            )
            resource.setrlimit(kind, (bound, bound))
        result["enforced_resources"] = {
            "address_space_bytes": resource.getrlimit(resource.RLIMIT_AS)[0],
            "cpu_seconds": resource.getrlimit(resource.RLIMIT_CPU)[0],
            "single_file_bytes": resource.getrlimit(resource.RLIMIT_FSIZE)[0],
        }
        from feature_worker import execute_reference

        result.update(execute_reference(config, limits, progress))
    except Exception as error:
        result.update(
            status="HOLD" if _unavailable(error) else "REJECTED",
            reason=f"{type(error).__name__}: {error}"[:2048],
        )
        traceback.print_exc()
    print(canonical(result).decode())


def _capture(path, maximum):
    size = path.stat().st_size
    with open_regular(path, 128 * 1024**2) as stream:
        raw = stream.read(maximum)
    complete = size <= maximum
    return raw, {
        "bytes": size,
        "captured_bytes": len(raw),
        "complete": complete,
        "sha256": sha(raw) if complete else None,
    }


def verify_feature_origin(
    checkpoint_path,
    *,
    source_snapshot,
    encoder_manifest_path,
    encoder_root,
    dataset_npz_path,
    expected_data_id,
    inputs_root,
    release_manifest_path=None,
    limits=None,
):
    """Run the fixed reference; returned failures retain observed costs.

    Catchable parent interruption kills and reaps the owned child, then
    propagates the original interruption. It never becomes a successful replay.
    """
    started, cpu = time.monotonic(), time.process_time()
    limits = limits or ReplayLimits()
    base = {
        "schema": SCHEMA,
        "authority": "DENY_ALL",
        "attempts": 1,
        "limits": asdict(limits),
    }
    usage, process, termination = None, None, None
    result = {"status": "HOLD"}
    try:
        if sys.platform not in ("linux", "darwin") or not hasattr(os, "wait4"):
            raise ImportError("This profile requires POSIX wait4 and resource limits")
        config = {
            name: str(Path(value).absolute())
            for name, value in {
                "checkpoint_path": checkpoint_path,
                "source_snapshot": source_snapshot,
                "encoder_manifest_path": encoder_manifest_path,
                "encoder_root": encoder_root,
                "dataset_npz_path": dataset_npz_path,
                "inputs_root": inputs_root,
            }.items()
        }
        config.update(expected_data_id=expected_data_id, limits=asdict(limits))
        config["release_manifest_path"] = (
            None
            if release_manifest_path is None
            else str(Path(release_manifest_path).absolute())
        )
        with tempfile.TemporaryDirectory(prefix="hepta-v13-replay-") as temporary:
            directory = Path(temporary)
            request = directory / "request.json"
            raw = canonical(config)
            if len(raw) > 16_384:
                raise ClosureError("Replay request exceeds its byte bound")
            request.write_bytes(raw)
            command = [
                sys.executable,
                "-I",
                "-B",
                "-c",
                "import sys; sys.path.insert(0, sys.argv[1]); from feature_replay import _worker_main; _worker_main(sys.argv[2])",
                str(Path(__file__).resolve().parent),
                str(request),
            ]
            environment = {
                **os.environ,
                "OPENBLAS_NUM_THREADS": "1",
                "OMP_NUM_THREADS": "1",
            }
            deadline = time.monotonic() + limits.wall_seconds
            with (
                (directory / "stdout").open("wb") as stdout,
                (directory / "stderr").open("wb") as stderr,
            ):
                process = subprocess.Popen(
                    command, stdout=stdout, stderr=stderr, env=environment
                )
                reaped = False
                try:
                    while True:
                        waited, status, usage = os.wait4(process.pid, os.WNOHANG)
                        if waited:
                            reaped, termination = True, "completed"
                            break
                        if time.monotonic() >= deadline:
                            termination = "wall_limit"
                            break
                        if (
                            max(
                                os.fstat(stdout.fileno()).st_size,
                                os.fstat(stderr.fileno()).st_size,
                            )
                            > limits.output_bytes
                        ):
                            termination = "output_limit"
                            break
                        time.sleep(0.01)
                finally:
                    if not reaped:
                        # Only this Popen child is touched. Its hard CPU bound
                        # remains independent of this catchable-parent cleanup.
                        try:
                            process.kill()
                        except ProcessLookupError:
                            pass
                        while True:
                            try:
                                _, status, usage = os.wait4(process.pid, 0)
                                break
                            except InterruptedError:
                                continue
                    process.returncode = os.waitstatus_to_exitcode(status)
            stdout_raw, stdout_record = _capture(
                directory / "stdout", limits.output_bytes
            )
            stderr_raw, stderr_record = _capture(
                directory / "stderr", limits.output_bytes
            )
            if termination != "completed" or process.returncode != 0:
                result = {"status": "HOLD", "reason": "Bounded worker did not complete"}
            elif not stdout_record["complete"] or not stderr_record["complete"]:
                result = {
                    "status": "REJECTED",
                    "reason": "Worker output exceeds the accepted receipt bound",
                }
            else:
                try:
                    result = strict_json(stdout_raw)
                    if (
                        not isinstance(result, dict)
                        or result.get("schema") != SCHEMA
                        or result.get("status") not in ("VERIFIED", "HOLD", "REJECTED")
                    ):
                        raise ClosureError(
                            "Worker did not return a complete replay result"
                        )
                except ClosureError as error:
                    result = {"status": "REJECTED", "reason": str(error)}
            result["worker_output"] = {"stdout": stdout_record, "stderr": stderr_record}
            result["worker_stderr"] = stderr_raw.decode(
                "utf-8", errors="backslashreplace"
            )
            if result["status"] != "VERIFIED":
                result["worker_stdout"] = stdout_raw.decode(
                    "utf-8", errors="backslashreplace"
                )
    except Exception as error:
        result = {
            "status": "HOLD"
            if _unavailable(error) or isinstance(error, OSError)
            else "REJECTED",
            "reason": f"{type(error).__name__}: {error}"[:2048],
        }
    parent_cpu = time.process_time() - cpu
    result.update(base)
    result["worker_exit"] = None if process is None else process.returncode
    result["worker_termination"] = termination
    result["cost"] = {
        "wall_seconds": time.monotonic() - started,
        "parent_cpu_seconds": parent_cpu,
        "child_user_seconds": None if usage is None else usage.ru_utime,
        "child_system_seconds": None if usage is None else usage.ru_stime,
        "total_cpu_seconds": None
        if usage is None
        else parent_cpu + usage.ru_utime + usage.ru_stime,
        "child_peak_rss_bytes": None
        if usage is None
        else usage.ru_maxrss * (1024 if sys.platform == "linux" else 1),
        "child_block_inputs": None if usage is None else usage.ru_inblock,
        "child_block_outputs": None if usage is None else usage.ru_oublock,
        "child_voluntary_context_switches": None if usage is None else usage.ru_nvcsw,
        "child_involuntary_context_switches": None
        if usage is None
        else usage.ru_nivcsw,
        "energy_joules": None,
        "scope": "Parent invocation and this exact child via wait4; model acquisition and caller receipt persistence are separate. Admitted-source-copy counters exclude subsequent staged/NPZ/ONNX reads.",
    }
    return result


def readback_receipt(path, expected_sha256, maximum=2 * 1024**2):
    started, cpu = time.monotonic(), time.process_time()
    if type(maximum) is not int or not 1 <= maximum <= 2 * 1024**2:
        raise ClosureError("Invalid or enlarged retained receipt bound")
    digest_text(expected_sha256, "retained replay receipt")
    raw = read_capped(path, maximum)
    if sha(raw) != expected_sha256:
        raise ClosureError("Retained receipt does not match the caller's exact digest")
    receipt = strict_json(raw)
    if not isinstance(receipt, dict) or receipt.get("schema") != SCHEMA:
        raise ClosureError("Not a retained V13 replay receipt")
    return {
        "schema": "hepta.v13.replay-readback.v1",
        "status": "READBACK",
        "authority": "DENY_ALL",
        "retained_receipt_sha256": expected_sha256,
        "retained_receipt": receipt,
        "fresh_execution": {
            "encoder_calls": 0,
            "adapter_calls": 0,
            "executor_calls": 0,
            "external_operations": 0,
        },
        "readback_cost": {
            "wall_seconds": time.monotonic() - started,
            "cpu_seconds": time.process_time() - cpu,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", nargs="?")
    for name in (
        "source-snapshot",
        "encoder-manifest",
        "encoder-root",
        "dataset",
        "data-id",
        "inputs-root",
        "release-manifest",
        "readback",
        "expected-sha256",
    ):
        parser.add_argument("--" + name)
    args = parser.parse_args()
    try:
        if args.readback:
            if args.checkpoint or not args.expected_sha256:
                parser.error(
                    "readback needs an expected digest and no execution request"
                )
            result = readback_receipt(args.readback, args.expected_sha256)
        else:
            if not all(
                (
                    args.checkpoint,
                    args.source_snapshot,
                    args.encoder_manifest,
                    args.encoder_root,
                    args.dataset,
                    args.data_id,
                    args.inputs_root,
                )
            ):
                parser.error(
                    "execution needs checkpoint, source, encoder, data and original input material"
                )
            result = verify_feature_origin(
                args.checkpoint,
                source_snapshot=args.source_snapshot,
                encoder_manifest_path=args.encoder_manifest,
                encoder_root=args.encoder_root,
                dataset_npz_path=args.dataset,
                expected_data_id=args.data_id,
                inputs_root=args.inputs_root,
                release_manifest_path=args.release_manifest,
            )
        print(
            json.dumps(
                result, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False
            )
        )
        return {"VERIFIED": 0, "READBACK": 0, "HOLD": 3, "REJECTED": 2}[
            result["status"]
        ]
    except (ClosureError, OSError) as error:
        print(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "authority": "DENY_ALL",
                    "status": "REJECTED",
                    "reason": str(error),
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
