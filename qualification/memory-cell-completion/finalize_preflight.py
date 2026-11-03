"""Verify retained CI bytes before the unchanged V9 fix/format finalizer.

This checks evidence integrity and source identity. It does not run tests,
training, fix, format, commits or pushes, and does not authenticate a claimed
GitHub run: the workflow must separately bind the downloaded artifact to it.
"""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence_transport import canonical, file_pin, identity, load, pin, require, safe_name, verify_transport
from source_freeze import git, verify_after, verify_sources


ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ["codex-hepta-" + name for name in (
    "cognitive-types", "neuron", "memory", "cognitive-store", "learning-artifacts",
    "agent-protocol", "agentd", "context-compiler", "infer-worker-host", "plasticity")]
REQUIRED = (
    "legacy-network-process.json", "fresh-reader/receipt.json", "baseline-v7-native-held.json",
    "baseline-v8-native-held.json", "candidate-v9-native-held.json", "continual-learning.json",
    "structure-learning.json", "migration-process.json", "continual-learning-score.json",
    "structure-learning-score.json", "native-language-audit.json")


def verify_receipt(repo, request, manifest, receipt, transport):
    require(isinstance(request, dict) and request.get("schema") == "hepta.memory.v9.finalize-request.v1",
            "existing V9 FINALIZE_REQUEST is required")
    source = manifest["source"]
    require(request.get("tested_commit") == source["commit"], "finalize request names another tested commit")
    declared = request.get("verification_receipt")
    require(pin(declared, path=True, nonempty=True, maximum=8_000_000) == transport["receipt"],
            "finalize request receipt hash differs from retained transport")
    require(file_pin(repo / declared["path"]) == transport["receipt"],
            "finalize request does not address the verified receipt bytes")
    require(receipt.get("schema") == "hepta.memory.v9.product-ci-receipt.v1"
            and receipt.get("passed") is True and receipt.get("source_commit") == source["commit"]
            and receipt.get("source_tree") == source["tree"]
            and receipt.get("tests_before_final_fix_and_format") is True
            and receipt.get("initial_tracked_changes") == "" and receipt.get("final_tracked_changes") == ""
            and receipt.get("missing_required_receipts") == [], "CI receipt is incomplete, failed or bound to another source")
    from evidence_transport import decode
    tested_request = decode(git(repo, "show", f"{source['commit']}:qualification/memory-cell-v9/VERIFY_REQUEST.json"))
    require(receipt.get("request") == tested_request and tested_request.get("mode") == "formal"
            and tested_request.get("tests_before_final_fix_and_format") is True, "CI request differs from tested source")
    files = receipt["files"]
    for name in REQUIRED:
        require(name in files, "required raw report missing: " + name)
        pin(files[name], nonempty=True)
    require(files.get("generated.patch") == identity(b"") and "execution.log" in files,
            "clean-source patch or raw execution log missing")
    executions = receipt.get("executions")
    require(isinstance(executions, list) and executions, "missing command executions")
    log_paths, commands = set(), []
    for execution in executions:
        require(isinstance(execution, dict) and type(execution.get("exit_code")) is int
                and execution["exit_code"] == 0 and execution.get("test_discovery_nonempty", True) is True,
                "failed or incomplete CI execution")
        command, path = execution.get("command"), execution.get("raw_output_path")
        require(isinstance(command, list) and command and all(isinstance(item, str) for item in command),
                "invalid command identity")
        safe_name(path)
        require(path.startswith("commands/") and path not in log_paths and path in files
                and execution.get("raw_output") == files[path], "command log inventory mismatch")
        log_paths.add(path)
        commands.append(command)
    ordinary = ["just", "test", "--locked"]
    for package in PACKAGES:
        ordinary.extend(["-p", package])
    actual = ["just", "test", "--locked", "--lib", "-p", "codex-hepta-agentd", "--run-ignored", "only",
              "-E", "test(memory_cell_) & test(actual_) & test(v9)"]
    require(ordinary in commands and actual in commands, "both native test groups must have completed")
    return {"required_raw_reports": {name: files[name] for name in REQUIRED},
            "raw_command_logs_verified": len(log_paths), "raw_inventory_files_verified": len(files),
            "ci_receipt_excluded_itself_from_inventory": True, "research_quality_pass_asserted": False}


def preflight(repo, manifest_path, request_path, adapter_freezes):
    manifest, receipt, transport = verify_transport(manifest_path)
    request_raw, request = load(request_path, 65_536)
    native = verify_receipt(repo, request, manifest, receipt, transport)
    sources = verify_sources(repo, manifest["source"]["commit"], manifest["source"]["tree"], adapter_freezes)
    return {"schema": "hepta.memory.completion.preflight.v1", "passed": True,
            "source": manifest["source"], "request": identity(request_raw), "transport": transport,
            "native_evidence": native, "sources": sources, "github_run_authenticated_here": False,
            "adapter_native_integration_claimed": False, "tests_executed": False,
            "training_executed": False, "fix_or_format_executed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--transport", type=Path)
    mode.add_argument("--after", type=Path, help="check a successful preflight's adapter freeze after finalization")
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--request", type=Path, default=ROOT / "qualification/memory-cell-v9/FINALIZE_REQUEST.json")
    parser.add_argument("--adapter-freeze", action="append", default=[], help="retained longrun FREEZE, relative to repository")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {"schema": "hepta.memory.completion.preflight.v1", "passed": False,
              "tests_executed": False, "fix_or_format_executed": False}
    try:
        if args.after:
            raw, before = load(args.after)
            result = {"schema": "hepta.memory.completion.preflight-after.v1", "passed": True,
                      "before_identity": identity(raw), "source_freeze": verify_after(args.repo, before),
                      "tests_executed": False, "fix_or_format_executed": False}
        else:
            result = preflight(args.repo, args.transport, args.request, args.adapter_freeze)
    except Exception as error:
        result.update(passed=False, error=f"{type(error).__name__}: {error}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as handle:
        handle.write(canonical(result))
    print(canonical({"receipt": str(args.output), "passed": result["passed"]}).decode().strip())
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
