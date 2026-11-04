#!/usr/bin/env python3
"""Verify retained original schema generation bytes without running archived code."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from verify import GitBytes, fetch_artifact, require, sha
from verify_memory_current import parse

SCHEMA_PREFIX = "codex-rs/app-server-protocol/schema/"
PACKAGE = "codex-app-server-protocol"
IGNORED = "schema_fixtures_tests::write_schema_fixtures_from_env"
REQUIRED = {
    "schema_fixtures_tests::typescript_schema_fixtures_match_generated",
    "schema_fixtures_tests::json_schema_fixtures_match_generated",
    "schema_fixtures_tests::stable_precomputed_exports_match_schema_fixtures",
    "schema_fixtures_tests::experimental_precomputed_exports_match_generated",
}
FORMAT_BASE = "fcedede3f945bc75cec6dc7730c7cf0ef9056eda"
BAD = {"failure", "error", "rerunFailure", "rerunError", "flakyFailure", "flakyError"}


def identity(raw):
    return {"bytes": len(raw), "sha256": sha(raw),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def complete_native(listing_raw, xml_raw):
    value = parse(listing_raw)
    suites = value["rust-suites"]
    require(len(suites) == 1, "expected exactly one compiled library")
    suite = next(iter(suites.values()))
    require(suite["package-name"] == PACKAGE and suite["kind"] == "lib"
            and suite["status"] == "listed", "wrong original compiled library")
    cases = suite["testcases"]
    require(cases and value["test-count"] == len(cases), "empty or inconsistent compiled inventory")
    ignored = set()
    for name, case in cases.items():
        require(isinstance(name, str) and name and type(case["ignored"]) is bool
                and case.get("kind") in (None, "test"), "invalid compiled case identity")
        expected = {"status": "mismatch", "reason": "ignored"} if case["ignored"] else {"status": "matches"}
        require(case["filter-match"] == expected, "original compiled case was filtered")
        if case["ignored"]:
            ignored.add(name)
    require(ignored == {IGNORED}, "original ignored generator changed")
    runnable = set(cases) - ignored
    require(REQUIRED <= runnable, "original schema comparison absent")
    root = ET.fromstring(xml_raw)
    require(root.tag == "testsuites", "missing original JUnit document")
    xml_suites = list(root.iter("testsuite"))
    require(len(xml_suites) == 1 and root.findall("testsuite") == xml_suites,
            "wrong JUnit library suite shape")
    xml_suite = xml_suites[0]
    testcases = list(root.iter("testcase"))
    require(testcases == xml_suite.findall("testcase"), "unexpected nested JUnit cases")
    require(not any(node.tag in BAD for node in root.iter()), "original native failure or retry")
    names = [case.get("name") for case in testcases]
    require(len(names) == len(set(names)), "duplicate JUnit case")
    skipped = {case.get("name") for case in testcases if case.find("skipped") is not None}
    passed = set(names) - skipped
    require(passed == runnable and skipped <= ignored,
            "JUnit does not cover the complete original runnable library")
    require(sum(1 for _ in root.iter("skipped")) == len(skipped), "invalid skipped node placement")
    for node in (root, xml_suite):
        if node is xml_suite or node.get("tests") is not None:
            require(int(node.get("tests", "-1")) == len(names), "JUnit tests counter differs")
        for key in ("failures", "errors"):
            require(int(node.get(key, "0")) == 0, "JUnit failure counter differs")
        if node is xml_suite or node.get("skipped") is not None:
            require(int(node.get("skipped", "0")) == len(skipped), "JUnit ignored counter differs")
    return {
        "runnable_cases": sorted(runnable), "passed": len(passed), "failed": 0, "errors": 0,
        "retries": 0, "original_ignored_cases": sorted(ignored),
        "junit_skipped_cases": sorted(skipped), "required_schema_cases": sorted(REQUIRED),
        "inventory": identity(listing_raw), "junit": identity(xml_raw),
    }


def expected_commands():
    return [
        ("source-commit", ["git", "rev-parse", "HEAD"]),
        ("source-tree", ["git", "rev-parse", "HEAD^{tree}"]),
        ("source-clean-before", ["git", "diff", "--exit-code", "HEAD", "--"]),
        ("rustc-version", ["rustc", "--version"]),
        ("nextest-version", ["cargo", "nextest", "--version"]),
        ("original-format", ["just", "fmt", "--base", FORMAT_BASE]),
        ("source-clean-after-format", ["git", "diff", "--exit-code", "HEAD", "--"]),
        ("original-stable-generator", ["just", "write-app-server-schema"]),
        ("original-experimental-generator", ["just", "write-app-server-schema", "--experimental"]),
        ("generated-source-diff", ["git", "diff", "--binary", "--no-ext-diff", "HEAD", "--", SCHEMA_PREFIX]),
        ("complete-original-library-inventory", ["cargo", "nextest", "list", "--locked", "-p",
                                               PACKAGE, "--lib", "--message-format", "json"]),
        ("complete-original-library", ["just", "test", "--locked", "-p", PACKAGE, "--lib", "--retries", "0"]),
        ("tracked-changed-paths", ["git", "diff", "--name-only", "HEAD", "--"]),
        ("untracked-changed-paths", ["git", "ls-files", "--others", "--exclude-standard"]),
    ]


def bound_outputs(receipt, members):
    outputs = receipt["outputs"]
    require(set(outputs) == set(members) - {"receipt.json"}, "missing or unbound artifact output")
    for name, recorded in outputs.items():
        require(recorded == identity(members[name]), "original output bytes differ: " + name)
    expected = expected_commands()
    steps = receipt["steps"]
    require(len(steps) == len(expected), "wrong original command count")
    for step, (name, command) in zip(steps, expected):
        require(step["name"] == name and step["command"] == command
                and type(step["exit"]) is int and step["exit"] == 0, "original command changed or failed: " + name)
        require(isinstance(step["elapsed_seconds"], (int, float))
                and math.isfinite(step["elapsed_seconds"]) and step["elapsed_seconds"] >= 0,
                "invalid command duration")
        require(name + ".stdout" in members and name + ".stderr" in members, "missing command streams")
    return outputs


def bound_sources(receipt, members, git, spec):
    before = parse(members["source-inputs-before.json"])
    after = parse(members["source-inputs-after.json"])
    require(before and before == after and receipt["non_schema_inputs_unchanged"] is True,
            "non-schema source changed")
    non_schema = {name for name in git.tree if not name.startswith(SCHEMA_PREFIX)}
    require(set(before) == non_schema, "non-schema snapshot is not the complete exact Git tree")
    for name, recorded in before.items():
        mode, kind, oid = git.tree[name]
        require(kind == "blob" and mode in {"100644", "100755", "120000"}, "unsupported Git input mode")
        raw = git.read(name)
        require(recorded == {"mode": mode, **identity(raw)} and recorded["git_blob"] == oid,
                "non-schema Git input differs: " + name)
    tree = git.command("rev-parse", "HEAD^{tree}").decode().strip()
    require(tree == receipt["tree"] == spec["source_tree"], "exact source tree differs")
    original = parse(members["original-schema.json"])
    schema_names = set(git.tree) - non_schema
    require(schema_names and set(original) == schema_names, "original schema inventory differs from Git")
    for name, recorded in original.items():
        mode, kind, oid = git.tree[name]
        require(kind == "blob" and mode in {"100644", "100755"}, "unsupported original schema input")
        require(recorded == identity(git.read(name)) and recorded["git_blob"] == oid,
                "original schema bytes differ: " + name)
    return original, {
        "non_schema_count": len(before), "original_schema_count": len(original),
        "total_git_inputs": len(git.tree), "source_tree": tree,
        "all_match_exact_git_bytes": True, "snapshot_values_equal": True,
        "source_before_sha256": sha(members["source-inputs-before.json"]),
        "source_after_sha256": sha(members["source-inputs-after.json"]),
        "symlinks": "Raw Git link payload; not dereferenced.",
    }


def bound_generation(receipt, members, original, spec):
    generated = parse(members["generated-schema.json"])
    deltas = parse(members["generated-deltas.json"])
    expected = spec["generated_deltas"]
    require(deltas == receipt["generated_deltas"] == expected, "exact generated delta set differs")
    require(set(generated) == set(original), "schema file added or removed unexpectedly")
    require(len({row["path"] for row in deltas}) == len(deltas) == 3, "wrong generated file count")
    changed = {name for name in generated if original[name] != generated[name]}
    require(changed == {row["path"] for row in deltas}, "unrecorded generated schema change")
    for row in deltas:
        name = row["path"]
        require(name.startswith(SCHEMA_PREFIX) and row["before"] == original[name]
                and row["after"] == generated[name], "generated inventory disagreement")
        require(identity(members["generated/" + name]) == row["after"], "retained generated bytes differ")
    expected_members = {
        "receipt.json", "source-inputs-before.json", "source-inputs-after.json",
        "original-schema.json", "generated-schema.json", "generated-deltas.json", "original-library.junit.xml",
        *("generated/" + name for name in changed),
        *(name + suffix for name, _ in expected_commands() for suffix in (".stdout", ".stderr")),
    }
    require(set(members) == expected_members, "original artifact member set differs")
    tracked = members["tracked-changed-paths.stdout"].decode().splitlines()
    require(len(tracked) == len(set(tracked)) and set(tracked) == changed, "final tracked changes differ")
    require(not members["untracked-changed-paths.stdout"].strip(), "unexpected original untracked changes")
    require(receipt["generation_completed"] is True
            and receipt["generated_bytes_unchanged_through_native"] is True,
            "generation did not finish with unchanged native inputs")
    return {"count": len(deltas), "deltas": deltas,
            "unchanged_schema_count": len(original) - len(deltas),
            "generated_bytes_unchanged_through_native": True}


def inspect(receipt, members, spec):
    require(members["source-commit.stdout"].decode().strip() == spec["source"]
            and members["source-tree.stdout"].decode().strip() == spec["source_tree"],
            "original source command output differs")
    rustc = members["rustc-version.stdout"].decode().strip()
    nextest = members["nextest-version.stdout"].decode().strip()
    require(rustc == receipt["rustc"] and rustc.startswith("rustc 1.96.0 ")
            and nextest == receipt["nextest"] and nextest.startswith("cargo-nextest 0.9.151 "),
            "original toolchain differs")
    for name in ("source-clean-before", "source-clean-after-format"):
        require(not members[name + ".stdout"].strip(), "original clean source has changes")
    native = complete_native(members["complete-original-library-inventory.stdout"],
                             members["original-library.junit.xml"])
    require(native == receipt["native"], "native receipt differs from compiled inventory and fresh JUnit")
    logs = members["complete-original-library.stdout"] + members["complete-original-library.stderr"]
    require(b"skipping test:" not in logs.lower(), "original library reported an early runtime skip")
    return {"compiled_inventory_count": native["passed"] + len(native["original_ignored_cases"]),
            "native": native, "command_exits": [0] * len(expected_commands()), "rustc": rustc,
            "nextest": nextest, "original_scope": "Complete original app-server-protocol library, including all four schema comparisons. One unchanged ignored fixture-writing helper."}


def main():
    require(__debug__, "optimized Python is not accepted")
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    entries = [row for row in parse(args.manifest.read_bytes()) if row["key"] == args.key]
    require(len(entries) == 1, "ambiguous artifact manifest key")
    spec = entries[0]
    require(spec["kind"] == "schema-original", "wrong original artifact kind")
    args.output.mkdir(parents=True, exist_ok=False)
    metadata, archive, members = fetch_artifact(spec)
    (args.output / "original.zip").write_bytes(archive)
    receipt = parse(members["receipt.json"])
    require(receipt["status"] == spec["expected_original_status"] == "passed"
            and receipt["commit"] == spec["source"] and receipt["tree"] == spec["source_tree"]
            and receipt["host"].startswith("Linux"), "wrong original source, host or result")
    outputs = bound_outputs(receipt, members)
    git = GitBytes(args.source, spec["source"])
    try:
        original, sources = bound_sources(receipt, members, git, spec)
    finally:
        git.close()
    generated = bound_generation(receipt, members, original, spec)
    result = inspect(receipt, members, spec)
    report = {
        "schema": 1, "key": spec["key"], "repository": spec["repository"], "source": spec["source"],
        "original_run": spec["run_id"], "artifact_id": spec["artifact_id"],
        "zip_bytes": len(archive), "zip_sha256": sha(archive), "all_member_crc": True,
        "original_qualification_status": receipt["status"], "source_verification": sources,
        "output_verification": outputs, "generation": generated, "result": result,
        "evidence_verification": "passed",
        "scope": "Read-only original bytes and complete original library evidence; no archived source was executed and no full-CI acceptance is claimed.",
    }
    rendered = json.dumps(report, indent=2).encode() + b"\n"
    (args.output / "VERIFIED.json").write_bytes(rendered)
    (args.output / "receipt.json").write_bytes(members["receipt.json"])
    (args.output / "artifact-metadata.json").write_bytes(json.dumps(metadata, indent=2).encode() + b"\n")
    projection = {key: value for key, value in report.items() if key != "output_verification"}
    projection["output_count"] = len(outputs)
    projection["verified_report_sha256"] = sha(rendered)
    print("ORIGINAL_SCHEMA_EVIDENCE_VERIFIED_JSON=" + json.dumps(projection, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
