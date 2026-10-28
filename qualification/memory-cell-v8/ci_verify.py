"""Run bounded V8 verification before this stage's final fix and format.

Research metrics remain separate from infrastructure test success. Every
attempt retains its exact source, command exits and partial output artifacts.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time


ROOT = Path(__file__).resolve().parents[2]
PROJECT = Path(__file__).resolve().parent
PACKAGES = ["codex-hepta-" + name for name in (
    "neuron", "agent-protocol", "agentd", "context-compiler", "infer-worker-host", "plasticity")]


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def identity(path):
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def execute(command, log):
    began = time.monotonic()
    unittest_counts = []
    log.write("COMMAND " + json.dumps(command) + "\n")
    log.flush()
    with subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace") as process:
        for line in process.stdout:
            match = re.fullmatch(r"Ran (\d+) tests? in .+", line.strip())
            if match:
                unittest_counts.append(int(match.group(1)))
            log.write(line)
            log.flush()
            print(line, end="", flush=True)
        code = process.wait()
    log.write(f"EXIT {code}\n")
    log.flush()
    result = {"command": command, "exit_code": code, "wall_seconds": time.monotonic() - began}
    if "unittest" in command:
        result["observed_unittest_counts"] = unittest_counts
        result["test_discovery_nonempty"] = len(unittest_counts) == 1 and unittest_counts[0] > 0
    return result


def main():
    request = json.loads((PROJECT / "VERIFY_REQUEST.json").read_text())
    if request.get("schema") != "hepta.memory.v8.verification-request.v1" or request.get("tests_before_final_fix_and_format") is not True:
        raise ValueError("invalid V8 verification request")
    output = ROOT / "memory-v8-ci-output"
    output.mkdir(exist_ok=False)
    receipt = {"schema": "hepta.memory.v8.product-ci-receipt.v1", "source_commit": git("rev-parse", "HEAD"),
               "source_tree": git("rev-parse", "HEAD^{tree}"), "request": request,
               "initial_tracked_changes": git("status", "--porcelain", "--untracked-files=no"),
               "complete_workspace_test": False, "executions": [], "research_gates_implied_by_test_success": False}
    python = os.environ["MEMORY_CELL_TRAINING_PYTHON"]
    target = Path(os.environ["CARGO_TARGET_DIR"])
    if not target.is_absolute() or receipt["initial_tracked_changes"]:
        raise ValueError("clean source and absolute target directory required")
    os.environ["HEPTA_TEST_CODEX_EXECUTABLE"] = str(target / "debug/codex-app-server")
    for key, name in {
        "MEMORY_CELL_TRAINING_RECEIPT_PATH": "legacy-training.json",
        "MEMORY_CELL_LANGUAGE_RECEIPT_PATH": "legacy-language.json",
        "MEMORY_CELL_POPULATION_RECEIPT_PATH": "legacy-population.json",
        "MEMORY_CELL_NETWORK_PROCESS_RECEIPT_PATH": "network-process.json",
        "MEMORY_CELL_V8_NATIVE_RECEIPT_PATH": "candidate-native-held.json",
        "MEMORY_CELL_V8_BASELINE_RECEIPT_PATH": "baseline-native-held.json",
        "MEMORY_CELL_V8_LEARNING_RECEIPT_PATH": "prospective-learning.json",
    }.items():
        os.environ[key] = str(output / name)
    ordinary = ["just", "test", "--locked"]
    for package in PACKAGES:
        ordinary.extend(["-p", package])
    commands = [
        [python, "-I", "-B", "-m", "unittest", "discover", "-s", "qualification/memory-cell-v8/addressing", "-p", "*_tests.py"],
        [python, "-I", "-B", "-m", "unittest", "discover", "-s", "qualification/memory-cell-v8/learning", "-p", "*_tests.py"],
        ["cargo", "build", "--locked", "--manifest-path", "codex-rs/Cargo.toml", "-p", "codex-app-server", "--bin", "codex-app-server"],
        ordinary,
        ["just", "test", "--locked", "--lib", "-p", "codex-hepta-agentd", "--run-ignored", "only",
         "-E", "test(memory_cell_) & test(actual_)"],
    ]
    began = time.monotonic()
    with (output / "execution.log").open("w") as log:
        for command in commands:
            result = execute(command, log)
            receipt["executions"].append(result)
            if command[:2] == ["cargo", "build"] and result["exit_code"]:
                receipt["native_tests_skipped_reason"] = "required same-source App Server executable build failed"
                break
        report = output / "prospective-learning.json"
        if report.exists():
            receipt["executions"].append(execute([python, "-I", "-B", str(PROJECT / "learning/score.py"),
                                                  str(report), str(output / "prospective-score.json")], log))
    receipt["wall_seconds"] = time.monotonic() - began
    receipt["final_tracked_changes"] = git("status", "--porcelain", "--untracked-files=no")
    (output / "generated.patch").write_bytes(subprocess.check_output(["git", "diff", "--binary"], cwd=ROOT))
    receipt["files"] = {str(path.relative_to(output)): identity(path) for path in sorted(output.rglob("*")) if path.is_file()}
    expected = ["network-process.json", "candidate-native-held.json", "baseline-native-held.json",
                "prospective-learning.json", "prospective-score.json"]
    receipt["missing_required_receipts"] = [name for name in expected if not (output / name).is_file()]
    receipt["passed"] = (not receipt["final_tracked_changes"] and not receipt["missing_required_receipts"]
                         and all(item["exit_code"] == 0 and item.get("test_discovery_nonempty", True)
                                 for item in receipt["executions"]))
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
