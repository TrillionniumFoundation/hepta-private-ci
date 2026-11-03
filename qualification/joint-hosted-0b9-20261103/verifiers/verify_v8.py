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

ROOT = Path(__file__).resolve().parent / "hosted-bede"
REPO = ROOT.parent.parent / "private-ci-v8-allocator-work-20261103"
HEAD = "bede07d3050d897a505020215a46a3ec8d66020d"
ARTIFACT = 13265608921
EXPECTED_SHA = "b72a6f758d6c3812fe71224c70558782e56d022871357637a009944343db3a8c"

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def git(*args):
    return subprocess.check_output(["git", *args], cwd=REPO)

def main():
    global ROOT, REPO
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args()
    ROOT, REPO = args.artifacts, args.repo
    archive = ROOT / (str(ARTIFACT) + ".zip")
    directory = ROOT / str(ARTIFACT)
    raw = archive.read_bytes()
    require(len(raw) == 29680 and sha(raw) == EXPECTED_SHA, "GitHub artifact identity")
    with zipfile.ZipFile(archive) as bundle:
        require(bundle.testzip() is None, "archive CRC")
        for entry in bundle.infolist():
            path = Path(entry.filename)
            require(not path.is_absolute() and ".." not in path.parts and (entry.external_attr >> 16) & 0o170000 != 0o120000, "unsafe member")
            require(bundle.read(entry) == (directory / path).read_bytes(), "extracted output mismatch")
    receipt = json.loads((directory / "receipt.json").read_text())
    require(receipt["commit"] == HEAD and receipt["status"] == "passed", "failed or foreign qualification")
    require(receipt["platform"].startswith("Windows-") and receipt["machine"] == "AMD64" and receipt["config"] == "ci-windows", "native Windows host")
    inputs = json.loads((directory / "source-inputs.json").read_text())
    for path, digest in inputs.items():
        require(sha(git("show", HEAD + ":" + path)) == digest, "immutable input mismatch: " + path)
    for name, expected in receipt["outputs"].items():
        data = (directory / name).read_bytes()
        require(len(data) == expected["bytes"] and sha(data) == expected["sha256"], "output identity: " + name)
    expected_steps = ["fresh-parallel-first-use", "original-consumer-tests", "original-clippy-selector", "original-consumer-clippy"]
    require([r["name"] for r in receipt["steps"]] == expected_steps and all(r["exit"] == 0 for r in receipt["steps"]), "original command sequence")
    targets = [f"//codex-rs/{name}:{name}-unit-tests" for name in ["v8-poc", "code-mode-runtime", "code-mode-host"]]
    for step in receipt["steps"]:
        command = step["command"]
        require(command[0] == receipt["bash_executable"] and command[0].endswith("\\Git\\usr\\bin\\bash.exe"), "wrong shell")
        if step["name"] != "original-clippy-selector":
            require(command[1] == "./.github/scripts/run-bazel-ci.sh", "original wrapper changed")
            require("--windows-msvc-host-platform" in command and "--platforms=//:windows_x86_64_msvc" in command and "--remote-download-toplevel" in command, "original native MSVC configuration")
        if step["name"] in expected_steps[:2]:
            require("--nocache_test_results" in command and "--test_output=all" in command, "cached or hidden tests")
    fresh = receipt["steps"][0]["command"]
    regression = "tests::parallel_first_isolates_keep_array_buffers_independent"
    require(f"--test_arg={regression}" in fresh and "--test_arg=--exact" in fresh and fresh[-1] == targets[0], "fresh regression selector")
    require(receipt["steps"][1]["command"][-3:] == targets, "full original target set")
    require(not any(a.startswith("--test_arg=") for a in receipt["steps"][1]["command"]), "full consumer tests filtered")
    require(receipt["steps"][3]["command"][-3:] == [target + "-bin" for target in targets], "Clippy binary set")
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
    report = {"schema": "v8-windows-hosted-independent-verification-v1", "source_commit": HEAD,
              "source_tree": git("rev-parse", HEAD + "^{tree}").decode().strip(), "run": 41705384578,
              "job": 126159900594, "artifact_id": ARTIFACT, "artifact_bytes": len(raw), "artifact_sha256": sha(raw),
              "immutable_git_input_paths_verified": len(inputs), "output_hashes_verified": len(receipt["outputs"]),
              "native_host": receipt["platform"], "fresh_process_parallel_test": {"passed": 1, "filtered_other_poc_cases": 6},
              "complete_original_consumer_tests": {"v8-poc": 7, "code-mode-runtime": 68, "code-mode-host": 40},
              "complete_consumer_failed_ignored_measured_filtered": 0, "original_sandbox_assertions_passed": True,
              "three_complete_test_binaries_clippy_passed": True, "native_msvc_wrapper_preserved": True,
              "qualification_budget_minutes": 30, "status": "windows_original_consumer_failure_scope_passed",
              "limits": ["Linux qualification pending; full original blocking CI and V8 canary source-build matrix remain separate.",
                         "This is the exact bede source, not qualification of the later joint 0b9 dependency graph.",
                         "The fresh regression intentionally selects one test; the following three complete targets have zero filtered cases.",
                         "No downloaded source or executable was run by this verifier."],
              "release_state": "Draft / HOLD_NO_GO / DENY_ALL"}
    (ROOT / "WINDOWS_VERIFIED.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
