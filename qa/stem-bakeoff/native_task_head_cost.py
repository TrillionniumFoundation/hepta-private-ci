"""Linux research-only cost measurement of one persistent native task Head.

Request bytes are retained JSONL, not regenerated features. Timings include the
pipe round trip, native JSON parsing/inference/serialization and Python response
JSON parsing. Encoder, request construction, validation and startup are excluded
from steady-state latency. Source metadata is not compiler attestation.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import queue
import select
import stat
import subprocess
import sys
import threading
import time

MAX_LINE = 256 * 1024
MAX_INPUT = 256 * 1024 * 1024
MAX_ROWS = 8192
MAX_BINARY = 512 * 1024 * 1024
PREDICTION_KEYS = {"task_logits", "task_probabilities", "predicted_class",
                   "accepted", "gate", "mode", "authority"}


class NativeCostError(ValueError):
    pass


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _digest(value):
    return (type(value) is str and len(value) == 64
            and all(c in "0123456789abcdef" for c in value)
            and value != "0" * 64)


def _finite_scalar(value):
    """Reject out-of-range JSON integers without leaking OverflowError."""
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise NativeCostError("duplicate JSON key")
            result[key] = value
        return result

    def constant(_):
        raise NativeCostError("nonfinite JSON number")

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise NativeCostError("invalid bounded JSON") from error


def _file(path, limit, *, payload=False):
    path = Path(path).absolute()
    if path.is_symlink():
        raise NativeCostError("direct symlink input is not supported")
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
            raise NativeCostError("regular nonempty bounded file required")
        digest, pieces, count = hashlib.sha256(), [], 0
        while chunk := stream.read(min(1024 * 1024, limit + 1 - count)):
            count += len(chunk)
            if count > limit:
                raise NativeCostError("file exceeded its byte budget")
            digest.update(chunk)
            if payload:
                pieces.append(chunk)
        after = os.fstat(stream.fileno())
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or count != before.st_size:
        raise NativeCostError("input changed while hashing")
    return digest.hexdigest(), b"".join(pieces) if payload else None


def _inputs(raw, manifest):
    lines = raw.splitlines(keepends=True)
    if not 1 <= len(lines) <= MAX_ROWS:
        raise NativeCostError("request row budget")
    selected, rejected = [], 0
    for line in lines:
        if not line.endswith(b"\n") or len(line) > MAX_LINE:
            raise NativeCostError("bounded newline-terminated request required")
        item = _json(line)
        if (type(item) is not dict or set(item) != {
                "identity", "features", "present_mask", "source_record_digest"}
                or item["identity"] != manifest["feature_identity"]
                or not _digest(item["source_record_digest"])
                or type(item["present_mask"]) is not int or not 0 <= item["present_mask"] <= 31
                or type(item["features"]) is not list
                or len(item["features"]) != manifest["width"]
                or any(not _finite_scalar(x)
                       or abs(x) > 3.4028234663852886e38 for x in item["features"])):
            raise NativeCostError("request feature identity, shape or values differ")
        if item["present_mask"] & 3 == 3:
            selected.append((line, _sha(line), item["source_record_digest"]))
        else:
            rejected += 1
    if not selected:
        raise NativeCostError("no complete text+image rows for Head cost measurement")
    return selected, len(lines), rejected


def _response(result, index, request_sha, source, artifact_sha, manifest):
    if (type(result) is not dict or set(result) != {"row_index", "request_sha256",
            "source_record_digest", "artifact_sha256", "status", "prediction",
            "task_admission_allowed", "action_execution_allowed"}
            or type(result["row_index"]) is not int or result["row_index"] != index
            or result["request_sha256"] != request_sha
            or result["source_record_digest"] != source
            or result["artifact_sha256"] != artifact_sha
            or result["status"] != "SCORED_RESEARCH_ONLY"
            or result["task_admission_allowed"] is not False
            or result["action_execution_allowed"] is not False):
        raise NativeCostError("response correlation, scoring or authority differs")
    prediction = result["prediction"]
    if type(prediction) is not dict or set(prediction) != PREDICTION_KEYS:
        raise NativeCostError("complete task prediction required")
    logits, probs = prediction["task_logits"], prediction["task_probabilities"]
    if (any(type(v) is not list or len(v) != manifest["task_count"]
            or any(not _finite_scalar(x) for x in v)
            for v in (logits, probs))
            or any(not 0 <= p <= 1 for p in probs) or abs(sum(probs) - 1) > 1e-6
            or type(prediction["predicted_class"]) is not int
            or prediction["predicted_class"] != max(range(len(probs)), key=probs.__getitem__)
            or type(prediction["accepted"]) is not bool
            or prediction["accepted"] != (max(probs) >= manifest["confidence_threshold"])
            or not _finite_scalar(prediction["gate"]) or not 0 <= prediction["gate"] <= 1
            or prediction["authority"] != "DENY_ALL" or prediction["mode"] != "SHADOW_ONLY"):
        raise NativeCostError("task prediction values or research posture differ")
    return _sha(json.dumps(prediction, sort_keys=True, separators=(",", ":"),
                           allow_nan=False).encode())


def _reader(stream, messages):
    try:
        while True:
            line = stream.readline(MAX_LINE + 1)
            if not line:
                messages.put(None, timeout=1)
                return
            if len(line) > MAX_LINE or not line.endswith(b"\n"):
                messages.put(NativeCostError("oversized or partial response"), timeout=1)
                return
            messages.put(line, timeout=1)
    except queue.Full:
        return
    except Exception as error:
        try:
            messages.put(error, timeout=1)
        except queue.Full:
            return


def _stderr(stream, retained):
    while chunk := stream.read(4096):
        if len(retained) < MAX_LINE:
            retained.extend(chunk[:MAX_LINE - len(retained)])


def _next(messages, timeout):
    try:
        result = messages.get(timeout=timeout)
    except queue.Empty as error:
        raise NativeCostError("native response timeout") from error
    if isinstance(result, Exception):
        raise NativeCostError("invalid native output") from result
    return result


def _send(stream, line, deadline):
    view = memoryview(line)
    while view:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([], [stream], [], remaining)[1]:
            raise NativeCostError("native request write timeout")
        try:
            sent = os.write(stream.fileno(), view)
        except BlockingIOError:
            continue
        if sent <= 0:
            raise NativeCostError("native request write failed")
        view = view[sent:]


def _proc_status(path):
    with path.open("rb") as stream:
        raw = stream.read(32769)
    if len(raw) > 32768:
        raise NativeCostError("proc status byte budget")
    fields = {}
    for line in raw.decode("ascii").splitlines():
        key, _, value = line.partition(":")
        if key in {"Pid", "PPid", "NSpid", "VmRSS", "VmHWM"}:
            if key in fields:
                raise NativeCostError("repeated proc status field")
            fields[key] = value.split()
    return fields


def _proc_identity(directory, child_pid, parent_pid, binary):
    fields = _proc_status(directory / "status")
    if (fields.get("Pid") != [directory.name]
            or fields.get("PPid") != [str(parent_pid)]
            or not fields.get("NSpid") or fields["NSpid"][-1] != str(child_pid)
            or not (directory / "exe").samefile(binary)):
        raise NativeCostError("proc child ownership or executable differs")
    with (directory / "stat").open("rb") as stream:
        raw = stream.read(8193)
    fields_stat = raw[raw.rfind(b")") + 2:].split()
    if len(raw) > 8192 or len(fields_stat) <= 19 or not fields_stat[19].isdigit():
        raise NativeCostError("invalid proc process start time")
    return int(fields_stat[19]), fields


def _locate_child(process, binary):
    try:
        parent = int(_proc_status(Path("/proc/self/status"))["Pid"][0])
        candidates = []
        entries = list(Path("/proc").iterdir())
        if len(entries) > 65536:
            raise NativeCostError("proc entry budget")
        for directory in entries:
            if not directory.name.isdecimal():
                continue
            try:
                started, _ = _proc_identity(directory, process.pid, parent, binary)
                candidates.append((directory, process.pid, parent, binary, started))
            except (OSError, ValueError, UnicodeError):
                continue
        if len(candidates) != 1:
            raise NativeCostError("no unique child verified by PPid/NSpid/exe/starttime")
        return candidates[0], None
    except (OSError, ValueError, KeyError, IndexError, UnicodeError) as error:
        return None, str(error)


def _sample_rss(identity, unavailable_reason):
    if identity is None:
        return {"rss_bytes": None, "post_exec_peak_rss_bytes": None, "reason": unavailable_reason}
    try:
        directory, child, parent, binary, started = identity
        observed, fields = _proc_identity(directory, child, parent, binary)
        if observed != started:
            raise NativeCostError("proc child start time changed")
        result = {}
        for key, name in (("VmRSS", "rss_bytes"), ("VmHWM", "post_exec_peak_rss_bytes")):
            value = fields[key]
            if len(value) != 2 or value[1] != "kB" or not value[0].isdigit() or int(value[0]) <= 0:
                raise NativeCostError("invalid proc RSS units or value")
            result[name] = int(value[0]) * 1024
        return {**result, "reason": None}
    except (OSError, ValueError, KeyError, UnicodeError) as error:
        return {"rss_bytes": None, "post_exec_peak_rss_bytes": None, "reason": str(error)}


def run_cost(binary, manifest, weights, requests, expected_manifest_sha256,
             expected_requests_sha256, *, warmup=20, samples=1000,
             source_identity=None, timeout_seconds=30.0):
    """Measure complete retained rows in source order, cycling when necessary.

    Presence-only filtering is fixed before measurement; labels and predictions
    never select inputs. Verified proc identity supplies post-exec RSS. The
    separate wait4 lifetime peak may include inherited pre-exec parent memory.
    """
    if (sys.platform != "linux" or not hasattr(os, "wait4")
            or type(warmup) is not int or not 1 <= warmup <= 512
            or type(samples) is not int or not 1 <= samples <= 4096
            or warmup + samples > MAX_ROWS
            or type(timeout_seconds) not in (int, float)
            or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 60
            or not _digest(expected_manifest_sha256) or not _digest(expected_requests_sha256)):
        raise NativeCostError("Linux wait4, bounded counts, timeout and expected digests required")
    source_raw = json.dumps(source_identity, sort_keys=True, separators=(",", ":"),
                            allow_nan=False).encode()
    if len(source_raw) > 65536 or source_identity is not None and type(source_identity) is not dict:
        raise NativeCostError("bounded source metadata required")
    paths = [Path(value).absolute() for value in (binary, manifest, weights, requests)]
    limits = [MAX_BINARY, 65536, 1024 * 1024, MAX_INPUT]
    before = [_file(path, limit, payload=i in (1, 3))
              for i, (path, limit) in enumerate(zip(paths, limits, strict=True))]
    if before[1][0] != expected_manifest_sha256 or before[3][0] != expected_requests_sha256:
        raise NativeCostError("retained artifact or request file digest differs")
    spec = _json(before[1][1])
    if (type(spec) is not dict or spec.get("schema") != "hepta.native-task-head.v1"
            or spec.get("numeric_profile") != "f32-io-f64-accum-gelu-erf-v1"
            or spec.get("state_contract") != "zero_state_only"
            or spec.get("authority") != "DENY_ALL" or spec.get("mode") != "SHADOW_ONLY"
            or spec.get("required_present_mask") != 3
            or spec.get("feature_layout") != "concat-text-image-product-absolute-difference-cosine-v1"
            or type(spec.get("feature_identity")) is not dict or not spec["feature_identity"]
            or type(spec.get("width")) is not int or not 5 <= spec["width"] <= 4096
            or (spec["width"] - 1) % 4
            or type(spec.get("task_count")) is not int or not 2 <= spec["task_count"] <= 256
            or type(spec.get("confidence_threshold")) not in (float, int)
            or not 0.5 <= spec["confidence_threshold"] <= 1
            or spec.get("weights_sha256") != before[2][0]
            or spec.get("weights_bytes") != paths[2].stat().st_size):
        raise NativeCostError("native manifest or weights contract differs")
    selected, input_rows, missing_rows = _inputs(before[3][1], spec)
    before = [(digest, None) for digest, _ in before]
    cost_source_digest = _sha(Path(__file__).read_bytes())
    messages, stderr_bytes = queue.Queue(maxsize=4), bytearray()
    durations, prediction_hashes, request_order = [], {}, hashlib.sha256()
    started = time.perf_counter_ns()
    process = subprocess.Popen([str(paths[0]), str(paths[1]), str(paths[2]),
                                expected_manifest_sha256], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    os.set_blocking(process.stdin.fileno(), False)
    stdout_thread = threading.Thread(target=_reader, args=(process.stdout, messages), daemon=True)
    stderr_thread = threading.Thread(target=_stderr, args=(process.stderr, stderr_bytes), daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    reaped = False
    try:
        first_response_ms, measured_start, child_identity, rss_reason = None, None, None, None
        for index in range(warmup + samples):
            line, request_sha, source = selected[index % len(selected)]
            if index == warmup:
                child_identity, rss_reason = _locate_child(process, paths[0])
                warmup_rss = _sample_rss(child_identity, rss_reason)
                measured_start = time.perf_counter_ns()
            start = time.perf_counter_ns()
            deadline = time.monotonic() + timeout_seconds
            _send(process.stdin, line, deadline)
            raw = _next(messages, max(0, deadline - time.monotonic()))
            if raw is None:
                raise NativeCostError("native process ended before response")
            decoded = _json(raw)
            stop = time.perf_counter_ns()
            if first_response_ms is None:
                first_response_ms = (stop - started) / 1e6
            # Validation is deliberately outside the timed round trip.
            prediction_sha = _response(decoded, index, request_sha, source, expected_manifest_sha256, spec)
            if request_sha in prediction_hashes and prediction_hashes[request_sha] != prediction_sha:
                raise NativeCostError("identical request produced different task prediction")
            prediction_hashes[request_sha] = prediction_sha
            if index >= warmup:
                durations.append(stop - start)
                request_order.update(bytes.fromhex(request_sha))
        measured_wall_ms = (time.perf_counter_ns() - measured_start) / 1e6
        final_rss = _sample_rss(child_identity, rss_reason)
        process.stdin.close()
        if _next(messages, timeout_seconds) is not None:
            raise NativeCostError("unexpected extra native response")
        deadline = time.monotonic() + timeout_seconds
        while True:
            waited, status, usage = os.wait4(process.pid, os.WNOHANG)
            if waited == process.pid:
                process.returncode = os.waitstatus_to_exitcode(status)
                reaped = True
                break
            if time.monotonic() >= deadline:
                raise NativeCostError("native exit timeout")
            time.sleep(0.005)
        if process.returncode != 0:
            raise NativeCostError(f"native process failed with exit status {process.returncode}")
        stderr_thread.join(timeout=timeout_seconds)
        for (path, limit), (digest, _) in zip(zip(paths, limits, strict=True), before, strict=True):
            if _file(path, limit)[0] != digest:
                raise NativeCostError("native binary or input changed during measurement")
        if _sha(Path(__file__).read_bytes()) != cost_source_digest:
            raise NativeCostError("cost measurement source changed during execution")
    finally:
        if not reaped:
            process.kill()
            process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream and not stream.closed:
                stream.close()
    ordered = sorted(durations)
    quantiles = {f"p{p}_ms": ordered[math.ceil(len(ordered) * p / 100) - 1] / 1e6
                 for p in (50, 95, 99)}
    return {"schema": "hepta.native-task-head-cost.v1", "status": "MEASURED_RESEARCH_ONLY",
        "mode": "SHADOW_ONLY", "authority": "DENY_ALL",
        "task_admission_allowed": False, "action_execution_allowed": False,
        "production_activation_allowed": False, "target_device_qualified": False,
        "energy_joules": None, "energy_measurement": "unavailable",
        "scope": "one resident task Head; complete text+image rows; zero state; JSONL round trip",
        "encoder_calls": 0, "policy_actions_measured": False,
        "source_metadata_is_compiler_attestation": False,
        "numerical_parity_established_by_this_measurement": False,
        "native_binary_sha256": before[0][0], "manifest_sha256": before[1][0],
        "weights_sha256": before[2][0], "requests_sha256": before[3][0],
        "feature_identity": spec["feature_identity"], "source_identity": _json(source_raw),
        "cost_source_sha256": cost_source_digest,
        "input_rows": input_rows, "complete_input_rows": len(selected),
        "missing_input_rows_excluded_before_measurement": missing_rows,
        "selection": "presence-only; source order; cyclic; no labels or confidence selection",
        "warmup_rows": warmup, "measured_rows": samples,
        "measured_ordered_request_digests_sha256": request_order.hexdigest(),
        "distinct_executed_requests": len(prediction_hashes),
        "latency": {**quantiles, "mean_ms": sum(durations) / samples / 1e6,
            "raw_nanoseconds": durations, "quantile_method": "nearest_rank",
            "includes": "pipe IO; native JSON decode/inference/encode; Python response JSON decode",
            "excludes": "Encoder; request construction; startup; input/response validation"},
        "spawn_to_first_response_ms": first_response_ms,
        "measurement_loop_wall_ms_including_validation": measured_wall_ms,
        "native_rss_after_warmup": warmup_rss, "native_rss_after_measurement": final_rss,
        "native_rss_source": "proc status verified by PPid/NSpid/exe/starttime; Linux kB times 1024",
        "wait4_process_lifetime_peak_rss_bytes": int(usage.ru_maxrss * 1024),
        "wait4_peak_may_include_pre_exec_parent_memory": True,
        "wait4_peak_is_native_resident_memory": False,
        "wait4_source": "os.wait4(exact child), Linux ru_maxrss KiB multiplied by 1024",
        "native_process_user_cpu_seconds": usage.ru_utime,
        "native_process_system_cpu_seconds": usage.ru_stime,
        "stderr_retained_sha256": _sha(bytes(stderr_bytes)),
        "runtime": {"platform": platform.system(), "machine": platform.machine(),
                    "python": platform.python_version()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "manifest", "weights", "requests", "expected-manifest-sha256",
                 "expected-requests-sha256", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--source-identity", help="JSON metadata file, not compiler attestation")
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--samples", type=int, default=1000)
    args = parser.parse_args()
    source = None if args.source_identity is None else _json(_file(args.source_identity, 65536, payload=True)[1])
    result = run_cost(args.binary, args.manifest, args.weights, args.requests,
        args.expected_manifest_sha256, args.expected_requests_sha256,
        warmup=args.warmup, samples=args.samples, source_identity=source)
    with Path(args.output).open("x", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
