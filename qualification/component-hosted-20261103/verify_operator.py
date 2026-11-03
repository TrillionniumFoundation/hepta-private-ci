#!/usr/bin/env python3
"""Independently verify the exact hosted Operator evidence without executing it."""

import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile


import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--artifacts", type=Path, required=True)
parser.add_argument("--repository", type=Path, required=True)
arguments = parser.parse_args()
ROOT = arguments.artifacts.resolve()
REPO = arguments.repository.resolve()
HEAD = "b049d994619da7fe59896bce0dfd7eb850024c01"
BASE = "1ef3216ffb86271d87e6aea049ce7ca7f2b76809"
TARGET = "//codex-rs/hepta-operator-acceptance:hepta-operator-acceptance-tests"
BINARY = TARGET + "-bin"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(*arguments):
    return subprocess.check_output(["git", *arguments], cwd=REPO)


def main():
    expected = json.loads((ROOT / "download-verification.json").read_text())
    summaries = []
    for downloaded in expected:
        aid = str(downloaded["artifact_id"])
        archive = ROOT / (aid + ".zip")
        data = archive.read_bytes()
        require(len(data) == downloaded["bytes"] and sha(data) == downloaded["sha256"], "archive integrity")
        directory = ROOT / aid
        with zipfile.ZipFile(archive) as z:
            require(z.testzip() is None, "ZIP CRC")
            for entry in z.infolist():
                p = Path(entry.filename)
                require(not p.is_absolute() and ".." not in p.parts, "unsafe ZIP path")
                require((entry.external_attr >> 16) & 0o170000 != 0o120000, "ZIP symlink")
                if not entry.is_dir():
                    require(z.read(entry) == (directory / p).read_bytes(), "extracted member drift")
        receipt = json.loads((directory / "receipt.json").read_text())
        require(receipt["commit"] == HEAD and receipt["status"] == "passed", "wrong source or failed qualification")
        require(len(receipt["steps"]) == 4 and all(row["exit"] == 0 for row in receipt["steps"]), "original commands failed")
        require(receipt["ssh_keygen"]["path"] == "/usr/bin/ssh-keygen", "wrong host OpenSSH tool")
        for name, value in receipt["outputs"].items():
            content = (directory / name).read_bytes()
            require(len(content) == value["bytes"] and sha(content) == value["sha256"], "output integrity: " + name)
        inputs = json.loads((directory / "source-inputs.json").read_text())
        for name, digest in inputs.items():
            require(sha(git("show", HEAD + ":" + name)) == digest, "immutable Git input mismatch: " + name)
        native = next(row for row in receipt["steps"] if row["name"] == "original-native-tests")
        require(native["command"][-1] == TARGET and "--nocache_test_results" in native["command"], "native test changed or cached")
        require(BINARY in (directory / "original-clippy-targets.stdout").read_text().splitlines(), "original Clippy selector omitted binary")
        log = (directory / "test.log").read_text()
        counts = re.findall(r"test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out", log)
        require(counts == [("24", "0", "0", "0", "0")], "original 24 tests were not all executed")
        require(len(re.findall(r"^test \S+ \.\.\. ok$", log, re.M)) == 24, "individual test completion count")
        xml = ET.fromstring((directory / "test.xml").read_bytes())
        suites = xml.findall("testsuite")
        require(len(suites) == 1 and suites[0].get("tests") == "1" and suites[0].get("failures") == "0" and suites[0].get("errors") == "0", "Bazel wrapper test XML")
        require("24 passed; 0 failed; 0 ignored" in (suites[0].findtext("system-out") or ""), "XML lacks underlying Rust results")
        graph = json.loads(gzip.decompress((directory / "action-graph.stdout.gz").read_bytes()))
        labels = {row["id"]: row["label"] for row in graph["targets"]}
        owned = [a for a in graph["actions"] if labels.get(a.get("targetId"), "").startswith("//codex-rs/hepta-operator-acceptance:")]
        compiled = [a for a in owned if labels[a["targetId"]] == BINARY and a["mnemonic"] in {"Rustc", "Clippy"}]
        require({a["mnemonic"] for a in compiled} == {"Rustc", "Clippy"}, "missing original Rustc/Clippy actions")
        require(all(a["executionPlatform"].endswith("rbe_platform//:rbe_platform") for a in compiled), "compiler selected wrong execution platform")
        require(all("no-remote-exec" not in {item["key"] for item in a.get("executionInfo", [])} for a in owned if a["mnemonic"] in {"Rustc", "Clippy"}), "local runtime tag contaminated compiler")
        host = [a for a in owned if labels[a["targetId"]] == TARGET and a["mnemonic"] == "TestRunner"]
        require(len(host) == 1, "original wrapper action missing or duplicated")
        expected_platform = "@@platforms//host:host" if receipt["config"] == "ci-macos" else "@@+rbe_platform_repository+rbe_platform//:rbe_platform"
        require(host[0]["executionPlatform"] == expected_platform, "unexpected selected test execution platform")
        require({"no-remote-exec", "no-remote-cache"}.issubset({item["key"] for item in host[0].get("executionInfo", [])}), "test lost fresh local requirements")
        native_stderr = (directory / "original-native-tests.stderr").read_text()
        sandbox = "darwin-sandbox" if receipt["config"] == "ci-macos" else "linux-sandbox"
        require(re.search(r"\b[1-9]\d* " + sandbox, native_stderr) is not None, "native invocation lacks actual local sandbox executions")
        secret_hits = []
        patterns = [rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", rb"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})", rb"x-buildbuddy-api-key[=:][ \t]*[A-Za-z0-9_-]{12,}", rb"Authorization:[ \t]*Bearer[ \t]+[A-Za-z0-9._-]{20,}"]
        for p in directory.iterdir():
            content = p.read_bytes()
            if p.suffix == ".gz":
                content = gzip.decompress(content)
            if any(re.search(pattern, content) for pattern in patterns):
                secret_hits.append(p.name)
        require(not secret_hits, "potential credential found; names withheld from public evidence until reviewed")
        summaries.append({"artifact_id": int(aid), "archive_sha256": sha(data), "source_inputs_git_byte_verified": len(inputs), "outputs_hash_verified": len(receipt["outputs"]), "platform": receipt["platform"], "machine": receipt["machine"], "test_counts": [24, 0, 0, 0, 0], "original_clippy_selector_includes_complete_binary": True, "compiler_and_clippy_use_original_rbe": True, "test_is_fresh_local_host_execution": True, "test_selected_execution_platform": expected_platform, "actual_native_sandbox": sandbox, "credential_pattern_hits": 0})
    unchanged = git("diff", "--name-only", BASE, HEAD, "--", "codex-rs/hepta-operator-acceptance/src").decode().strip()
    require(not unchanged, "production Rust/tests changed")
    result = {"schema": "operator-hosted-independent-verification-v1", "source_commit": HEAD, "source_tree": git("rev-parse", HEAD + "^{tree}").decode().strip(), "original_run": 41690661437, "original_source_and_test_bodies_unchanged": True, "artifacts": summaries, "status": "passed", "limits": "Component execution repair only; does not qualify the later combined dependency graph or the complete original blocking CI."}
    (ROOT / "root-independent-verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
