#!/usr/bin/env python3
"""Read retained Core/Supervisor qualification bytes; execute no archived source."""
import argparse
import json
import re
from pathlib import Path
import xml.etree.ElementTree as ET

from verify import GitBytes, fetch_artifact, require, sha
from verify_memory_current import parse

CORE = {
    "environment_selection::tests::blocking_snapshot_waits_for_starting_environment",
    "tools::handlers::multi_agents::tests::multi_agent_v2_wait_agent_uses_configured_default_timeout",
}
RESTART = {"restart_budget_survives_repeated_supervisord_recovery"}
SCOPES = (
    ("core-original-two", "codex-core", "lib", ["--lib"], CORE, False),
    ("supervisor-restart-original", "codex-hepta-supervisor", "test",
     ["--test", "restart_budget_recovery"], RESTART, True),
)
BAD = {"failure", "error", "skipped", "rerunFailure", "rerunError", "flakyFailure", "flakyError"}
FORMAT_BASE = "fcedede3f945bc75cec6dc7730c7cf0ef9056eda"


def compiled_inventory(raw, package, kind, required, complete):
    value = parse(raw)
    suites = value["rust-suites"]
    require(len(suites) == 1, "more than one compiled binary")
    suite_id, suite = next(iter(suites.items()))
    require(suite["package-name"] == package and suite["kind"] == kind
            and suite["status"] == "listed", "wrong compiled binary identity")
    require(isinstance(suite["binary-path"], str) and suite["binary-path"], "empty compiled binary path")
    cases = suite["testcases"]
    require(cases and value["test-count"] == len(cases), "empty or inconsistent inventory")
    ignored = set()
    for name, case in cases.items():
        require(type(case["ignored"]) is bool and case.get("kind") in (None, "test"),
                "invalid compiled test kind")
        wanted = {"status": "mismatch", "reason": "ignored"} if case["ignored"] else {"status": "matches"}
        require(case["filter-match"] == wanted, "unexpected original compiled filter")
        if case["ignored"]:
            ignored.add(name)
    runnable = set(cases) - ignored
    require(required <= runnable, "required original case absent or ignored")
    if complete:
        require(runnable == required and not ignored, "complete Supervisor target universe changed")
    return {
        "suite": suite_id, "binary": suite["binary-path"], "all_cases": sorted(cases),
        "all_runnable_count": len(runnable), "expected": sorted(required),
        "qualification_filtered_cases": sorted(runnable - required),
        "original_ignored": sorted(ignored), "complete_target": complete,
    }


def checked_junit(raw, listed):
    root = ET.fromstring(raw)
    suites = list(root.iter("testsuite"))
    require(len(suites) == 1, "expected one JUnit binary suite")
    require(not any(element.tag in BAD for element in root.iter()), "failed/skipped/retried JUnit")
    cases = list(root.iter("testcase"))
    names = [case.get("name") for case in cases]
    require(len(names) == len(set(names)) and set(names) == set(listed["expected"]),
            "wrong or duplicate original executed cases")
    suite = suites[0]
    require(int(suite.get("tests", "-1")) == len(names)
            and all(int(suite.get(key, "0")) == 0 for key in ("failures", "errors", "skipped")),
            "JUnit counters disagree")
    return {"passed": len(names), "failed": 0, "errors": 0, "skipped": 0, "retried": 0,
            "executed": names, "original_ignored": listed["original_ignored"]}


def source_identity(receipt, members, git):
    before, after = parse(members["source-before.json"]), parse(members["source-after.json"])
    require(before and before == after and receipt["source_inputs_unchanged"] is True,
            "source snapshot changed or missing")
    require(set(before) == set(git.tree), "snapshot is not the complete original Git tree")
    for name, identity in before.items():
        mode, kind, oid = git.tree[name]
        require(kind == "blob" and mode in {"100644", "100755", "120000"}, "unsupported Git input")
        raw = git.read(name)
        require(identity == {"mode": mode, "expected_git_blob": oid, "git_blob": oid,
                             "bytes": len(raw), "sha256": sha(raw)}, "exact Git bytes differ: " + name)
    tree = git.command("rev-parse", "HEAD^{tree}").decode().strip()
    require(tree == receipt["source_tree"], "original Git tree identity differs")
    return {"count": len(before), "source_tree": tree, "all_match_exact_git_bytes": True,
            "before_sha256": sha(members["source-before.json"]),
            "after_sha256": sha(members["source-after.json"]),
            "snapshot_values_equal": True, "symlinks": "raw Git link payload; not dereferenced"}


def outputs_and_commands(receipt, members):
    outputs = receipt["outputs"]
    require(set(outputs) == set(members) - {"receipt.json"}, "unbound or missing original output")
    for name, identity in outputs.items():
        require(identity == {"bytes": len(members[name]), "sha256": sha(members[name])},
                "original output hash differs: " + name)
    commands = receipt["commands"]
    rows = {row["name"]: row for row in commands}
    require(len(rows) == len(commands), "duplicate original command")
    for name in rows:
        require(name + ".stdout" in members and name + ".stderr" in members, "missing original command streams")
    return rows, outputs


def inspect(receipt, members, rows, spec):
    expected = [
        ("source-commit", ["git", "--no-replace-objects", "rev-parse", "HEAD"]),
        ("source-tree", ["git", "--no-replace-objects", "rev-parse", "HEAD^{tree}"]),
        ("initial-clean-source", ["git", "--no-replace-objects", "diff", "--exit-code", "HEAD", "--"]),
        ("rustc-version", ["rustc", "-Vv"]),
        ("nextest-version", ["cargo", "nextest", "--version"]),
        ("original-formatter", ["just", "fmt", "--base", FORMAT_BASE]),
        ("source-clean-after-formatter", ["git", "--no-replace-objects", "diff", "--exit-code", "HEAD", "--"]),
    ]
    for name, package, kind, target, required, complete in SCOPES:
        common = ["--locked", "-p", package, *target]
        expected.append((name + "-inventory", ["cargo", "nextest", "list", *common, "--message-format=json"]))
        command = ["just", "test", *common, "--no-tests=fail", "--retries", "0", "--success-output=final"]
        if not complete:
            command += ["-E", " | ".join("test(=" + case + ")" for case in sorted(required))]
        expected.append((name + "-original-tests", command))
    expected += [
        ("original-scoped-clippy", ["just", "fix", "--locked", "-p", "codex-core",
                                   "-p", "codex-hepta-supervisor", "--no-deps"]),
        ("final-clean-source", ["git", "--no-replace-objects", "diff", "--exit-code", "HEAD", "--"]),
    ]
    require(list(rows) == [name for name, _ in expected], "original command order differs")
    for name, argv in expected:
        require(rows[name]["argv"] == argv and rows[name]["exit_code"] == 0,
                "original command failed or changed: " + name)
    require(members["source-commit.stdout"].decode().strip() == spec["source"]
            and members["source-tree.stdout"].decode().strip() == receipt["source_tree"],
            "original source commands differ")
    require(members["rustc-version.stdout"].startswith(b"rustc 1.96.0 ")
            and members["nextest-version.stdout"].startswith(b"cargo-nextest 0.9.151 "),
            "unexpected original compiler or nextest")
    require(not receipt["problems"] and set(receipt["scopes"]) == {s[0] for s in SCOPES},
            "unexpected original scope or problems")
    result = {}
    for name, package, kind, target, required, complete in SCOPES:
        item = receipt["scopes"][name]
        require(item["status"] == "passed", "original selected scope failed")
        listed = compiled_inventory(members[name + "-inventory.stdout"], package, kind, required, complete)
        require(listed == item["inventory"], "recorded inventory differs from compiled original")
        checked = checked_junit(members[name + "-junit.xml"], listed)
        require(checked == item["result"], "recorded JUnit result differs")
        logs = members[name + "-original-tests.stdout"] + members[name + "-original-tests.stderr"]
        require(b"skipping test:" not in logs.lower(), "original selected test reported early skip")
        binary_hash = item["binary_sha256_before"]
        require(re.fullmatch(r"[0-9a-f]{64}", binary_hash) is not None
                and item["binary_sha256_after"] == binary_hash, "original binary identity changed")
        result[name] = {
            "executed": checked["passed"], "executed_cases": checked["executed"],
            "compiled_inventory_count": len(listed["all_cases"]),
            "original_ignored": listed["original_ignored"],
            "qualification_filtered_count": len(listed["qualification_filtered_cases"]),
            "complete_target": complete, "junit_sha256": sha(members[name + "-junit.xml"]),
            "recorded_binary_sha256_before_and_after": binary_hash,
        }
    return {"mode": "original-focused-native", "executed": 3, "scopes": result,
            "command_exits": [0] * len(expected),
            "boundary": "Two selected original Core cases and one complete Supervisor restart target. Unselected Core cases did not execute. Binary equality is recorded by the original job; binaries are not retained here."}


def main():
    require(__debug__, "optimized Python is not accepted")
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    matches = [row for row in parse(args.manifest.read_bytes()) if row["key"] == args.key]
    require(len(matches) == 1, "ambiguous artifact manifest key")
    spec = matches[0]
    require(spec["kind"] == "core-supervisor-original", "wrong focused native evidence kind")
    args.output.mkdir(parents=True, exist_ok=False)
    metadata, archive, members = fetch_artifact(spec)
    (args.output / "original.zip").write_bytes(archive)
    receipt = parse(members["receipt.json"])
    require(receipt["source_commit"] == spec["source"]
            and receipt["run_id"] == str(spec["run_id"])
            and receipt["run_attempt"] == "1"
            and receipt["status"] == spec["expected_original_status"] == "passed",
            "wrong original source, run or verdict")
    require(receipt["host"].startswith({"windows": "Windows", "linux": "Linux"}[spec["host"]]),
            "wrong original native host")
    git = GitBytes(args.source, spec["source"])
    try:
        sources = source_identity(receipt, members, git)
        rows, outputs = outputs_and_commands(receipt, members)
        result = inspect(receipt, members, rows, spec)
    finally:
        git.close()
    report = {
        "schema": 1, "key": spec["key"], "repository": spec["repository"], "source": spec["source"],
        "original_run": spec["run_id"], "artifact_id": spec["artifact_id"],
        "zip_bytes": len(archive), "zip_sha256": sha(archive), "all_member_crc": True,
        "original_qualification_status": receipt["status"], "source_verification": sources,
        "output_verification": outputs, "result": result, "evidence_verification": "passed",
        "scope": "Read-only original evidence verification; no new native run or full Core/whole-CI acceptance.",
    }
    rendered = json.dumps(report, indent=2).encode() + b"\n"
    (args.output / "VERIFIED.json").write_bytes(rendered)
    (args.output / "receipt.json").write_bytes(members["receipt.json"])
    (args.output / "artifact-metadata.json").write_bytes(json.dumps(metadata, indent=2).encode() + b"\n")
    projection = {key: value for key, value in report.items() if key != "output_verification"}
    projection["output_count"] = len(outputs)
    projection["verified_report_sha256"] = sha(rendered)
    print("ORIGINAL_FOCUSED_EVIDENCE_VERIFIED_JSON=" + json.dumps(projection, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
