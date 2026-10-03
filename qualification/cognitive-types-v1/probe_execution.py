"""Bounded POSIX execution and strict JSON reports for the existing codec probe.

A parser error, resource limit or process failure is infrastructure-invalid,
never a semantic rejection. These helpers confer no qualification authority.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import selectors
import signal
import subprocess
import time

# Match the existing probe ceiling and retain one byte for oversize rejection tests.
MAX_INPUT_BYTES = 1_048_576 + 1_024 + 1
MAX_STDOUT_BYTES = 64 * 1024
MAX_STDERR_BYTES = 256 * 1024
PROBE_TIMEOUT_SECONDS = 60


class ProbeError(ValueError):
    """The probe did not deliver one complete, bounded, unambiguous report."""


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ProbeError("duplicate probe JSON key")
        value[key] = item
    return value


def _noninteger(_value):
    raise ProbeError("probe JSON numbers must be integers")


def _integer(value):
    if len(value.lstrip("-")) > 39:
        raise ProbeError("probe JSON integer exceeds the u128 report range")
    integer = int(value)
    if not -(2**127) <= integer < 2**128:
        raise ProbeError("probe JSON integer exceeds the report range")
    return integer


def parse_report(data: bytes) -> dict:
    if not data or len(data) > MAX_STDOUT_BYTES:
        raise ProbeError("empty or oversized probe report")
    report = json.loads(data.decode("utf-8"), object_pairs_hook=_object,
                        parse_constant=_noninteger, parse_float=_noninteger,
                        parse_int=_integer)
    if type(report) is not dict or report.get("outcome") not in ("accepted", "rejected"):
        raise ProbeError("probe report must be an object with a recognized outcome")
    return report


def same_typed_value(actual, expected) -> bool:
    """Python equality alone equates true/1 and 1.0/1; wire evidence must not."""
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        return actual.keys() == expected.keys() and all(
            same_typed_value(actual[key], value) for key, value in expected.items())
    if type(expected) is list:
        return len(actual) == len(expected) and all(
            same_typed_value(a, b) for a, b in zip(actual, expected, strict=True))
    return actual == expected


def _terminate_group(process):
    # The group belongs exclusively to this invocation. Kill it even after the
    # direct child exits, so inherited pipes cannot leave grandchildren running.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    finally:
        process.wait(timeout=5)


def _capture(argv, wire, timeout):
    if os.name != "posix":
        raise ProbeError("bounded probe execution requires the qualified POSIX host")
    if type(wire) is not bytes or len(wire) > MAX_INPUT_BYTES:
        raise ProbeError("invalid or oversized probe input")
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x for x in argv):
        raise ProbeError("invalid probe command")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ProbeError("invalid probe deadline")
    deadline = time.monotonic() + timeout
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    captured = {"stdout": bytearray(), "stderr": bytearray()}
    limits = {"stdout": MAX_STDOUT_BYTES, "stderr": MAX_STDERR_BYTES}
    offset = 0
    try:
        with selectors.DefaultSelector() as selector:
            for name in ("stdout", "stderr"):
                stream = getattr(process, name)
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            if wire:
                os.set_blocking(process.stdin.fileno(), False)
                selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
            else:
                process.stdin.close()
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProbeError("probe deadline exceeded")
                for key, _ in selector.select(min(remaining, 0.1)):
                    stream, name = key.fileobj, key.data
                    if name == "stdin":
                        try:
                            offset += os.write(stream.fileno(), memoryview(wire)[offset:offset + 65536])
                        except BrokenPipeError:
                            offset = len(wire)
                        except BlockingIOError:
                            continue
                        if offset == len(wire):
                            selector.unregister(stream)
                            stream.close()
                        continue
                    try:
                        chunk = os.read(stream.fileno(), min(65536, limits[name] - len(captured[name]) + 1))
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(stream)
                        stream.close()
                    elif len(captured[name]) + len(chunk) > limits[name]:
                        raise ProbeError(f"probe {name} byte limit exceeded")
                    else:
                        captured[name].extend(chunk)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProbeError("probe deadline exceeded")
            returncode = process.wait(timeout=remaining)
            # Closed pipes and a zero leader exit do not close descendants that
            # redirected their own output. Cleanup in finally is not success.
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                pass
            else:
                raise ProbeError("probe leader exited with residual descendants")
        return returncode, bytes(captured["stdout"]), bytes(captured["stderr"])
    finally:
        try:
            _terminate_group(process)
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()


def invoke_probe(argv, wire, expected=None, *, timeout=PROBE_TIMEOUT_SECONDS):
    """Execute the real configured probe; no mock or fallback implementation."""
    try:
        code, stdout, stderr = _capture(argv, wire, timeout)
        report = parse_report(stdout)
        if code not in (0, 2) or (code == 0) != (report["outcome"] == "accepted"):
            raise ProbeError("probe exit code and report outcome are inconsistent")
        if expected is not None and type(expected) is not dict:
            raise ProbeError("expected probe result must be an object")
        passed = code == 2 if expected is None else (
            code == 0 and all(key in report and same_typed_value(report[key], value)
                              for key, value in expected.items()))
        return {"passed": passed, "status": "passed" if passed else "failed", "argv": argv,
                "exit_code": code, "report": report,
                "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
                "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
                "stderr": stderr.decode(errors="replace")[-4000:]}
    except (OSError, ValueError, RecursionError, subprocess.SubprocessError) as error:
        return {"passed": False, "status": "infrastructure_invalid", "error": str(error), "argv": argv}
