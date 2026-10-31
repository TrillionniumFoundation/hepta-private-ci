"""Audit real broker artifacts through the reused historical native adapter.

This does not compile or deploy Round7 dynamics in Rust. The historical build
receipt remains unchanged; this run produces a separate execution receipt.
"""

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import signal
import stat
import time

from ..native_adapter import Native


Q24 = 1 << 24
BINARY_SHA256 = "b519cae26325f818d9596aab34504490a0b5355b9eb633369878e6f07a50e179"
BUILD_RECEIPT_SHA256 = "3d791e7d7245904a31a9d71301075ac562772130dd6d9628a8369e7ae701ba3d"


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _write(path, record):
    path.write_text(json.dumps(record, sort_keys=True, indent=2, allow_nan=False) + "\n")


@contextmanager
def _deadline(seconds):
    """Bound the legacy adapter's blocking readline in this Linux CLI."""
    def expired(signum, frame):
        raise TimeoutError(f"native request exceeded {seconds} seconds")

    old_handler = signal.getsignal(signal.SIGALRM)
    old_timer = signal.setitimer(signal.ITIMER_REAL, 0)
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        if old_timer[0]:
            signal.setitimer(signal.ITIMER_REAL, *old_timer)


def _read_artifact(path, allowed_root):
    original = Path(path)
    if original.is_symlink():
        raise ValueError("terminal artifact must be a regular file, not a symlink")
    resolved = original.resolve(strict=True)
    if not resolved.is_relative_to(allowed_root):
        raise ValueError("artifact is outside the declared artifact root")
    fd = os.open(resolved, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 8 * 1024 * 1024:
            raise ValueError("artifact must be a regular file of at most 8 MiB")
        content = stream.read()
    return {"path": str(resolved), "bytes": len(content), "sha256": _sha(content)}


def _validate_typed(result):
    for key in ("typed_model_port", "original_neuron_runtime", "original_sparse_journal",
                "independent_anchor_witness", "abstain"):
        if result.get(key) is not True:
            raise AssertionError(f"native typed output did not retain {key}")
    if result.get("authority") != "DENY_ALL" or result.get("native_owner_integration"):
        raise AssertionError("research native owner unexpectedly acquired authority")
    if result.get("calibrated_success_probability") is not False:
        raise AssertionError("unqualified native output claimed calibration")
    q = result["head"]["probabilities_q24"]
    if len(q) != 3 or any(not isinstance(x, int) or x < 0 for x in q) or sum(q) != Q24:
        raise AssertionError("native probability vector is not a Q24 simplex")


def _validate_pair(result, reset):
    if result.get("authority") != "DENY_ALL" or result.get("native_owner_integration"):
        raise AssertionError("sparse bridge unexpectedly acquired authority")
    if result.get("original_sparse_tick_calls") != 2 or len(result.get("ticks", [])) != 2:
        raise AssertionError("pair did not execute exactly two original sparse ticks")
    if result.get("checkpoint_reset_intervention") is not reset:
        raise AssertionError("pair reset intervention does not match request")
    for tick in result["ticks"]:
        if tick.get("authority") != "DENY_ALL" or tick.get("requires_calibration") is not True:
            raise AssertionError("unqualified sparse tick lost its authority/calibration boundary")


def run(manifest_path, artifact_root, output, binary, build_receipt, timeout=10.0):
    started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
    children_started = resource.getrusage(resource.RUSAGE_CHILDREN)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("native request timeout must be finite and positive")
    artifact_root = Path(artifact_root).resolve(strict=True)
    binary, build_receipt = Path(binary).resolve(strict=True), Path(build_receipt).resolve(strict=True)
    if _sha(binary.read_bytes()) != BINARY_SHA256:
        raise ValueError("native executable differs from the pinned restored binary")
    build_bytes = build_receipt.read_bytes()
    if _sha(build_bytes) != BUILD_RECEIPT_SHA256:
        raise ValueError("original native build receipt changed")
    historical_receipt = json.loads(build_bytes)
    manifest_bytes = Path(manifest_path).read_bytes()
    manifest = json.loads(manifest_bytes)
    records = manifest["records"] if isinstance(manifest, dict) else manifest
    if not isinstance(records, list) or len(records) != 16:
        raise ValueError("bridge audit requires exactly 16 predeclared broker terminal artifacts")
    cases = [record["case"] for record in records]
    if len(set(cases)) != 16 or any(not isinstance(case, str) or not case for case in cases):
        raise ValueError("case identifiers must be nonempty and distinct")
    for record in records:
        params = record["native_parameters"]
        if set(params) != {"mean", "variance", "lower", "upper"}:
            raise ValueError("native_parameters must declare mean, variance, lower, upper")
        if any(not math.isfinite(float(v)) for v in params.values()):
            raise ValueError("native input must be finite")
        if not record.get("parameter_mapping"):
            raise ValueError("declare where each native Gaussian input came from")
        digest = record["expected_sha256"]
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError("expected artifact SHA256 must be a 64-character hexadecimal string")
        if len(bytes.fromhex(digest)) != 32:
            raise ValueError("artifact SHA256 must encode 32 bytes")
    if len({str(Path(r["artifact_path"]).resolve()) for r in records}) != 16:
        raise ValueError("the sixteen cases must refer to sixteen distinct broker artifacts")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    outcomes = []
    totals = {"native_calls": 0, "original_sparse_ticks": 0, "native_subprocess_roundtrip_ns": 0}
    for index, record in enumerate(records):
        case_started = time.perf_counter_ns()
        case_path = output / f"case_{index:02d}"
        case_path.mkdir()
        result = {"index": index, "case": record["case"], "request_record": record,
                  "status": "started", "phases": []}
        native = None
        try:
            native = Native(binary, historical_receipt)
            parameters = record["native_parameters"]
            directory = case_path / "typed_journal"
            with _deadline(timeout):
                typed = native.typed(record["case"], directory, **parameters)
            result["typed"] = typed
            result["phases"].append("native_typed")
            _validate_typed(typed)
            readback = _read_artifact(record["artifact_path"], artifact_root)
            readback["expected_sha256"] = record["expected_sha256"]
            readback["matches_writer_receipt"] = readback["sha256"] == record["expected_sha256"]
            result["readback"] = readback
            result["phases"].append("terminal_artifact_readback")
            feedback = Q24 if readback["matches_writer_receipt"] else -Q24
            result["feedback_rule"] = "writer-receipt SHA256 match: +2^24; mismatch: -2^24; never hidden task truth"
            result["feedback_q24"] = feedback
            with _deadline(timeout):
                pair = native.tick_pair(record["case"], readback["sha256"], feedback, False)
            result["pair"] = pair
            result["phases"].append("native_feedback_pair")
            _validate_pair(pair, False)
            with _deadline(timeout):
                reset_pair = native.tick_pair(record["case"], readback["sha256"], feedback, True)
            result["reset_pair"] = reset_pair
            result["phases"].append("native_feedback_reset_control")
            _validate_pair(reset_pair, True)
            result["readout_activation_changed_by_reset"] = (
                pair["ticks"][1]["activation_q24"] != reset_pair["ticks"][1]["activation_q24"])
            result["status"] = "passed" if readback["matches_writer_receipt"] else "readback_mismatch"
        except Exception as error:
            result["status"] = "failed"
            result["error"] = {"type": type(error).__name__, "message": str(error)}
        finally:
            if native is not None:
                totals["native_calls"] += native.calls
                totals["original_sparse_ticks"] += native.original_sparse_ticks
                totals["native_subprocess_roundtrip_ns"] += native.wall_ns
                try:
                    native.close()
                except Exception as error:
                    result["close_error"] = {"type": type(error).__name__, "message": str(error)}
                    result["status"] = "failed"
            result["case_wall_ns"] = time.perf_counter_ns() - case_started
            _write(case_path / "EXECUTION.json", result)
            outcomes.append({"case": record["case"], "status": result["status"],
                             "receipt": str((case_path / "EXECUTION.json").relative_to(output))})
    children_finished = resource.getrusage(resource.RUSAGE_CHILDREN)
    child_cpu_seconds = ((children_finished.ru_utime + children_finished.ru_stime)
                         - (children_started.ru_utime + children_started.ru_stime))
    summary = {
        "schema": "hepta.analytic-event.round7.native-bridge.v1",
        "manifest_sha256": _sha(manifest_bytes), "binary_sha256": BINARY_SHA256,
        "historical_build_receipt_sha256": BUILD_RECEIPT_SHA256,
        "historical_source_commit": historical_receipt["source_commit"],
        "fresh_compile_this_run": False,
        "scope": "Executed historical typed NeuronRuntime and sparse-tick I/O bridge over actual broker readbacks; Round7 dynamics and learned weights are not installed in Rust.",
        "state_scope": "The typed request writes its own persistent journal. Each pair request starts a separate fresh sparse state and does not restore or mutate that typed journal. The reset control is internal to its two-tick pair.",
        "authority": "DENY_ALL", "production_activation": False,
        "feedback_scope": "Artifact integrity only; no task-answer or calibrated-success-probability feedback claim.",
        "outcomes": outcomes, "all_passed": all(r["status"] == "passed" for r in outcomes),
        "totals": totals,
        "wall_ns": time.perf_counter_ns() - started,
        "controller_cpu_ns_excluding_child_processes": time.process_time_ns() - cpu_started,
        "native_child_cpu_ns": round(child_cpu_seconds * 1e9),
    }
    _write(output / "SUMMARY.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--output", required=True)
    here = Path(__file__).resolve().parent
    parser.add_argument("--binary", default=str(here / "evidence/native_reuse/analytic_event"))
    parser.add_argument("--build-receipt", default=str(here / "evidence/native_reuse/BUILD_RECEIPT.json"))
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    summary = run(args.manifest, args.artifact_root, args.output, args.binary,
                  args.build_receipt, args.timeout)
    print(json.dumps({"all_passed": summary["all_passed"], "totals": summary["totals"],
                      "wall_ns": summary["wall_ns"]}, sort_keys=True))
    raise SystemExit(0 if summary["all_passed"] else 1)


if __name__ == "__main__":
    main()
