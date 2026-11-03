#!/usr/bin/env python3
"""Verify retained original failed ZIPs without executing their contents."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

COMMIT = "ae2876036274e3be07af122fb80cb3d18acf92d5"
ARTIFACTS = [
    (13266619365, 41643, "aeec407cdd6dac00a129c153864a25266e26d3c675be02760a8e4c567f745533", "linux", 260, 1),
    (13266689342, 41617, "3dc751bc5902ee20885df0c546137a065beef6804f57a41e02062a88ed792481", "windows", 251, 1),
    (13267774672, 42555, "24604f91937b564489bc706c8e38ea6b17df36d4523465c8242d0324c4979a4e", "macos", 271, 4),
]
TARGETS = ["//codex-rs/exec-server:exec-server-authorized_read_rpc-test",
           "//codex-rs/exec-server:exec-server-unit-tests",
           "//codex-rs/file-system:file-system-unit-tests"]
TIMEOUT_CASE = "remote::tests::connect_environment_times_out_when_registry_response_body_stalls"
MAC_CASES = {
    "local_file_system::authorized_read_tests::stable_handle_bounded_read_never_returns_oversize_prefix",
    "local_file_system::authorized_read_tests::stable_handle_read_authorizes_resolved_symlink_target",
    "local_file_system::authorized_read_tests::stable_handle_read_keeps_authorized_handle_after_later_hardlink",
}


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def counts(log):
    return [tuple(map(int, row)) for row in re.findall(
        r"test result: (?:ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out", log)]


def main():
    require(__debug__, "optimized Python cannot verify evidence")
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    git_inputs = {}
    rows = []
    for artifact, length, digest, host, passed, failed in ARTIFACTS:
        path = args.artifacts / (str(artifact) + ".zip")
        data = path.read_bytes()
        require(len(data) == length and sha(data) == digest, "original ZIP identity differs")
        with zipfile.ZipFile(path) as archive:
            require(archive.testzip() is None, "original ZIP CRC differs")
            members = archive.infolist()
            require(len({i.filename for i in members}) == len(members), "duplicate ZIP member")
            files = {}
            for info in members:
                p = PurePosixPath(info.filename)
                require(not p.is_absolute() and ".." not in p.parts and "\\" not in info.filename,
                        "unsafe ZIP member")
                require(not stat.S_ISLNK(info.external_attr >> 16), "symlink ZIP member")
                if not info.is_dir():
                    files[info.filename] = archive.read(info)
        receipt = json.loads(files["receipt.json"])
        before = json.loads(files["source-inputs.json"])
        require(receipt["commit"] == COMMIT and receipt["status"] == "failed", "negative source/status differs")
        require(receipt["config"] == "ci-" + host, "native platform differs")
        require(len(before) == 182 and receipt["source_after"] == before and receipt["source_inputs_unchanged"],
                "original source snapshot differs")
        for name, expected in before.items():
            if name not in git_inputs:
                blob = subprocess.check_output(["git", "-C", str(args.repository), "show", COMMIT + ":" + name])
                git_inputs[name] = sha(blob)
            require(git_inputs[name] == expected, "exact immutable Git input differs: " + name)
        require(set(receipt["outputs"]) == set(files) - {"receipt.json"}, "output manifest coverage differs")
        for name, expected in receipt["outputs"].items():
            require(expected == {"bytes": len(files[name]), "sha256": sha(files[name])}, "output differs: " + name)
        steps = {step["name"]: step for step in receipt["steps"]}
        original = steps["original-rpc-and-unit-tests"]
        require(original["exit"] == 3 and original["command"][-3:] == TARGETS,
                "original failed target execution differs")
        require("--nocache_test_results" in original["command"] and "--test_output=all" in original["command"],
                "original uncached complete execution differs")
        require(not any("filter" in arg for arg in original["command"]), "unexpected case filter")
        require(steps["original-testlog-location"]["exit"] == 0 and "original-clippy" not in steps,
                "negative execution boundary differs")
        if host == "linux":
            require(receipt["steps"][0]["name"] == "committed-lock-check" and receipt["steps"][0]["exit"] == 0,
                    "committed lock was not checked first")
        summaries = {}
        for target in TARGETS:
            name = target.split(":")[1]
            log = files[name + ".log"].decode()
            summary = counts(log)
            if target == TARGETS[0]:
                expected = [(0, 1, 0, 0, 0)] if host == "macos" else [(1, 0, 0, 0, 0)]
                expected_errors = int(host == "macos")
                if host != "macos":
                    require("test authorized_read_rpc_is_capability_gated_and_denies_outside_root ... ok" in log,
                            "original capability RPC did not pass")
            elif target == TARGETS[1]:
                expected = [(passed, failed, 0, 0, 0)]
                expected_errors = 1
                failures = set(re.findall(r"^test (\S+) \.\.\. FAILED$", log, re.MULTILINE))
                require(failures == {TIMEOUT_CASE} | (MAC_CASES if host == "macos" else set()),
                        "original failed case set differs")
            else:
                expected = [] if host == "windows" else [(0, 0, 0, 0, 0)]
                expected_errors = 0
            require(summary == expected, "complete original Rust count differs: " + name)
            suites = list(ET.fromstring(files[name + ".xml"]).iter("testsuite"))
            require(len(suites) == 1 and int(suites[0].get("tests", "0")) == 1,
                    "original wrapper XML count differs")
            require(int(suites[0].get("failures", "0")) == 0
                    and int(suites[0].get("errors", "0")) == expected_errors
                    and int(suites[0].get("skipped", "0")) == 0
                    and not list(suites[0].iter("skipped")), "original wrapper XML result differs")
            summaries[target] = summary
        rows.append({"artifact_id": artifact, "bytes": length, "sha256": digest,
                     "platform": host, "exact_git_inputs": len(before), "outputs_verified": len(receipt["outputs"]),
                     "source_before_after_equal": True, "original_test_counts": summaries,
                     "original_suite_result": "FAILED", "clippy_reached": False})
    result = {"commit": COMMIT, "run_id": 41710889184, "unique_exact_git_inputs": len(git_inputs),
              "original_artifacts": rows, "all_native_scopes_qualified": False,
              "verification": "All retained original negative identities, bytes, inputs and execution boundaries verified"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"verified_original_negative_artifacts": len(rows), "exact_git_inputs": len(git_inputs),
                      "all_native_scopes_qualified": False}))


if __name__ == "__main__":
    main()
