#!/usr/bin/env python3
"""Independently inspect the completed upstream Tee backport qualification."""
import argparse
import base64
import json
import ntpath
from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET

from verify import GitBytes, canonical, emit_raw, fetch_artifact, require, sha, verify_sources

FOLDER = "qualification/bazel9-output-backport-20261104"
ROBRIX_READER = "qualification/robrix-runfiles-20261104/run.py"
ROBRIX_TARGET = "//codex-rs/hepta-supervisor:hepta-supervisor-robrix_control_projection-test"
ROBRIX_CASES = {
    "robrix_control_v2_generated_projection_and_cross_parser_corpus",
    "writer_reproduces_the_tracked_artifact_set_byte_for_byte",
}
BAD_XML = {"failure", "error", "skipped", "rerunFailure", "rerunError", "flakyFailure", "flakyError"}


def pairs_unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def parse(raw):
    return json.loads(raw, object_pairs_hook=pairs_unique)


def identity(raw):
    return {"bytes": len(raw), "sha256": sha(raw)}


def exact_output_map(outputs, members):
    require(set(outputs) == set(members) - {"receipt.json"}, "unbound or missing retained member")
    for name, value in outputs.items():
        require(value == identity(members[name]), "retained bytes differ: " + name)


def gtest(raw, binding):
    root = ET.fromstring(raw)
    require(root.tag == "testsuites", "missing full GTest document")
    expected = binding["original_gtest_cases"] + binding["additional_upstream_cases"]
    require(len(expected) == len(set(expected)) == binding["required_gtest_count"] == 20,
            "incorrect GTest universe")
    require(len(binding["original_gtest_cases"]) == 18 and len(binding["additional_upstream_cases"]) == 2,
            "upstream GTest split changed")
    nodes = list(root.iter("testcase"))
    names = [node.get("classname", "") + "." + node.get("name", "") for node in nodes]
    require(root.get("tests") == "20" and len(names) == len(set(names)) == 20 and set(names) == set(expected),
            "GTest execution differs from exact original and upstream-added cases")
    suites = list(root.iter("testsuite"))
    require(sum(int(node.get("tests", "-1")) for node in suites) == 20, "GTest suite counters differ")
    require(all(int(node.get(key, "0")) == 0 for node in [root, *suites]
                for key in ("failures", "errors", "disabled", "skipped")), "unsuccessful GTest counters")
    require(not any(node.tag in BAD_XML for node in root.iter()), "GTest failure, skip or retry")
    require(all(node.get("status") == "run" and node.get("result") == "completed" for node in nodes),
            "GTest did not actually complete")
    return {"count": 20, "original": 18, "additional_upstream": 2, "failures": 0, "skipped": 0,
            "cases": names, "xml": identity(raw)}


def tool_inventory(value):
    require(value and all(isinstance(name, str) and name and not name.startswith("/")
                         and ".." not in name.split("/") and "\\" not in name for name in value),
            "invalid embedded-tool paths")
    for name, entry in value.items():
        require(isinstance(entry, dict), "invalid embedded-tool identity")
        kind = entry.get("kind")
        if kind == "directory":
            require(entry == {"kind": "directory"}, "invalid directory record")
        elif kind == "file":
            require(set(entry) == {"kind", "bytes", "sha256"} and type(entry["bytes"]) is int and
                    entry["bytes"] >= 0 and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]),
                    "invalid file identity: " + name)
        elif kind == "symlink":
            require(set(entry) == {"kind", "target"} and isinstance(entry["target"], str),
                    "invalid symlink identity")
        else:
            raise RuntimeError("unsupported embedded-tool kind")


def inspect_robrix(receipt, members, git, spec):
    require(receipt["commit"] == spec["source"] and receipt["status"] == "passed" and
            receipt["config"] == "ci-windows" and "Windows" in receipt["platform"], "wrong Robrix source/platform")
    source = verify_sources({**spec, "kind": "robrix", "reader": ROBRIX_READER}, receipt, members, git)
    exact_output_map(receipt["outputs"], members)
    text = members["robrix.log"].decode().replace("\r\n", "\n")
    summaries = re.findall(r"test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out", text)
    require(summaries == [("ok", "2", "0", "0", "0", "0")], "Robrix final original denominator changed")
    names = re.findall(r"^test (\S+) \.\.\. ok$", text, re.M)
    require(len(names) == len(set(names)) == 2 and set(names) == ROBRIX_CASES and
            receipt["original_cases"] == names and receipt["test_counts"] == [2, 0, 0, 0, 0],
            "Robrix exact executed cases differ")
    require("skipping test:" not in text.lower(), "early-return Robrix skip")
    root = ET.fromstring(members["robrix.xml"])
    suites, cases = list(root.iter("testsuite")), list(root.iter("testcase"))
    require(suites and cases and sum(int(node.get("tests", "-1")) for node in suites) == len(cases),
            "empty or inconsistent Robrix wrapper XML")
    require(all(int(node.get(key, "0")) == 0 for node in suites for key in ("failures", "errors", "skipped"))
            and not any(node.tag in BAD_XML for node in root.iter()), "Robrix failed/skipped/retried wrapper")
    rows = receipt["steps"]
    expected = ["committed-inputs-clean-before", "original-robrix-corpus-tests", "original-testlog-location",
                "original-clippy-selector", "original-clippy", "committed-inputs-clean-after"]
    require([row["name"] for row in rows] == expected and all(row["exit"] == 0 for row in rows),
            "original Robrix commands changed or failed")
    steps = {row["name"]: row for row in rows}
    for name in expected:
        require(all(name + "." + suffix in members for suffix in ("stdout", "stderr")), "missing original stream")
    bash = receipt["bash_executable"]
    wrapper = [bash, "./.github/scripts/run-bazel-ci.sh", "--print-failed-test-logs",
               "--print-failed-action-summary", "--windows-msvc-host-platform", "--remote-download-toplevel", "--"]
    require(steps["original-robrix-corpus-tests"]["command"] == [
        *wrapper, "test", "--platforms=//:windows_x86_64_msvc", "--keep_going",
        "--nocache_test_results", "--test_output=all", "--", ROBRIX_TARGET], "original Robrix test invocation changed")
    require(steps["original-clippy"]["command"] == [
        *wrapper, "build", "--platforms=//:windows_x86_64_msvc", "--config=clippy", "--", ROBRIX_TARGET],
        "original Robrix Clippy target changed")
    require(steps["original-clippy-selector"]["command"] == [bash, "./scripts/list-bazel-clippy-targets.sh"] and
            "//codex-rs/..." in members["original-clippy-selector.stdout"].decode().splitlines(), "Clippy selector changed")
    for name in ("committed-inputs-clean-before", "committed-inputs-clean-after"):
        require(steps[name]["command"] == ["git", "diff", "--exit-code", "HEAD", "--"], "checkout check changed")
    original = members["original-robrix-corpus-tests.stdout"] + members["original-robrix-corpus-tests.stderr"]
    require(re.search(rb"Executed 1 out of 1 tests?: 1 tests? pass", original), "Robrix original target not executed")
    return {"source": source, "outputs": len(receipt["outputs"]), "executed": 2, "failed": 0,
            "ignored": 0, "filtered": 0, "cases": names, "original_commands": rows}


def main():
    require(__debug__, "optimized Python is not accepted")
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    matches = [item for item in parse(args.manifest.read_bytes()) if item["key"] == args.key]
    require(len(matches) == 1, "unknown artifact key")
    spec = matches[0]
    args.output.mkdir(parents=True, exist_ok=False)
    metadata, zip_raw, members = fetch_artifact(spec)
    (args.output / "original.zip").write_bytes(zip_raw)
    prefix = spec["receipt_path"].removesuffix("receipt.json")
    robrix_prefix = "robrix-runfiles/"
    require(set(members) == {name for name in members if name.startswith(prefix) or name.startswith(robrix_prefix)},
            "unrecognized ZIP root")
    helper = {name[len(prefix):]: value for name, value in members.items() if name.startswith(prefix)}
    robrix = {name[len(robrix_prefix):]: value for name, value in members.items() if name.startswith(robrix_prefix)}
    receipt = parse(helper["receipt.json"])
    require(receipt["status"] == "passed" and receipt["product_commit"] == spec["source"] and
            "Windows" in receipt["native_host"], "wrong successful original helper source or host")
    git = GitBytes(args.source, spec["source"])
    try:
        expected_inputs = {name for name, entry in git.tree.items()
                           if name.startswith(FOLDER + "/") and "/" not in name[len(FOLDER) + 1:]
                           and entry[1] == "blob"} | {".bazelrc"}
        inputs = receipt["qualification_inputs"]
        require(set(inputs) == expected_inputs, "helper input scope is incomplete")
        for name, value in inputs.items():
            require(value == identity(git.read(name)), "helper input differs from exact Git: " + name)
        binding = parse(git.read(FOLDER + "/source-binding.json"))
        require(receipt["upstream_base"] == binding["upstream_base_commit"] and
                receipt["fix_commit"] == binding["fix_commit"] and receipt["upstream_tree"] == spec["upstream_tree"],
                "upstream commit/tree differs")
        require(sha(git.read(FOLDER + "/bazel9-windows-tee-drain.patch")) == binding["patch_sha256"],
                "actual patch differs from original binding")
        exact_output_map(receipt["evidence_outputs"], helper)
        for name, value in binding["files"].items():
            raw = helper[Path(name).name]
            require(identity(raw) == {"bytes": value["patched_bytes"], "sha256": value["patched_sha256"]},
                    "actual patched upstream source differs")
        parsed_gtest = gtest(helper["tw-gtest.xml"], binding)
        require(receipt["gtest"] == parsed_gtest, "original GTest receipt differs from complete XML")
        binary = helper["tw.exe"]
        require(identity(binary) == receipt["built_wrapper"], "retained binary differs from qualified wrapper")
        require(len(binary) > 64 and binary[:2] == b"MZ", "not a PE executable")
        pe = struct.unpack_from("<I", binary, 60)[0]
        require(pe + 6 <= len(binary) and binary[pe:pe + 4] == b"PE\0\0" and
                struct.unpack_from("<H", binary, pe + 4)[0] == 0x8664, "not native Windows x64")
        before, override = parse(helper["installed-tools-before.json"]), parse(helper["override-tools.json"])
        tool_inventory(before)
        tool_inventory(override)
        require(set(before) == set(override) and len(before) == receipt["embedded_entry_count"],
                "embedded-tool entry universe changed")
        changed = [name for name in before if before[name] != override[name]]
        require(changed == ["tools/test/tw.exe"] and receipt["only_changed_tool"] == changed[0],
                "more than the one qualified tool changed")
        require(override[changed[0]] == {"kind": "file", **identity(binary)}, "override is not the qualified binary")
        require(receipt["original_installed_tools_unchanged"] is True and
                receipt["qualified_override_unchanged"] is True, "original finalizer did not pass")
        steps = receipt["steps"]
        expected = ["product-identity", "product-clean-before", "upstream-init", "upstream-line-endings",
                    "upstream-remote", "upstream-fetch", "upstream-checkout", "upstream-identity",
                    "upstream-tree", "upstream-clean-before", "upstream-patch-check", "upstream-patch",
                    "upstream-exact-diff", "upstream-changed-paths", "builder-version", "build-original-tw-target",
                    "test-complete-original-tw-target", "upstream-bazel-bin", "upstream-changed-paths-after",
                    "product-bazel-version", "product-install-base", "product-clean-after-prepare"]
        require([row["name"] for row in steps] == expected and all(row["exit"] == 0 for row in steps),
                "helper command sequence changed or failed")
        by_name = {row["name"]: row for row in steps}
        for name in expected:
            require(all(name + "." + suffix in helper for suffix in ("stdout", "stderr")), "helper stream missing")
        versions = helper["builder-version.stdout"].decode().splitlines()
        require(versions == receipt["builder_versions"] == [
            "Bazelisk " + binding["bazelisk_version"], "bazel " + binding["upstream_builder_version"]],
            "builder or launcher version changed")
        version = by_name["builder-version"]["command"]
        require(version[-2:] == ["version", "--gnu_format"], "builder version invocation changed")
        builder = version[:-2]
        require(len(builder) == 5 and builder[1:3] == ["--nosystem_rc", "--nohome_rc"] and
                builder[3] == "--output_base=" + ntpath.join(receipt["work"], "b") and
                builder[4] == "--output_user_root=" + ntpath.join(receipt["work"], "u"),
                "builder is not the original isolated invocation")
        require(by_name["build-original-tw-target"]["command"] ==
                [*builder, "build", "--lockfile_mode=error", "//tools/test:tw"], "original build target changed")
        require(by_name["test-complete-original-tw-target"]["command"] == [
            *builder, "test", "--lockfile_mode=error", "--nocache_test_results", "--test_output=all",
            "--flaky_test_attempts=1", "--test_env=GTEST_OUTPUT=xml:" + ntpath.join(receipt["work"], "evidence", "tw-gtest.xml"),
            "//tools/test:tw_test"], "original GTest command changed")
        require(helper["upstream-identity.stdout"].decode().strip() == binding["upstream_base_commit"] and
                helper["upstream-tree.stdout"].decode().strip() == spec["upstream_tree"], "actual upstream identity differs")
        require(helper["product-bazel-version.stdout"].decode().splitlines() == ["bazel 9.0.0"],
                "product Bazel version changed")
        for name in ("upstream-changed-paths.stdout", "upstream-changed-paths-after.stdout"):
            require(set(helper[name].decode().splitlines()) == set(binding["files"]), "unrelated upstream mutation")
        robrix_receipt = parse(robrix["receipt.json"])
        require(identity(robrix["receipt.json"]) == receipt["robrix_receipt"], "finalizer bound a different Robrix receipt")
        robrix_result = inspect_robrix(robrix_receipt, robrix, git, spec)
        exact_files = {}
        for name in [prefix + "receipt.json", prefix + "tw-gtest.xml", prefix + "installed-tools-before.json",
                     prefix + "override-tools.json", robrix_prefix + "receipt.json",
                     robrix_prefix + "robrix.log", robrix_prefix + "robrix.xml"]:
            raw = members[name]
            exact_files[name] = identity(raw)
            emit_raw(name, raw)
            print("EXACT_ORIGINAL_FILE_BASE64=" + json.dumps({
                "path": name, **exact_files[name], "base64": base64.b64encode(raw).decode()
            }, separators=(",", ":")), flush=True)
        report = {"schema": 1, "repository": spec["repository"], "source": spec["source"],
                  "original_run": spec["run_id"], "artifact_id": spec["artifact_id"],
                  "zip_bytes": len(zip_raw), "zip_sha256": sha(zip_raw), "all_member_crc": True,
                  "original_qualification_status": "passed", "evidence_verification": "passed",
                  "helper_inputs": {"count": len(inputs), "all_exact_git_bytes": True,
                                    "map_sha256": sha(canonical(inputs))},
                  "helper_outputs": len(receipt["evidence_outputs"]), "gtest": parsed_gtest,
                  "native_wrapper": identity(binary), "embedded_entries": len(before),
                  "embedded_kind_counts": {kind: sum(row["kind"] == kind for row in before.values())
                                           for kind in ("file", "directory", "symlink")},
                  "only_changed_embedded_entry": changed, "robrix": robrix_result, "exact_files": exact_files,
                  "boundaries": ["Read-only inspection; no archived executable or source was executed.",
                                 "Installed/override final stability is the original source-bound finalizer observation; separate post-finalizer inventories are not retained.",
                                 "This one prepared Windows job does not prove every other CI consumer installs the override."]}
        (args.output / "VERIFIED.json").write_bytes(json.dumps(report, indent=2).encode() + b"\n")
        (args.output / "artifact-metadata.json").write_bytes(json.dumps(metadata, indent=2).encode() + b"\n")
        print("TEE_EVIDENCE_VERIFIED_JSON=" + json.dumps(report, separators=(",", ":")), flush=True)
    finally:
        git.close()


if __name__ == "__main__":
    main()
