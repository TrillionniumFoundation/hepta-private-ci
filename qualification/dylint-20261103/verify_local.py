#!/usr/bin/env python3
"""Replay preserved local evidence and compare every recorded source input."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import zipfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_bytes(data, expected):
    require(len(data) == expected["bytes"], "byte length differs")
    require(hashlib.sha256(data).hexdigest() == expected["sha256"], "SHA-256 differs")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(__debug__, "optimized Python is not accepted for evidence replay")
    root = args.repository.resolve()
    evidence = root / "qualification/dylint-20261103"
    manifest = json.loads((evidence / "local-evidence.json").read_bytes())
    contents = {}
    for name, row in manifest["archives"].items():
        verify_bytes((evidence / name).read_bytes(), row)
        with zipfile.ZipFile(evidence / name) as archive:
            names = archive.namelist()
            require(len(names) == len(set(names)), "duplicate archive member")
            require(set(names) == set(row["members"]), "archive members differ")
            require(sum(info.file_size for info in archive.infolist()) < 20 * 1024 * 1024,
                    "archive exceeds its uncompressed bound")
            require(archive.testzip() is None, "archive CRC failure")
            for member in names:
                path = PurePosixPath(member)
                require(not path.is_absolute() and ".." not in path.parts, "unsafe member path")
                data = archive.read(member)
                verify_bytes(data, row["members"][member])
                require(member not in contents, "ambiguous evidence member")
                contents[member] = data
    original = manifest["original_failure"]
    compressed = (evidence / original["file"]).read_bytes()
    verify_bytes(compressed, original["compressed"])
    negative = gzip.decompress(compressed)
    verify_bytes(negative, original["decoded"])
    require(b"revspec 'master' not found" in negative and b"dylint_driver v5.0.0" in negative,
            "original upstream branch failure is missing")
    tests = json.loads(contents["maintained-original-local-tests.json"])
    require(tests["exit"] == 0 and tests["source_before"] == tests["source_after"],
            "local test command failed or source changed")
    require(tests["toolchain"] == "nightly-2025-09-18", "original nightly changed")
    require(tests["command"] == ["just", "test", "--manifest-path",
            "../tools/argument-comment-lint/Cargo.toml", "--config",
            "../tools/argument-comment-lint/.cargo/config.toml", "--profile", "default",
            "--locked", "--no-tests=fail", "--retries", "0"], "test command differs")
    log = contents["maintained-original-local-tests.log"]
    verify_bytes(log, {"bytes": tests["log_bytes"], "sha256": tests["log_sha256"]})
    require(b"8 tests run: 8 passed (1 slow), 0 skipped" in log, "original test summary differs")
    require(len(re.findall(rb"^\s*PASS \[", log, re.MULTILINE)) == 8, "test case count differs")
    require(re.search(rb"PASS \[[^\]]+\] \(8/8\) argument_comment_lint ui", log),
            "original UI case did not pass")
    wrappers = json.loads(contents["wrapper-tests.json"])
    require(wrappers["exit"] == 0 and b"Ran 6 tests" in contents["wrapper-tests.stderr"],
            "original wrapper tests failed")
    lock = json.loads(contents["successful/receipt.json"])
    before = json.loads(contents["successful/source-inputs.json"])
    require(lock["status"] == "generated-not-committed-qualification", "generation scope differs")
    require(not lock["committed_lock_required"] and not lock["committed_lock_matches"],
            "local generation was incorrectly presented as committed qualification")
    require(lock["source_after"] == before and lock["source_inputs_unchanged"], "lock inputs changed")
    require([(step["name"], step["command"], step["exit"]) for step in lock["steps"]] == [
        ("original-lock-update", ["just", "bazel-lock-update"], 0),
        ("original-lock-check", ["./scripts/check-module-bazel-lock.sh"], 0),
    ], "original lock commands did not both pass")
    for name, row in lock["outputs"].items():
        verify_bytes(contents["successful/" + name], row)
    require((root / "MODULE.bazel.lock").read_bytes() == contents["successful/MODULE.bazel.lock"],
            "generated lock differs from the candidate")
    for inventory in [tests["source_before"], before]:
        for name, expected in inventory.items():
            require(hashlib.sha256((root / name).read_bytes()).hexdigest() == expected,
                    "recorded input differs: " + name)
    report = {"local_original_tests": 8, "skipped": 0, "original_wrapper_tests": 6,
              "test_inputs": len(tests["source_before"]), "lock_inputs": len(before),
              "generated_lock_sha256": lock["generated_lock_sha256"],
              "original_negative_retained": True, "committed_hosted_qualification": "pending"}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
