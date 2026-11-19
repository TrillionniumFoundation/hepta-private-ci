"""Linux command envelope for trusted PERC campaigns that do not detach children.

Measures the child invocation, including its imports, startup and bookkeeping.
It is not a sandbox, billing receipt, energy meter or historical attestation.
The command must wait for its descendants; detached work is outside this meter.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


class _Cancelled(BaseException):
    pass


def _digest(path):
    digest, count = hashlib.sha256(), 0
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            count += len(chunk)
    return {"sha256": digest.hexdigest(), "bytes": count}


def _wait(pid, deadline, state):
    while True:
        previous = signal.pthread_sigmask(
            signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM}
        )
        try:
            found, status, usage = os.wait4(pid, os.WNOHANG)
            if found:
                state.update(
                    reaped=True,
                    returncode=os.waitstatus_to_exitcode(status),
                    usage=usage,
                )
        finally:
            # A pending cancellation can raise here, after state is retained.
            signal.pthread_sigmask(signal.SIG_SETMASK, previous)
        if found:
            return state["returncode"], state["usage"]
        if time.monotonic() >= deadline:
            raise subprocess.TimeoutExpired([str(pid)], 0)
        time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))


def _stop(pid, grace):
    try:
        os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
    except ChildProcessError:
        return (
            None,
            None,
        )  # An external reaper consumed it; never signal reused identity.
    # Do not reap the session leader until both signals have been sent: its
    # unreaped PID prevents an unrelated new process group reusing this identity.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            pass
        if sig == signal.SIGTERM:
            time.sleep(grace)
    _, status, usage = os.wait4(pid, 0)
    return os.waitstatus_to_exitcode(status), usage


def run(
    argv,
    output_dir,
    *,
    cwd=None,
    timeout_seconds=600.0,
    grace_seconds=1.0,
    source_paths=(),
):
    """Retain one command's measured lifecycle and return its immutable receipt.

    Linux wait4 supplies per-invocation CPU and largest waited-process RSS,
    avoiding cumulative child accounting and unrelated-child high-water marks.
    A caller-supplied source list pins bytes, not which code the command loaded.
    """
    if sys.platform != "linux":
        raise RuntimeError("PERC process envelope requires Linux wait4")
    if (
        not isinstance(argv, (list, tuple))
        or not 0 < len(argv) <= 256
        or any(type(a) is not str or not a or "\0" in a for a in argv)
        or sum(len(a.encode()) for a in argv) > 262144
    ):
        raise ValueError("bounded explicit argv required; no shell command string")
    if not (
        math.isfinite(timeout_seconds)
        and 0 < timeout_seconds <= 86400
        and math.isfinite(grace_seconds)
        and 0 <= grace_seconds <= 60
    ):
        raise ValueError("invalid timeout or grace period")
    if len(source_paths) > 256:
        raise ValueError("too many source paths")
    directory = Path(cwd or os.getcwd()).resolve(strict=True)
    sources = [Path(p).resolve(strict=True) for p in source_paths]
    if len(set(sources)) != len(sources):
        raise ValueError("duplicate source paths")
    output = Path(output_dir).absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(mode=0o700)  # Atomic create; existing directories/symlinks fail.
    meter_start, meter_cpu = time.perf_counter_ns(), time.process_time_ns()
    meter_path = Path(__file__).resolve()
    meter_before = _digest(meter_path)
    before = {str(p): _digest(p) for p in sources}
    request = {
        "argv": list(argv),
        "cwd": str(directory),
        "sources": before,
        "timeout_seconds": timeout_seconds,
        "grace_seconds": grace_seconds,
    }
    (output / "request.json").write_text(json.dumps(request, sort_keys=True) + "\n")
    outcome, returncode, usage, process = "launch_failed", None, None, None
    state = {"reaped": False, "returncode": None, "usage": None}
    errors, cancellation = [], None
    command_start = time.perf_counter_ns()
    with (
        (output / "stdout.bin").open("xb", buffering=0) as stdout,
        (output / "stderr.bin").open("xb", buffering=0) as stderr,
    ):
        try:
            process = subprocess.Popen(
                argv,
                cwd=directory,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            try:
                returncode, usage = _wait(
                    process.pid, time.monotonic() + timeout_seconds, state
                )
                outcome = "succeeded" if returncode == 0 else "failed"
            except subprocess.TimeoutExpired:
                outcome = "timed_out"
                returncode, usage = _stop(process.pid, grace_seconds)
            except (KeyboardInterrupt, _Cancelled) as error:
                outcome = "cancelled"
                cancellation = (
                    error.args[0] if isinstance(error, _Cancelled) else "SIGINT"
                )
                if state["reaped"]:
                    returncode, usage = state["returncode"], state["usage"]
                else:
                    returncode, usage = _stop(process.pid, grace_seconds)
            process.returncode = returncode  # wait4 already reaped this exact child.
        except OSError as error:
            errors.append(
                {
                    "type": type(error).__name__,
                    "errno": error.errno,
                    "message": str(error),
                }
            )
    command_end = time.perf_counter_ns()
    live_group = False
    if process is not None and returncode is not None:
        try:
            os.killpg(
                process.pid, 0
            )  # Observation only; never signal a reaped identity.
            live_group = True
        except ProcessLookupError:
            pass
    after = {}
    for path in sources:
        try:
            after[str(path)] = _digest(path)
        except OSError as error:
            after[str(path)] = {"error": type(error).__name__}
    streams = {
        name: dict(path=name + ".bin", **_digest(output / (name + ".bin")))
        for name in ("stdout", "stderr")
    }
    meter_after = _digest(meter_path)
    cpu = None if usage is None else round((usage.ru_utime + usage.ru_stime) * 1e9)
    receipt = dict(
        schema="perc1.process-envelope.v1",
        outcome=outcome,
        returncode=returncode,
        pid=process.pid if process else None,
        cancellation=cancellation,
        command_wall_ns=command_end - command_start,
        waited_cpu_ns=cpu,
        largest_waited_process_rss_bytes=None
        if usage is None
        else usage.ru_maxrss * 1024,
        rss_scope="Linux wait4 ru_maxrss; largest waited process, not simultaneous group RSS",
        live_process_group_after_leader=live_group,
        source_before=before,
        source_after=after,
        sources_unchanged=before == after,
        request_sha256=_digest(output / "request.json")["sha256"],
        meter_before=meter_before,
        meter_after=meter_after,
        streams=streams,
        errors=errors,
        measurement_valid=usage is not None
        and not errors
        and not live_group
        and before == after
        and meter_before == meter_after,
        meter_postprocessing_wall_ns=time.perf_counter_ns() - command_end,
        meter_observed_wall_ns=time.perf_counter_ns() - meter_start,
        meter_observed_cpu_ns=time.process_time_ns() - meter_cpu,
        provider_billing=None,
        energy_joules=None,
        scientific_qualified=False,
        complete_process_tree_measured=None,
        cpu_scope="wait4 leader plus descendants it reaped; un-reaped descendants excluded, including after timeout/cancellation",
        scope="trusted non-detaching command lifecycle; waited descendants only; meter import/startup and final receipt write excluded; no complete physical-cost claim",
    )
    with (output / "receipt.json").open("x") as stream:
        json.dump(receipt, stream, sort_keys=True)
        stream.write("\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--cwd")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--grace", type=float, default=1.0)
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("argv", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
    cancelling = False

    def cancel(signum, frame):
        nonlocal cancelling
        if not cancelling:
            cancelling = True
            raise _Cancelled(signum)

    previous = {s: signal.signal(s, cancel) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        result = run(
            argv,
            args.output,
            cwd=args.cwd,
            timeout_seconds=args.timeout,
            grace_seconds=args.grace,
            source_paths=args.source,
        )
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["outcome"] == "succeeded" and result["measurement_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
