"""Run V9 verification, preserving original bytes and failed attempts."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
PROJECT = Path(__file__).resolve().parent
PACKAGES = ["codex-hepta-" + name for name in (
    "cognitive-types", "neuron", "memory", "cognitive-store", "learning-artifacts",
    "agent-protocol", "agentd", "context-compiler", "infer-worker-host", "plasticity")]


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def identity(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def execute(command, output, executions, log):
    number = len(executions) + 1
    raw_path = output / "commands" / f"{number:02}.log"
    raw_path.parent.mkdir(exist_ok=True)
    entry = {"command": command, "exit_code": None, "raw_output_path": str(raw_path.relative_to(output))}
    executions.append(entry)
    counts, started = [], time.monotonic()
    log.write(("COMMAND " + json.dumps(command) + "\n").encode())
    log.flush()
    try:
        with raw_path.open("xb") as raw_log, subprocess.Popen(
                command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
            for data in iter(process.stdout.readline, b""):
                raw_log.write(data)
                log.write(data)
                log.flush()
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
                match = re.fullmatch(rb"Ran (\d+) tests? in .+", data.strip())
                if match:
                    counts.append(int(match.group(1)))
            entry["exit_code"] = process.wait()
    except OSError as error:
        entry["spawn_or_io_error"] = f"{type(error).__name__}: {error}"
    finally:
        entry["wall_seconds"] = time.monotonic() - started
        if raw_path.exists():
            entry["raw_output"] = identity(raw_path)
        if "unittest" in command:
            entry.update(observed_unittest_counts=counts, test_discovery_nonempty=len(counts) == 1 and counts[0] > 0)
        log.write(("\nEXIT " + json.dumps(entry["exit_code"]) + "\n").encode())
        log.flush()
    return entry["exit_code"] == 0 and entry.get("test_discovery_nonempty", True)


def main():
    request = json.loads((PROJECT / "VERIFY_REQUEST.json").read_bytes())
    if (request.get("schema") != "hepta.memory.v9.verification-request.v1"
            or request.get("mode") not in ("development", "formal")
            or request.get("tests_before_final_fix_and_format") is not True):
        raise ValueError("invalid V9 verification request")
    output = ROOT / "memory-v9-ci-output"
    output.mkdir(exist_ok=False)
    receipt = {"schema": "hepta.memory.v9.product-ci-receipt.v1", "source_commit": git("rev-parse", "HEAD"),
               "source_tree": git("rev-parse", "HEAD^{tree}"), "request": request,
               "initial_tracked_changes": git("status", "--porcelain", "--untracked-files=no"),
               "complete_workspace_test": False, "executions": [], "research_gates_implied_by_test_success": False,
               "passed": False, "tests_before_final_fix_and_format": True}
    python = os.environ["MEMORY_CELL_TRAINING_PYTHON"]
    target = Path(os.environ["CARGO_TARGET_DIR"])
    if not target.is_absolute() or receipt["initial_tracked_changes"]:
        raise ValueError("clean source and absolute target directory required")
    os.environ["HEPTA_TEST_CODEX_EXECUTABLE"] = str(target / "debug/codex-app-server")
    exports = {
        "MEMORY_CELL_NETWORK_PROCESS_RECEIPT_PATH": "legacy-network-process.json",
        "MEMORY_CELL_V9_BASELINE_V7_RECEIPT_PATH": "baseline-v7-native-held.json",
        "MEMORY_CELL_V9_BASELINE_V8_RECEIPT_PATH": "baseline-v8-native-held.json",
        "MEMORY_CELL_V9_CANDIDATE_RECEIPT_PATH": "candidate-v9-native-held.json",
        "MEMORY_CELL_V9_CONTINUAL_RECEIPT_PATH": "continual-learning.json",
        "MEMORY_CELL_V9_STRUCTURE_RECEIPT_PATH": "structure-learning.json",
        "MEMORY_CELL_V9_MIGRATION_RECEIPT_PATH": "migration-process.json",
    }
    os.environ.update({key: str(output / name) for key, name in exports.items()})
    ordinary = ["just", "test", "--locked"]
    for package in PACKAGES:
        ordinary.extend(["-p", package])
    commands = [
        [python, "-I", "-B", "-m", "unittest", "discover", "-s", str(PROJECT / "addressing"), "-p", "*_tests.py"],
        [python, "-I", "-B", "-m", "unittest", "discover", "-s", str(PROJECT / "learning"), "-p", "*_tests.py"],
        [python, "-I", "-B", str(PROJECT / "learning/fresh_reader.py"), "qualify", "--demo",
         "--output", str(output / "fresh-reader")],
        ["cargo", "build", "--locked", "--manifest-path", "codex-rs/Cargo.toml", "-p", "codex-app-server", "--bin", "codex-app-server"],
        ordinary,
    ]
    if request["mode"] == "formal":
        commands.append(["just", "test", "--locked", "--lib", "-p", "codex-hepta-agentd", "--run-ignored", "only",
                         "-E", "test(memory_cell_) & test(actual_) & test(v9)"])
    started = time.monotonic()
    with (output / "execution.log").open("xb") as log:
        for command in commands:
            succeeded = execute(command, output, receipt["executions"], log)
            if command[:2] == ["cargo", "build"] and not succeeded:
                receipt["native_tests_skipped_reason"] = "required same-source App Server build failed"
                break
        if request["mode"] == "formal":
            if all((output / name).is_file() for name in (
                    "baseline-v7-native-held.json", "baseline-v8-native-held.json", "candidate-v9-native-held.json")):
                execute([python, "-I", "-B", str(PROJECT / "evaluation/native_evidence.py"),
                         "--reports", str(output), "--output", str(output / "native-language-audit.json")],
                        output, receipt["executions"], log)
            for stem in ("continual-learning", "structure-learning"):
                report = output / f"{stem}.json"
                if report.exists():
                    execute([python, "-I", "-B", str(PROJECT / "learning/score.py"),
                             str(report), str(output / f"{stem}-score.json")], output, receipt["executions"], log)
    receipt["wall_seconds"] = time.monotonic() - started
    receipt["final_tracked_changes"] = git("status", "--porcelain", "--untracked-files=no")
    (output / "generated.patch").write_bytes(subprocess.check_output(["git", "diff", "--binary"], cwd=ROOT))
    receipt["files"] = {str(path.relative_to(output)): identity(path) for path in sorted(output.rglob("*")) if path.is_file()}
    required = ["legacy-network-process.json", "fresh-reader/receipt.json"]
    if request["mode"] == "formal":
        required.extend(name for name in exports.values() if name != "legacy-network-process.json")
        required.extend(("native-language-audit.json", "continual-learning-score.json", "structure-learning-score.json"))
    receipt["missing_required_receipts"] = [name for name in required if not (output / name).is_file()]
    receipt["passed"] = (not receipt["final_tracked_changes"] and not receipt["missing_required_receipts"]
                         and len(receipt["executions"]) >= len(commands)
                         and all(item["exit_code"] == 0 and item.get("test_discovery_nonempty", True)
                                 for item in receipt["executions"]))
    with (output / "receipt.json").open("x") as handle:
        handle.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print("MEMORY_V9_VERIFICATION_RECEIPT:" + json.dumps(receipt, sort_keys=True))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
