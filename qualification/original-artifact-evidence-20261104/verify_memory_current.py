#!/usr/bin/env python3
"""Independently inspect retained current Memory artifacts; execute no archived code."""
import argparse
import ast
import base64
import gzip
import hashlib
import io
import os
import tomllib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from verify import GitBytes, LIMIT, canonical, emit_raw, fetch_artifact, request, require, sha, verify_sources

PACKAGES = ("codex-utils-path", "codex-state", "codex-hepta-memory")
TARGETS = {
    "path": "//codex-rs/utils/path-utils:path-utils-unit-tests",
    "state": "//codex-rs/state:state-unit-tests",
    "memory": "//codex-rs/hepta-memory:hepta-memory-unit-tests",
}
BAD_XML = {"failure", "error", "skipped", "rerunFailure", "rerunError", "flakyFailure", "flakyError"}
SCOPE = "qualification/windows-memory-recovery-current/scope.json"
NATIVE_READER = "qualification/windows-memory-recovery-current/run_native.py"


def unique(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "duplicate JSON key: " + key)
        value[key] = item
    return value


def parse(raw):
    return json.loads(raw, object_pairs_hook=unique)


def parse_cargo_metadata_log(raw):
    # generate.py sends both Cargo streams to the same original log. Cargo emits
    # one compact metadata document after any diagnostic lines; diagnostics are
    # retained and hashed independently instead of being parsed as JSON.
    starts = [match.start() for match in re.finditer(br'^\{"packages":', raw, re.M)]
    require(len(starts) == 1, "expected one line-start Cargo metadata document")
    prefix, document = raw[:starts[0]], raw[starts[0]:]
    require(len(prefix) <= 1024 * 1024, "Cargo diagnostic prefix exceeds reader bound")
    metadata = parse(document)
    require(isinstance(metadata, dict) and isinstance(metadata.get("packages"), list)
            and isinstance(metadata.get("workspace_members"), list)
            and metadata.get("version") == 1, "invalid Cargo metadata document")
    return metadata, {"bytes": len(prefix), "sha256": sha(prefix),
                      "preview_utf8": prefix[:8192].decode("utf-8", errors="replace"),
                      "preview_is_complete": len(prefix) <= 8192}


def verify_output_set(receipt, members):
    outputs = receipt["outputs"]
    require(set(outputs) == set(members) - {"receipt.json"}, "unbound or missing retained output")
    for name, value in outputs.items():
        raw = members[name]
        require(value == {"bytes": len(raw), "sha256": sha(raw)}, "output bytes differ: " + name)
    commands = receipt["commands"]
    by_name = {row["name"]: row for row in commands}
    require(len(by_name) == len(commands), "duplicate original command")
    for name, row in by_name.items():
        require(isinstance(row["argv"], list) and row["argv"] and
                all(isinstance(arg, str) for arg in row["argv"]), "invalid command argv")
        require(type(row["exit_code"]) is int, "invalid command exit")
        require(all(name + "." + suffix in outputs for suffix in ("stdout", "stderr")),
                "original command streams missing: " + name)
    return by_name, outputs


def inventory(raw, package, ignored):
    data = parse(raw)
    require(len(data["rust-suites"]) == 1, "more than the selected library")
    suite_id, suite = next(iter(data["rust-suites"].items()))
    require(suite["package-name"] == package and suite["kind"] == "lib" and suite["status"] == "listed",
            "wrong or unlisted library")
    cases = suite["testcases"]
    require(cases and data["test-count"] == len(cases), "empty/inconsistent test universe")
    ignored = set(ignored)
    observed = set()
    for name, case in cases.items():
        require(type(case["ignored"]) is bool and case.get("kind") in (None, "test"), "invalid case kind")
        if case["ignored"]:
            observed.add(name)
        expected_filter = {"status": "mismatch", "reason": "ignored"} if case["ignored"] else {"status": "matches"}
        require(case["filter-match"] == expected_filter, "unapproved test filter: " + name)
    require(observed == ignored, "original ignored case set changed")
    expected = set(cases) - ignored
    require(expected, "zero executable cases")
    return {"suite": suite_id, "binary": suite["binary-path"], "all_cases": sorted(cases),
            "expected": sorted(expected), "original_ignored": sorted(ignored)}


def junit(raw, expected):
    root = ET.fromstring(raw)
    suites = list(root.iter("testsuite"))
    require(suites, "no JUnit suite")
    require(not any(node.tag in BAD_XML for node in root.iter()), "failed, skipped or retried JUnit case")
    cases = list(root.iter("testcase"))
    names = [node.get("name") for node in cases]
    require(len(names) == len(set(names)) and set(names) == set(expected["expected"]),
            "JUnit is not the complete selected nonignored universe")
    require(sum(int(node.get("tests", "-1")) for node in suites) == len(names), "JUnit case counter mismatch")
    require(all(int(node.get(key, "0")) == 0 for node in suites for key in ("failures", "errors", "skipped")),
            "JUnit failure/skip counter")
    return {"passed": len(names), "failed": 0, "errors": 0, "skipped": 0, "retried": 0,
            "executed": names, "original_ignored": expected["original_ignored"]}


def static_windows_cases(raw):
    module = ast.parse(raw)
    for statement in module.body:
        if isinstance(statement, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "WINDOWS_REQUIRED"
                for target in statement.targets):
            result = ast.literal_eval(statement.value)
            require(set(result) == set(PACKAGES), "Windows required-package set changed")
            require(all(isinstance(value, set) and value and all(isinstance(x, str) for x in value)
                        for value in result.values()), "bad required Windows cases")
            return result
    raise RuntimeError("required Windows controls not bound")


def require_command(by_name, name, argv):
    require(name in by_name and by_name[name]["exit_code"] == 0 and by_name[name]["argv"] == argv,
            "original command changed or failed: " + name)


def inspect_native(receipt, members, git, by_name, spec):
    require(set(receipt["libraries"]) == set(PACKAGES), "missing or additional original libraries")
    require(all(row["exit_code"] == 0 for row in by_name.values()), "original command failed")
    require_command(by_name, "rustc-version", ["rustc", "-Vv"])
    require(members["rustc-version.stdout"].startswith(b"rustc 1.96.0 "), "compiler pin changed")
    require_command(by_name, "nextest-version", ["cargo", "nextest", "--version"])
    require(members["nextest-version.stdout"].startswith(b"cargo-nextest 0.9.151 "), "nextest pin changed")
    config = parse(git.read(SCOPE))
    required = static_windows_cases(git.read(NATIVE_READER))
    expected_host = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}[spec["host"]]
    host = receipt["host"]
    require((expected_host in host) or (spec["host"] == "macos" and "Darwin" in host), "native host mismatch")
    counts = {}
    for package in PACKAGES:
        require_command(by_name, package + "-inventory", [
            "cargo", "nextest", "list", "--locked", "-p", package, "--lib", "--message-format=json"])
        allow = config["original_ignored_memory_cases"] if package == "codex-hepta-memory" else []
        listed = inventory(members[package + "-inventory.stdout"], package, allow)
        actual = receipt["libraries"][package]
        require(actual["status"] == "passed" and actual["inventory"] == listed, "recorded inventory differs")
        if spec["host"] == "windows":
            suffixes = {name.rsplit("::", 1)[-1] for name in listed["expected"]}
            require(required[package] <= suffixes, "required Windows cases did not compile")
        require_command(by_name, package + "-original-tests", [
            "just", "test", "--locked", "-p", package, "--lib", "--no-tests=fail",
            "--retries", "0", "--success-output=final"])
        text = members[package + "-original-tests.stdout"] + members[package + "-original-tests.stderr"]
        require(b"skipping test:" not in text.lower(), "early-return skip")
        result = junit(members[package + "-junit.xml"], listed)
        require(actual["result"] == result, "JUnit differs from the original result receipt")
        require(re.fullmatch(r"[0-9a-f]{64}", actual["binary_sha256_before"]) is not None and
                actual["binary_sha256_before"] == actual["binary_sha256_after"], "recorded binary changed")
        counts[package] = {"executed": result["passed"], "original_ignored": listed["original_ignored"],
                           "inventory_cases": len(listed["all_cases"]),
                           "junit_sha256": sha(members[package + "-junit.xml"]),
                           "case_names_sha256": sha(canonical(result["executed"])),
                           "recorded_binary_sha256": actual["binary_sha256_before"]}
    require_command(by_name, "original-scoped-clippy", [
        "just", "fix", "--locked", "-p", PACKAGES[0], "-p", PACKAGES[1], "-p", PACKAGES[2], "--no-deps"])
    return {"mode": "native", "libraries": counts, "total_executed": sum(x["executed"] for x in counts.values()),
            "failed": 0, "skipped": 0, "retried": 0,
            "boundary": "Exact original Cargo inventory versus JUnit. Binary equality is the original recorded before/after hash; binaries are not retained in this artifact."}


def rust_counts(raw, ignored):
    text = raw.decode("utf-8").replace("\r\n", "\n")
    values = re.findall(
        r"test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out", text)
    require(values and values[-1][0] == "ok", "missing or failed final Rust summary")
    passed, failed, skipped, measured, filtered = map(int, values[-1][1:])
    require(passed > 0 and failed == measured == filtered == 0, "incomplete original Rust target")
    names = re.findall(r"^test (\S+) \.\.\. ignored(?:,.*)?$", text, re.M)
    require(len(names) == len(set(names)) == skipped and set(names) == set(ignored), "ignored set changed")
    require("skipping test:" not in text.lower(), "early-return Rust skip")
    return {"passed": passed, "failed": failed, "original_ignored": names,
            "measured": measured, "filtered": filtered, "rust_summaries": [list(value) for value in values]}


def bazel_list(raw, allow_empty=False):
    text = raw.decode("utf-8").replace("\r\n", "\n")
    rows = re.findall(r"^(\S+): (test|benchmark)$", text, re.M)
    names = [name for name, kind in rows]
    require((names or allow_empty) and len(names) == len(set(names)), "empty or duplicate compiled inventory")
    require(all(kind == "test" for _, kind in rows), "benchmark in original library inventory")
    return sorted(names)


def inspect_shards(name, count, listed, allowed, receipt, members):
    expected_relative = []
    for index in range(count):
        prefix = "" if count == 1 else "shard_" + str(index + 1) + "_of_" + str(count) + "/"
        expected_relative.extend([prefix + "test.log", prefix + "test.xml"])
    records = receipt["retained_reports"][name]
    require(len(records) == len(expected_relative), "wrong number of retained shard reports")
    mapping = {record["relative"]: record["file"] for record in records}
    require(len(mapping) == len(records) and set(mapping) == set(expected_relative),
            "missing, extra, repeated or retried original report")
    for relative, file_name in mapping.items():
        require(file_name == name + "--" + relative.replace("/", "--") and file_name in members,
                "retained shard path does not bind actual output")
    outcomes, summaries, shard_cases, ignored_names = {}, [], [], []
    for index in range(count):
        relative = "test.log" if count == 1 else "shard_" + str(index + 1) + "_of_" + str(count) + "/test.log"
        raw = members[mapping[relative]]
        text = raw.decode("utf-8").replace("\r\n", "\n")
        matches = list(re.finditer(
            r"test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out",
            text))
        require(len(matches) == 1 and matches[0][1] == "ok", "missing, failed or repeated Rust summary")
        summary = matches[0]
        counters = list(map(int, summary.groups()[1:]))
        rows = re.findall(r"^test (\S+) \.\.\. (ok|FAILED|ignored)(?:,.*)?$", text[:summary.start()], re.M)
        require(not any(line.startswith("test ") for line in text[summary.end():].splitlines()),
                "unaccounted cases after shard completion")
        require("skipping test:" not in text.lower(), "early-return skip in shard")
        require([sum(status == label for _, status in rows) for label in ("ok", "FAILED", "ignored")] == counters[:3]
                and counters[1] == counters[3] == 0, "shard counters disagree with actual cases")
        names = [case for case, _ in rows]
        require(len(names) == len(set(names)), "duplicate case within shard")
        for case, status in rows:
            require(case in listed and case not in outcomes, "extra or duplicate case across shards")
            hash_value = 0x811c9dc5
            for value in case.encode("utf-8"):
                hash_value = (hash_value ^ value) * 0x01000193 & 0xffffffff
            require(hash_value % count == index, "case ran in the wrong original shard")
            require(status == ("ignored" if case in allowed else "ok"), "unexpected ignored or failed case")
            outcomes[case] = status
            if status == "ignored":
                ignored_names.append(case)
        require(counters[4] == len(listed) - len(rows), "shard filtering does not conserve original inventory")
        summaries.append(counters)
        shard_cases.append(names)
        root = ET.fromstring(members[mapping[relative.removesuffix(".log") + ".xml"]])
        suites = list(root.iter("testsuite"))
        cases = list(root.iter("testcase"))
        require(suites and cases and sum(int(node.get("tests", "-1")) for node in suites) == len(cases),
                "empty or inconsistent wrapper XML")
        require(not any(node.tag in BAD_XML for node in root.iter()), "wrapper XML failure/skip/retry")
        require(all(int(node.get(key, "0")) == 0 for node in suites for key in ("failures", "errors", "skipped")),
                "wrapper XML failure counters")
    require(set(outcomes) == set(listed) and set(ignored_names) == set(allowed),
            "not the complete original disjoint case universe")
    result = {"passed": sum(value == "ok" for value in outcomes.values()), "failed": 0,
              "original_ignored": ignored_names, "measured": 0, "filtered": 0,
              "shard_counts": summaries, "shard_cases": shard_cases, "inventory": listed,
              "complete_disjoint_coverage": True}
    require(result["passed"] > 0 and receipt["targets"][name] == result, "recorded target coverage differs")
    return result


def inspect_bazel(receipt, members, git, by_name):
    require("Linux" in receipt["host"], "not the original Linux GNU host")
    require(set(receipt["targets"]) == set(receipt["inventories"]) == set(receipt["retained_reports"]) == set(TARGETS),
            "missing or additional original target")
    require(all(row["exit_code"] == 0 for row in by_name.values()), "original command failed")
    expected_commands = ["initial-clean-source", "committed-lock-first", "original-lock-update",
                         "original-lock-check", "original-testlog-location"]
    for key in TARGETS:
        expected_commands.extend(["original-inventory-" + key, "original-ignored-inventory-" + key])
    expected_commands.extend(["original-library-targets", "original-scoped-clippy", "final-clean-source"])
    require(list(by_name) == expected_commands, "original command sequence changed")
    for name, argv in [("committed-lock-first", ["just", "bazel-lock-check"]),
                       ("original-lock-update", ["just", "bazel-lock-update"]),
                       ("original-lock-check", ["just", "bazel-lock-check"])]:
        require_command(by_name, name, argv)
    wrapper = [receipt["bash_executable"], "./.github/scripts/run-bazel-ci.sh", "--print-failed-test-logs",
               "--print-failed-action-summary", "--remote-download-toplevel", "--"]
    require_command(by_name, "original-library-targets", [
        *wrapper, "test", "--keep_going", "--nocache_test_results", "--test_output=all", "--", *TARGETS.values()])
    command_log = members["original-library-targets.stdout"] + members["original-library-targets.stderr"]
    require(re.search(rb"Executed 3 out of 3 tests?: 3 tests? pass", command_log), "not all original targets executed")
    allow = parse(git.read(SCOPE))["original_ignored_memory_cases"]
    counts = {"path": 1, "state": 4, "memory": 1}
    results = {}
    for name, target in TARGETS.items():
        prefix = [*wrapper, "run", "--test_sharding_strategy=disabled", target, "--", "--list", "--format", "terse"]
        require_command(by_name, "original-inventory-" + name, prefix)
        require_command(by_name, "original-ignored-inventory-" + name, [*prefix, "--ignored"])
        listed = bazel_list(members["original-inventory-" + name + ".stdout"])
        ignored = bazel_list(members["original-ignored-inventory-" + name + ".stdout"], allow_empty=True)
        wanted = allow if name == "memory" else []
        require(set(ignored) == set(wanted) and set(ignored) <= set(listed), "original ignored set changed")
        require(receipt["inventories"][name] == {"all_cases": listed, "original_ignored": ignored},
                "recorded inventory differs from actual compiled list")
        results[name] = inspect_shards(name, counts[name], listed, wanted, receipt, members)
    require_command(by_name, "original-scoped-clippy", [
        *wrapper, "build", "--config=clippy", "--", *(target + "-bin" for target in TARGETS.values())])
    return {"mode": "bazel", "targets": results,
            "total_executed": sum(value["passed"] for value in results.values()),
            "boundary": "Original 3/3 target execution; every fresh original shard, compiled case inventory, full disjoint assigned coverage, exact original ignores, original Clippy and unchanged committed lock inputs."}


def generation_outputs(receipt, members):
    outputs = receipt["outputs"]
    require(set(outputs) == set(members) - {"receipt.json"}, "unbound or missing generated output")
    for name, value in outputs.items():
        require(value == {"bytes": len(members[name]), "sha256": sha(members[name])},
                "generated output bytes differ: " + name)
    commands = receipt["commands"]
    by_name = {row["name"]: row for row in commands}
    require(len(by_name) == len(commands), "duplicate generation command")
    for name, row in by_name.items():
        require(row["log_sha256"] == sha(members[name + ".log"]), "generation command log differs")
    return by_name, outputs


def inspect_generation(receipt, members, git, by_name, spec):
    config = parse(git.read(SCOPE))
    base = config["base_commit"]
    require(receipt["base_commit"] == base and receipt["changed_paths"] == []
            and receipt["committed_cargo_equals_generated"] is True
            and receipt["committed_bazel_equals_generated"] is True,
            "generated source or locks still need adoption")
    commands = [
        ("initial-clean-source", ["git", "--no-replace-objects", "diff", "--exit-code", "HEAD", "--"]),
        ("committed-lock-first", ["just", "bazel-lock-check"]),
        ("original-formatter", ["just", "fmt", "--base", base]),
        ("original-formatter-check", ["just", "fmt", "--check", "--base", base]),
        ("actual-cargo-metadata", ["cargo", "metadata", "--all-features", "--format-version", "1"]),
        ("actual-locked-metadata", ["cargo", "metadata", "--locked", "--all-features", "--format-version", "1"]),
        ("original-lock-update", ["just", "bazel-lock-update"]),
        ("original-lock-check", ["just", "bazel-lock-check"]),
    ]
    require(list(by_name) == [name for name, _ in commands], "original generation sequence changed")
    for name, argv in commands:
        require_command(by_name, name, argv)
    for file_name, git_path in [("Cargo.lock", "codex-rs/Cargo.lock"), ("MODULE.bazel.lock", "MODULE.bazel.lock")]:
        require(members[file_name] == members["committed-" + file_name] == git.read(git_path),
                "generated lock differs from exact committed Git bytes")
    parse(members["MODULE.bazel.lock"])
    metadata_diagnostics = {}
    for name in ("actual-cargo-metadata", "actual-locked-metadata"):
        raw = members[name + ".log"]
        with gzip.GzipFile(fileobj=io.BytesIO(members[name + ".log.gz"])) as stream:
            uncompressed = stream.read(LIMIT + 1)
        require(len(uncompressed) <= LIMIT and uncompressed == raw, "retained metadata gzip differs")
        metadata, metadata_diagnostics[name] = parse_cargo_metadata_log(raw)
        require(len(metadata["packages"]) == config["package_count"], "metadata package count changed")
    oid = config["base_cargo_blob"]
    document = parse(request("https://api.github.com/repos/" + spec["repository"] + "/git/blobs/" + oid,
                             os.environ["GITHUB_TOKEN"]))
    require(document["sha"] == oid and document["encoding"] == "base64", "wrong original baseline Git blob")
    baseline = base64.b64decode("".join(document["content"].split()), validate=True)
    require(len(baseline) == document["size"] and
            hashlib.sha1(b"blob " + str(len(baseline)).encode() + b"\0" + baseline).hexdigest() == oid,
            "original baseline Cargo bytes do not match Git identity")
    before, after = tomllib.loads(baseline.decode()), tomllib.loads(members["Cargo.lock"].decode())
    def records(value):
        rows = {(row["name"], row["version"], row.get("source", "")): row for row in value["package"]}
        require(len(rows) == len(value["package"]), "duplicate Cargo package")
        return rows
    old, new = records(before), records(after)
    require(set(old) == set(new) and len(new) == config["package_count"], "package versions/sources changed")
    require({k: v for k, v in before.items() if k != "package"} ==
            {k: v for k, v in after.items() if k != "package"}, "Cargo header changed")
    observed = {}
    for key, row in old.items():
        wanted = config["expected_added_dependencies"].get(key[0])
        if wanted is None:
            require(row == new[key], "unrelated package record changed")
            continue
        require(not key[2] and {k: v for k, v in row.items() if k != "dependencies"} ==
                {k: v for k, v in new[key].items() if k != "dependencies"}, "workspace record identity changed")
        require(new[key].get("dependencies") == sorted(row.get("dependencies", []) + wanted),
                "unexpected workspace dependency edges")
        observed[key[0]] = wanted
    delta = {"packages": len(new), "added_dependencies": observed, "versions_sources_checksums_unchanged": True}
    require(observed == config["expected_added_dependencies"] and receipt["cargo_delta"] == delta,
            "recorded Cargo delta differs")
    return {"mode": "generation", "commands": [name for name, _ in commands], "command_exits": [0] * len(commands),
            "cargo_delta": delta, "cargo_sha256": sha(members["Cargo.lock"]),
            "bazel_sha256": sha(members["MODULE.bazel.lock"]), "baseline_cargo_blob": oid,
            "committed_and_generated_match_exact_git": True, "metadata_diagnostics": metadata_diagnostics,
            "boundary": "Actual original formatting/metadata/lock generation; no native result inferred."}


def main():
    require(__debug__, "optimized Python is not accepted")
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    matches = [item for item in parse(args.manifest.read_bytes()) if item["key"] == args.key]
    require(len(matches) == 1, "unknown or duplicate artifact key")
    spec = matches[0]
    args.output.mkdir(parents=True, exist_ok=False)
    metadata, raw, members = fetch_artifact(spec)
    (args.output / "original.zip").write_bytes(raw)
    receipt = parse(members["receipt.json"])
    require(receipt["source_commit"] == spec["source"], "wrong original source")
    require(receipt["status"] == spec["expected_original_status"], "unexpected original verdict")
    if spec["kind"] != "memory-generation":
        require(receipt["run_id"] == str(spec["run_id"]), "wrong original run in receipt")
    source_before = parse(members["source-before.json"])
    bound_receipt = {**receipt, "source_before": source_before}
    git = GitBytes(args.source, spec["source"])
    try:
        # Both original Memory readers import the raw-link snapshot from generate.py.
        source = verify_sources({**spec, "kind": "generation"}, bound_receipt, members, git)
        if spec["kind"] == "memory-generation":
            require(receipt["status"] == "committed-lock-qualified", "generation is not qualified")
            by_name, outputs = generation_outputs(receipt, members)
            result = inspect_generation(receipt, members, git, by_name, spec)
        else:
            by_name, outputs = verify_output_set(receipt, members)
        if spec["kind"] == "memory-generation":
            pass
        elif receipt["status"] == "passed":
            for name in ("initial-clean-source", "final-clean-source"):
                require_command(by_name, name, ["git", "--no-replace-objects", "diff", "--exit-code", "HEAD", "--"])
            if spec["kind"] == "memory-native":
                result = inspect_native(receipt, members, git, by_name, spec)
            elif spec["kind"] == "memory-bazel":
                result = inspect_bazel(receipt, members, git, by_name)
            else:
                raise RuntimeError("unsupported current Memory artifact kind")
        else:
            require(receipt["status"] == "failed", "unsupported original failure state")
            result = {"mode": "negative-evidence", "original_commands": receipt["commands"],
                      "original_libraries": receipt.get("libraries"), "original_targets": receipt.get("targets"),
                      "original_problems": receipt.get("problems"), "failed_streams": {}}
            failed = [row for row in by_name.values() if row["exit_code"] != 0]
            incomplete = (spec["kind"] == "memory-bazel" and set(receipt.get("targets", {})) != set(TARGETS))
            require(failed or receipt.get("problems") or incomplete, "no recorded original failure")
            result["observed_junit"] = {}
            for package in PACKAGES:
                name = package + "-junit.xml"
                if name in members:
                    root = ET.fromstring(members[name])
                    cases = list(root.iter("testcase"))
                    result["observed_junit"][package] = {
                        "cases": len(cases), "sha256": sha(members[name]),
                        "failures": [{"name": case.get("name"),
                                      "details": [{"tag": child.tag, "attributes": child.attrib, "text": child.text}
                                                  for child in case if child.tag in BAD_XML or child.tag in {"system-out", "system-err"}]}
                                     for case in cases if any(child.tag in BAD_XML for child in case)]
                    }
            if spec["kind"] == "memory-bazel":
                for suffix in ("stdout", "stderr"):
                    name = "original-library-targets." + suffix
                    if name in members:
                        emit_raw(name, members[name])
            for row in failed:
                for suffix in ("stdout", "stderr"):
                    name = row["name"] + "." + suffix
                    result["failed_streams"][name] = outputs[name]
                    emit_raw(name, members[name])
    finally:
        git.close()
    report = {"schema": 1, "repository": spec["repository"], "source": spec["source"],
              "original_run": spec["run_id"], "artifact_id": spec["artifact_id"],
              "original_qualification_status": receipt["status"], "key": spec["key"],
              "zip_bytes": len(raw), "zip_sha256": sha(raw), "all_member_crc": True,
              "source_verification": source, "output_verification": outputs, "result": result,
              "evidence_verification": "passed",
              "scope": "Read-only verification of original retained evidence; no new product execution or whole-CI admission."}
    rendered = json.dumps(report, indent=2).encode() + b"\n"
    (args.output / "VERIFIED.json").write_bytes(rendered)
    (args.output / "receipt.json").write_bytes(members["receipt.json"])
    (args.output / "artifact-metadata.json").write_bytes(json.dumps(metadata, indent=2).encode() + b"\n")
    compact = {key: value for key, value in report.items() if key != "output_verification"}
    if compact["result"].get("mode") == "negative-evidence":
        compact["result"] = dict(compact["result"])
        compact["result"]["original_libraries"] = {
            name: {"status": value.get("status"),
                   "inventory_count": len(value.get("inventory", {}).get("all_cases", [])),
                   "expected_count": len(value.get("inventory", {}).get("expected", [])),
                   "result_passed": value.get("result", {}).get("passed")}
            for name, value in (compact["result"].get("original_libraries") or {}).items()
        }
    compact["output_count"] = len(outputs)
    compact["verified_report_sha256"] = sha(rendered)
    print("MEMORY_EVIDENCE_VERIFIED_JSON=" + json.dumps(compact, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
