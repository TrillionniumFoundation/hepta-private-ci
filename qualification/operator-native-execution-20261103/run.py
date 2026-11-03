#!/usr/bin/env python3
"""Record the original compiler, Clippy and host-test execution on real runners."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import time


REPO = Path(__file__).resolve().parents[2]
TARGET = "//codex-rs/hepta-operator-acceptance:hepta-operator-acceptance-tests"
BINARY = TARGET + "-bin"


def snapshot():
    paths = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "codex-rs/hepta-operator-acceptance",
         "codex-rs/Cargo.toml", "codex-rs/Cargo.lock", "MODULE.bazel", "MODULE.bazel.lock",
         "defs.bzl", "workspace_root_test_launcher.*", ".bazelrc", ".bazelversion",
         ".github/actions/setup-ci", ".github/actions/setup-bazel-ci",
         ".github/actions/prepare-bazel-ci", ".github/scripts/run_bazel_with_buildbuddy.py",
         "bazel/rules/testing", "scripts/list-bazel-clippy-targets.sh",
         "qualification/operator-native-execution-20261103",
         ".github/workflows/hepta-operator-native-execution.yml"], cwd=REPO,
    ).decode().split("\0")
    return {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest() for name in paths if name}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", choices=["ci-macos", "ci-linux"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    before = snapshot()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    (output / "source-inputs.json").write_text(json.dumps(before, indent=2) + "\n")
    receipt = {"commit": commit, "status": "failed", "platform": platform.platform(),
               "machine": platform.machine(), "config": args.config, "steps": []}
    wrapper = "./.github/scripts/run_bazel_with_buildbuddy.py"
    config = f"--config={args.config}"
    commands = [
        ("original-clippy-targets", ["./scripts/list-bazel-clippy-targets.sh"]),
        ("original-clippy", [wrapper, "build", config, "--config=clippy", BINARY]),
        ("original-native-tests", [wrapper, "test", config, "--nocache_test_results", "--test_output=all", TARGET]),
        ("action-graph", [wrapper, "aquery", config, "--config=clippy", f'deps({TARGET}) union deps({BINARY})', "--output=jsonproto"]),
    ]
    try:
        # A keyless local fallback cannot reproduce the execution-platform defect.
        if not os.environ.get("BUILDBUDDY_API_KEY"):
            raise RuntimeError("qualification requires the original authenticated RBE configuration")
        ssh_keygen = Path("/usr/bin/ssh-keygen")
        if not ssh_keygen.is_file() or not os.access(ssh_keygen, os.X_OK):
            raise RuntimeError("the original host ssh-keygen is unavailable")
        receipt["ssh_keygen"] = {"path": str(ssh_keygen), "sha256": hashlib.sha256(ssh_keygen.read_bytes()).hexdigest()}
        for name, command in commands:
            started = time.monotonic()
            with (output / f"{name}.stdout").open("wb") as stdout, (output / f"{name}.stderr").open("wb") as stderr:
                result = subprocess.run(command, cwd=REPO, stdout=stdout, stderr=stderr)
            receipt["steps"].append({"name": name, "command": command, "exit": result.returncode,
                                     "elapsed_seconds": time.monotonic() - started})
            if result.returncode:
                raise RuntimeError(f"{name} exited {result.returncode}")
            if name == "original-clippy-targets" and BINARY not in (output / f"{name}.stdout").read_text().splitlines():
                raise RuntimeError("the original Clippy target selector lost the complete Rust test")
        testlogs = REPO / "bazel-testlogs/codex-rs/hepta-operator-acceptance/hepta-operator-acceptance-tests"
        for filename in ["test.log", "test.xml"]:
            shutil.copyfile(testlogs / filename, output / filename)
        summaries = re.findall(r"test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out", (output / "test.log").read_text())
        if not summaries or any(int(row[0]) == 0 or any(int(n) for n in row[1:]) for row in summaries):
            raise RuntimeError("original Rust tests did not all pass without exclusions")
        receipt["test_summaries"] = summaries
        graph = json.loads((output / "action-graph.stdout").read_text())
        target_ids = {row["id"]: row["label"] for row in graph["targets"]}
        actions = [row for row in graph["actions"] if target_ids.get(row.get("targetId"), "").startswith("//codex-rs/hepta-operator-acceptance:")]
        receipt["operator_actions"] = [{"target": target_ids.get(row.get("targetId")), "mnemonic": row["mnemonic"],
                                        "executionInfo": row.get("executionInfo", []), "executionPlatform": row.get("executionPlatform")}
                                       for row in actions]
        compilers = [row for row in actions if row["mnemonic"] in {"Rustc", "Clippy"}]
        test_compilers = [row for row in compilers if target_ids.get(row.get("targetId")) == BINARY]
        if not {"Rustc", "Clippy"}.issubset({row["mnemonic"] for row in test_compilers}):
            raise RuntimeError("the complete original Rust test lacks a compiler or Clippy action")
        if any(item.get("key") == "no-remote-exec" for row in compilers for item in row.get("executionInfo", [])):
            raise RuntimeError("local-only runtime requirement leaked into compiler actions")
        tests = [row for row in actions if row["mnemonic"] == "TestRunner" and target_ids.get(row.get("targetId")) == TARGET]
        if len(tests) != 1 or not {"no-remote-exec", "no-remote-cache"}.issubset({item["key"] for item in tests[0].get("executionInfo", [])}):
            raise RuntimeError("fresh local execution requirements were not retained")
        if snapshot() != before:
            raise RuntimeError("qualification changed a source input")
        receipt["status"] = "passed"
    finally:
        graph_path = output / "action-graph.stdout"
        if graph_path.exists():
            (output / "action-graph.stdout.gz").write_bytes(gzip.compress(graph_path.read_bytes(), mtime=0))
            graph_path.unlink()
        receipt["outputs"] = {p.name: {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                              for p in sorted(output.iterdir()) if p.is_file() and p.name != "receipt.json"}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
