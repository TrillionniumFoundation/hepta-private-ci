#!/usr/bin/env python3
"""Independently verify exact native authorized-read artifacts, without running recovered code."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import xml.etree.ElementTree as ET
import zipfile

COMMIT = "aaf74551dccf99f2d0d1525d02337cf804233817"
ARTIFACTS = [
    (13270394401, 46592, "3400116f04947e40e6f660cc601547127e6145885eae9b4aeaaa29faf6bc7515", "windows", 252),
    (13271262602, 45537, "faea4bc6190ef3bdc09e09c4a865f333dd21c11645ecba4cac884c488d064f60", "macos", 275),
    (13270792583, 45525, "7b637d90a318e54b10b3507e9b17b5c0416f3656bf119415fe0159d0492ad1f1", "linux", 261),
]
TARGETS = ["//codex-rs/exec-server:exec-server-authorized_read_rpc-test",
           "//codex-rs/exec-server:exec-server-unit-tests",
           "//codex-rs/file-system:file-system-unit-tests"]
CLIPPY = [TARGETS[0], TARGETS[1] + "-bin", TARGETS[2] + "-bin"]


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    require(__debug__, "optimized Python cannot verify evidence")
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    git_inputs = {}
    rows = []
    for artifact, length, digest, host, unit_count in ARTIFACTS:
        path = args.artifacts / (str(artifact) + ".zip")
        data = path.read_bytes()
        require(len(data) == length and sha(data) == digest, "original ZIP identity differs")
        with zipfile.ZipFile(path) as archive:
            require(archive.testzip() is None, "ZIP CRC differs")
            members = archive.infolist()
            require(len({i.filename for i in members}) == len(members), "duplicate ZIP member")
            files = {}
            for info in members:
                p = PurePosixPath(info.filename)
                require(not p.is_absolute() and ".." not in p.parts and "\\" not in info.filename,
                        "unsafe ZIP path")
                require(not stat.S_ISLNK(info.external_attr >> 16), "symlink ZIP entry")
                if not info.is_dir():
                    files[info.filename] = archive.read(info)
        receipt = json.loads(files["receipt.json"])
        before = json.loads(files["source-inputs.json"])
        require(receipt["commit"] == COMMIT and receipt["status"] == "passed", "source/status differs")
        require(receipt["config"] == "ci-" + host, "native platform differs")
        require(len(before) == 189 and receipt["source_after"] == before and receipt["source_inputs_unchanged"],
                "input before/after identity differs")
        for name, expected in before.items():
            if name not in git_inputs:
                blob = subprocess.check_output(["git", "-C", str(args.repository), "show", COMMIT + ":" + name])
                git_inputs[name] = sha(blob)
            require(git_inputs[name] == expected, "immutable Git input differs: " + name)
        require(set(receipt["outputs"]) == set(files) - {"receipt.json"}, "output coverage differs")
        for name, expected in receipt["outputs"].items():
            require(expected == {"bytes": len(files[name]), "sha256": sha(files[name])}, "output differs: " + name)
        names = [step["name"] for step in receipt["steps"]]
        expected_names = (["committed-lock-check"] if host == "linux" else []) + [
            "original-rpc-and-unit-tests", "original-testlog-location", "original-clippy-selector", "original-clippy"]
        require(names == expected_names and all(step["exit"] == 0 for step in receipt["steps"]),
                "original execution order or exits differ")
        steps = {step["name"]: step for step in receipt["steps"]}
        command = steps["original-rpc-and-unit-tests"]["command"]
        require(command[-3:] == TARGETS and "--nocache_test_results" in command and "--test_output=all" in command,
                "complete original targets differ")
        require(not any("filter" in arg for arg in command), "unexpected test filter")
        require(steps["original-clippy"]["command"][-3:] == CLIPPY
                and "--config=clippy" in steps["original-clippy"]["command"], "original Clippy targets differ")
        if host == "windows":
            require("--windows-msvc-host-platform" in command and "--platforms=//:windows_x86_64_msvc" in command,
                    "native MSVC flags differ")
            require(receipt["bash_executable"].endswith("Git\\usr\\bin\\bash.exe"), "native Git Bash differs")
        summaries = {}
        for index, target in enumerate(TARGETS):
            name = target.split(":")[1]
            log = files[name + ".log"].decode()
            expected_count = [1, unit_count, 0][index]
            counts = [tuple(map(int, row)) for row in re.findall(
                r"test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out", log)]
            expected = [] if index == 2 and host == "windows" else [(expected_count, 0, 0, 0, 0)]
            require(counts == expected, "complete Rust count differs: " + name)
            require(receipt["test_counts"][target] == list(map(str, [expected_count, 0, 0, 0, 0])),
                    "recorded count differs")
            # Two original process tests print child kill diagnostics before
            # their final `ok`; preserve those lines rather than dropping cases.
            blocks = re.findall(r"^test (\S+) \.\.\. (.*?)(?=^test |\ntest result:|\Z)", log, re.MULTILINE | re.DOTALL)
            require(len(blocks) == expected_count and len({case for case, _ in blocks}) == expected_count
                    and all(body.rstrip().endswith("ok") for _, body in blocks), "per-case completion differs")
            if index == 0:
                require(blocks[0][0] == "authorized_read_rpc_is_capability_gated_and_denies_outside_root",
                        "original capability/denial RPC differs")
            if index == 1:
                require("remote::tests::connect_environment_times_out_when_registry_response_body_stalls"
                        in {case for case, _ in blocks}, "original timeout case missing")
            suites = list(ET.fromstring(files[name + ".xml"]).iter("testsuite"))
            require(len(suites) == 1 and int(suites[0].get("tests", "0")) == 1,
                    "original wrapper XML count differs")
            require(all(int(suites[0].get(key, "0")) == 0 for key in ["errors", "failures", "skipped"])
                    and not list(suites[0].iter("skipped")), "wrapper XML records failure or skip")
            summaries[target] = {"rust_cases_passed": expected_count, "wrapper_executed": True}
        original_output = files["original-rpc-and-unit-tests.stdout"].decode()
        require("Executed 3 out of 3 tests: 3 tests pass." in original_output, "original uncached execution missing")
        require(all(re.search(re.escape(target) + r"\s+PASSED in", original_output) for target in TARGETS),
                "original target success line missing")
        require("Build completed successfully" in files["original-clippy.stdout"].decode(), "Clippy completion missing")
        rows.append({"artifact_id": artifact, "bytes": length, "sha256": digest, "platform": host,
                     "exact_git_inputs": len(before), "outputs_verified": len(receipt["outputs"]),
                     "source_before_after_equal": True, "original_test_counts": summaries,
                     "native_test_executions": unit_count + 1, "ignored_or_filtered_cases": 0,
                     "original_clippy_targets": CLIPPY, "original_command_exits": [0] * len(names)})
    result = {"commit": COMMIT, "run_id": 41717707968, "unique_exact_git_inputs": len(git_inputs),
              "original_artifacts": rows, "native_test_executions": sum(row["native_test_executions"] for row in rows),
              "all_three_original_scopes_qualified": True, "full_repository_ci_qualified": False,
              "empty_wrapper_counted_as_positive_rust_coverage": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"verified_original_artifacts": len(rows), "exact_git_inputs": len(git_inputs),
                      "native_test_executions": result["native_test_executions"]}))


if __name__ == "__main__":
    main()
