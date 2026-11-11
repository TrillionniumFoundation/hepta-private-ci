#!/usr/bin/env python3
"""Focused recorder failures only; zero executions of the actual Cargo model."""

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import struct
import sys
import tempfile
import time
from unittest.mock import patch

import differential


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def rejected_main(arguments, output):
    with patch.object(sys, "argv", ["differential.py", *arguments, "--output", str(output)]):
        try:
            differential.main()
        except SystemExit as exit_status:
            require(exit_status.code == 1, "Failure boundary exited successfully")
        else:
            raise RuntimeError("Expected a nonzero failure boundary exit")
    receipt = json.loads((output / "RESULTS.json").read_text())
    require(receipt["passed"] is False and receipt["status"] == "failed_exception", "Failure receipt was not closed")
    require(receipt["physical_helper_attempts"] == 0, "Boundary check unexpectedly launched the actual helper")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repository", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--helper", required=True, type=Path)
    parser.add_argument("--expected-helper-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    common = ["--source-repository", str(args.source_repository), "--checkpoint", str(args.checkpoint),
              "--helper", str(args.helper)]
    bad_identity = rejected_main(common + ["--expected-helper-sha256", "0" * 64], args.output / "bad-helper-identity")
    require(bad_identity["registration_sha256"] is None, "Bad helper identity was registered")

    # The injected cleanup failure occurs after an intentionally mocked success.
    # This exercises the failure flag only and does not evaluate model tensors.
    original_donor = differential.donor_modules

    @contextmanager
    def cleanup_failure(repository):
        with original_donor(repository) as donor:
            yield donor
        raise RuntimeError("intentional post-comparison cleanup failure")

    with patch.object(differential, "run", return_value={"passed": True}), patch.object(
            differential, "donor_modules", cleanup_failure):
        cleanup = rejected_main(common + ["--expected-helper-sha256", args.expected_helper_sha256],
                                args.output / "post-success-cleanup")
    require("intentional post-comparison cleanup failure" in cleanup["error"], "Wrong cleanup boundary")

    command = b"\x00" + struct.pack("<Q", 17) + b"\x00"
    absent = args.output / "launch-failure"
    absent.mkdir()
    missing = differential.Helper(absent / "intentionally-absent-executable", b"", b"", absent)
    try:
        missing.call("controlled-launch-failure", b"", b"", command)
    except RuntimeError:
        pass
    else:
        raise RuntimeError("Missing executable was accepted")
    record = json.loads((absent / "CALLS.json").read_text())[0]
    require(record["launched"] is False and record["pid"] is None and record["launch_error"], "Missing launch receipt")

    malformed = args.output / "malformed-response"
    malformed.mkdir()
    with tempfile.TemporaryDirectory(prefix="hepta-negative-response-") as temporary:
        stub = Path(temporary) / "controlled-invalid-response"
        stub.write_text("#!/bin/sh\ncat >/dev/null\nprintf 'malformed-response'\n")
        stub.chmod(0o700)
        helper = differential.Helper(stub, b"", b"", malformed)
        try:
            helper.call("controlled-invalid-response-not-a-model", b"", b"", command)
        except ValueError as error:
            require("response checksum" in str(error), "Wrong response failure boundary")
        else:
            raise RuntimeError("Malformed response was accepted")
    raw = (malformed / "response-000.bin").read_bytes()
    record = json.loads((malformed / "CALLS.json").read_text())[0]
    require(raw == b"malformed-response" and record["response_sha256"] == differential.digest(raw), "Raw failed response missing")
    receipt = {
        "schema": "hepta.joint-differential-failure-boundaries.v1", "passed": True,
        "validator_sha256": differential.digest(Path(differential.__file__).read_bytes()),
        "checks": ["bad helper identity has a failed prelaunch receipt", "post-success cleanup error forces exit 1",
                   "Popen failure is recorded without a launched child", "malformed response raw bytes are retained before rejection"],
        "actual_cargo_helper_executions": 0, "new_training_updates": 0,
        "controlled_invalid_response_processes": 1,
        "controlled_response_process_wall_seconds": record["wall_seconds"],
        "controlled_response_process_cpu_seconds": record["child_cpu_seconds"],
        "wall_seconds": time.perf_counter() - started, "parent_cpu_seconds": time.process_time() - cpu,
        "scope": "Recorder failure behavior only. The one shell response stub and mocked comparison are not model or ordinary-owner qualification.",
    }
    differential.write_json(args.output / "RESULTS.json", receipt)
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
