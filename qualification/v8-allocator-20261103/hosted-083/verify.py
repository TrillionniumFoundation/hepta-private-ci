#!/usr/bin/env python3
"""Independently inspect exact V8 qualification outputs without running them."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parent
REPO = None
HEAD = "083116160fe81198ae0c441aad22224c0c8d2940"
parser = argparse.ArgumentParser()
parser.add_argument("--platform", choices=["windows", "linux"], required=True)
parser.add_argument("--repo", type=Path, required=True)
args = parser.parse_args()
REPO = args.repo
WINDOWS = args.platform == "windows"
ARTIFACT = 13267549502 if WINDOWS else 13267688340
EXPECTED_BYTES = 35911 if WINDOWS else 45914
EXPECTED_SHA = "2d925abae2eaed19bf813a3dd6d16d691250e8eb94a34b30c85b57afd2d81d12" if WINDOWS else "017f38fcb48e70065b6d3ad07067dc81f07d5717a94e9e17896ed10b7dafb16e"

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def git(*args):
    return subprocess.check_output(["git", *args], cwd=REPO)

def main():
    archive = ROOT / (str(ARTIFACT) + ".zip")
    directory = ROOT / str(ARTIFACT)
    raw = archive.read_bytes()
    require(len(raw) == EXPECTED_BYTES and sha(raw) == EXPECTED_SHA, "GitHub artifact identity")
    with zipfile.ZipFile(archive) as bundle:
        require(bundle.testzip() is None, "archive CRC")
        for entry in bundle.infolist():
            path = Path(entry.filename)
            require(not path.is_absolute() and ".." not in path.parts and (entry.external_attr >> 16) & 0o170000 != 0o120000, "unsafe member")
            target = directory / path
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                require(bundle.read(entry) == target.read_bytes(), "existing extracted output mismatch")
            else:
                target.write_bytes(bundle.read(entry))
    receipt = json.loads((directory / "receipt.json").read_text())
    require(receipt["commit"] == HEAD and receipt["status"] == "passed", "failed or foreign qualification")
    require(receipt["platform"].startswith("Windows-" if WINDOWS else "Linux-") and receipt["machine"] == ("AMD64" if WINDOWS else "x86_64") and receipt["config"] == ("ci-windows" if WINDOWS else "ci-linux"), "native host")
    inputs = json.loads((directory / "source-inputs.json").read_text())
    require(len(inputs) == 132 and receipt["source_after"] == inputs and receipt["source_inputs_unchanged"], "complete final source snapshot")
    for path, digest in inputs.items():
        require(sha(git("show", HEAD + ":" + path)) == digest, "immutable input mismatch: " + path)
    for name, expected in receipt["outputs"].items():
        data = (directory / name).read_bytes()
        require(len(data) == expected["bytes"] and sha(data) == expected["sha256"], "output identity: " + name)
    steps = receipt["steps"]
    if not WINDOWS:
        require(steps[0]["name"] == "committed-lock-check" and steps[0]["exit"] == 0 and steps[0]["command"] == [receipt["bash_executable"], "./scripts/check-module-bazel-lock.sh"], "original committed lock check first")
        steps = steps[1:]
    expected_steps = ["fresh-parallel-first-use", "original-consumer-tests", "original-clippy-selector", "original-consumer-clippy"]
    require([r["name"] for r in steps] == expected_steps and all(r["exit"] == 0 for r in steps), "original command sequence")
    targets = [f"//codex-rs/{name}:{name}-unit-tests" for name in ["v8-poc", "code-mode-runtime", "code-mode-host"]]
    for step in steps:
        command = step["command"]
        require(command[0] == receipt["bash_executable"] and (command[0].endswith("\\Git\\usr\\bin\\bash.exe") if WINDOWS else command[0] == "/usr/bin/bash"), "wrong shell")
        if step["name"] != "original-clippy-selector":
            require(command[1] == "./.github/scripts/run-bazel-ci.sh", "original wrapper changed")
            require("--remote-download-toplevel" in command and (("--windows-msvc-host-platform" in command and "--platforms=//:windows_x86_64_msvc" in command) if WINDOWS else not any("windows" in x for x in command)), "original native platform and output configuration")
        if step["name"] in expected_steps[:2]:
            require("--nocache_test_results" in command and "--test_output=all" in command, "cached or hidden tests")
    fresh = steps[0]["command"]
    regression = "tests::parallel_first_isolates_keep_array_buffers_independent"
    require(f"--test_arg={regression}" in fresh and "--test_arg=--exact" in fresh and fresh[-1] == targets[0], "fresh regression selector")
    require(steps[1]["command"][-3:] == targets, "full original target set")
    require(not any(a.startswith("--test_arg=") for a in steps[1]["command"]), "full consumer tests filtered")
    require(steps[3]["command"][-3:] == [target + "-bin" for target in targets], "Clippy binary set")
    selector = (directory / "original-clippy-selector.stdout").read_text().splitlines()
    require("-//codex-rs/v8-poc:all" in selector and all(target + "-bin" in selector for target in targets[1:]), "original Clippy selector contract")
    counts = {"fresh-parallel-first-use": (1, 6), "v8-poc": (7, 0), "code-mode-runtime": (68, 0), "code-mode-host": (40, 0)}
    for name, (passed, filtered) in counts.items():
        log = (directory / (name + ".log")).read_text()
        actual = re.findall(r"test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out", log)
        require(actual == [(str(passed), "0", "0", "0", str(filtered))], "underlying Rust test counts: " + name)
        require(len(re.findall(r"^test \S+ \.\.\. ok$", log, re.M)) == passed, "individual completed test records: " + name)
        doc = ET.fromstring((directory / (name + ".xml")).read_bytes())
        suites = list(doc.iter("testsuite"))
        require(suites and all(int(s.get("failures", "0")) == 0 and int(s.get("errors", "0")) == 0 for s in suites), "Bazel test XML failure")
    require(f"test {regression} ... ok" in (directory / "fresh-parallel-first-use.log").read_text(), "fresh regression not executed")
    require("test tests::sandbox_feature_matches_linked_v8 ... ok" in (directory / "v8-poc.log").read_text(), "original PoC sandbox assertion")
    require("linked_v8_has_sandbox_enabled ... ok" in (directory / "code-mode-runtime.log").read_text(), "original runtime sandbox assertion")
    require(not git("diff", "84424d4a35153aa5ab5b1cc778e2e80be6d411e4", HEAD, "--", "codex-rs/v8-poc", "codex-rs/code-mode-runtime", "codex-rs/code-mode-host"), "launcher successor changed consumer source")
    report = {"schema": "v8-083-native-hosted-independent-verification-v1", "source_commit": HEAD,
              "source_tree": git("rev-parse", HEAD + "^{tree}").decode().strip(), "run": 41710309685,
              "job": 126176341972 if WINDOWS else 126176342211, "artifact_id": ARTIFACT, "artifact_bytes": len(raw), "artifact_sha256": sha(raw),
              "immutable_git_input_paths_verified": len(inputs), "output_hashes_verified": len(receipt["outputs"]),
              "native_host": receipt["platform"], "fresh_process_parallel_test": {"passed": 1, "filtered_other_poc_cases": 6},
              "complete_original_consumer_tests": {"v8-poc": 7, "code-mode-runtime": 68, "code-mode-host": 40},
              "complete_consumer_failed_ignored_measured_filtered": 0, "original_sandbox_assertions_passed": True,
              "three_complete_test_binaries_clippy_passed": True, "native_platform_wrapper_preserved": True, "committed_lock_first": not WINDOWS,
              "qualification_budget_minutes": 30, "status": "native_original_consumer_scope_passed",
              "limits": ["Both native consumer scopes are independently checked; full original blocking CI and V8 canary source-build matrix remain separate.",
                         "This is exact 083 source, not qualification on the combined 0b9 dependency graph.",
                         "The fresh regression intentionally selects one test; the following three complete targets have zero filtered cases.",
                         "No downloaded source or executable was run by this verifier."],
              "release_state": "Draft / HOLD_NO_GO / DENY_ALL"}
    (ROOT / (args.platform.upper() + "_VERIFIED.json")).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
