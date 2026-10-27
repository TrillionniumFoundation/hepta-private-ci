"""Retain exact-source verification receipts for actual product crates."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
REQUEST = Path(__file__).with_name("VERIFY_REQUEST.json")
GROUPS = {
    "typed-native": ["codex-hepta-cognitive-types", "codex-hepta-neuron"],
    "source-owner": ["codex-hepta-memory", "codex-hepta-cognitive-store"],
    "release-owner": ["codex-hepta-learning-artifacts"],
    "daemon": ["codex-hepta-agent-protocol", "codex-hepta-agentd"],
    "population": ["codex-hepta-neuron", "codex-hepta-plasticity"],
}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode().strip()


def identity(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def main():
    mode = sys.argv[1]
    request = json.loads(REQUEST.read_text())
    groups = request["groups"]
    if not groups or len(set(groups)) != len(groups) or set(groups) - GROUPS.keys():
        raise ValueError("invalid scoped test groups")
    if mode == "plan":
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write("groups=" + json.dumps(groups) + "\n")
        return 0
    group = os.environ.get("MEMORY_TEST_GROUP")
    if mode == "test":
        if group not in groups:
            raise ValueError("test group not requested")
        command = ["just", "test", "--locked", "--lib"]
        for package in GROUPS[group]:
            command.extend(["-p", package])
    elif mode == "lock":
        command = ["just", "bazel-lock-update"]
    else:
        raise ValueError("unknown verification mode")
    output = ROOT / "memory-v7-ci-output"
    output.mkdir(exist_ok=False)
    commands = [command]
    if mode == "test" and group == "daemon":
        commands.append(["just", "test", "--locked", "--lib", "-p", "codex-hepta-agentd",
                         "--run-ignored", "only", "-E", "test(memory_cell_) & test(actual_)"])
        os.environ["MEMORY_CELL_TRAINING_RECEIPT_PATH"] = str(output / "training-receipt.json")
        os.environ["MEMORY_CELL_LANGUAGE_RECEIPT_PATH"] = str(output / "language-receipt.json")
        os.environ["MEMORY_CELL_POPULATION_RECEIPT_PATH"] = str(output / "population-receipt.json")
    receipt = {
        "schema": "hepta.memory.v7.product-ci-receipt.v1",
        "source_commit": git("rev-parse", "HEAD"),
        "source_tree": git("rev-parse", "HEAD^{tree}"),
        "request": request,
        "mode": mode,
        "group": group,
        "command": command,
        "commands": commands,
        "initial_tracked_changes": git("status", "--porcelain", "--untracked-files=no"),
        "lock_before": identity(ROOT / "MODULE.bazel.lock"),
        "complete_workspace_test": False,
        "production_manifests_modified_for_test": False,
    }
    started = time.monotonic()
    executions = []
    with (output / "execution.log").open("w") as log:
        for command in commands:
            before = time.monotonic()
            process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in process.stdout:
                log.write(line)
                log.flush()
                print(line, end="", flush=True)
            executions.append({"command": command, "exit_code": process.wait(), "wall_seconds": time.monotonic() - before})
            if executions[-1]["exit_code"] != 0:
                break
        receipt["executions"] = executions
        receipt["exit_code"] = next((item["exit_code"] for item in executions if item["exit_code"] != 0), 0)
    receipt["wall_seconds"] = time.monotonic() - started
    receipt["lock_after"] = identity(ROOT / "MODULE.bazel.lock")
    receipt["final_tracked_changes"] = git("status", "--porcelain", "--untracked-files=no")
    patch = subprocess.check_output(["git", "diff", "--binary"], cwd=ROOT)
    (output / "generated.patch").write_bytes(patch)
    if mode == "lock":
        (output / "MODULE.bazel.lock").write_bytes((ROOT / "MODULE.bazel.lock").read_bytes())
    receipt["log"] = identity(output / "execution.log")
    receipt["passed"] = receipt["exit_code"] == 0 and not receipt["initial_tracked_changes"] and not receipt["final_tracked_changes"]
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
