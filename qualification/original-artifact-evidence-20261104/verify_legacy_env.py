#!/usr/bin/env python3
"""Verify the older no-prewarm Git/queue artifact without importing its code."""
import argparse
import json
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from verify import GitBytes, fetch_artifact, request, require, sha

INPUTS = [
    ".bazelrc", "defs.bzl", "workspace_root_test_launcher.bat.tpl",
    "MODULE.bazel.lock", "codex-rs/Cargo.lock", "codex-rs/git-utils/BUILD.bazel",
    "codex-rs/git-utils/src/git_process.rs", "codex-rs/git-utils/src/git_process_tests.rs",
    "codex-rs/ext/queue/BUILD.bazel", "codex-rs/ext/queue/tests/queue_service.rs",
    "codex-rs/utils/pty/src/win/job.rs",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    matches = [row for row in json.loads(args.manifest.read_bytes()) if row["key"] == args.key]
    require(len(matches) == 1, "unknown artifact")
    spec = matches[0]
    require(spec["kind"] == "legacy-env", "wrong evidence reader")
    args.output.mkdir(parents=True, exist_ok=False)
    metadata, raw, members = fetch_artifact(spec)
    (args.output / "original.zip").write_bytes(raw)
    sources = [name for name in members if name == "source.json" or name.endswith("/source.json")]
    require(len(sources) == 1, "ambiguous original source receipt")
    prefix = sources[0][:-len("source.json")]
    source = json.loads(members[sources[0]])
    retained = json.loads(members[prefix + "retained.json"])
    require(source["head"] == spec["source"] and str(source["run_id"]) == str(spec["run_id"]),
            "wrong original source/run")
    require(source["pre_test_powershell_probe"] is False and source["diagnostic_only"] is False,
            "original evidence contains a preparatory diagnostic")
    require(set(source["inputs"]) == set(INPUTS), "original eleven input set changed")
    git = GitBytes(args.source, spec["source"])
    try:
        require(git.command("rev-parse", "HEAD^{tree}").decode().strip() == source["tree"], "wrong source tree")
        input_bytes = {}
        for name in INPUTS:
            raw_git = git.read(name)
            actual = source["inputs"][name]
            raw_sha = sha(raw_git)
            if actual == raw_sha:
                input_bytes[name] = {"git_blob": git.tree[name][2], "git_sha256": raw_sha,
                                     "recorded_sha256": actual, "checkout_bytes": "exact"}
                continue
            # This historical Windows workflow did not pin core.autocrlf.
            # Prove its exact CRLF checkout bytes, never silently normalize or
            # describe those bytes as identical to the canonical Git blob.
            require(b"\r" not in raw_git and b"\0" not in raw_git
                    and sha(raw_git.replace(b"\n", b"\r\n")) == actual,
                    "original Git input mismatch beyond exact CRLF checkout: " + name)
            input_bytes[name] = {"git_blob": git.tree[name][2], "git_sha256": raw_sha,
                                 "recorded_sha256": actual, "checkout_bytes": "exact LF-to-CRLF transform"}
        observed_objects = git.command("ls-tree", "HEAD", "--", *INPUTS).decode()
        require(observed_objects == source["input_git_objects"], "original Git object list differs")
        workflow = git.read(".github/workflows/windows-bazel-process-native.yml")
        require(git.tree[".github/workflows/windows-bazel-process-native.yml"][2] ==
                "0902ceaca163b9f32036029a1140c0b368ee3dfd", "wrong original qualifier source")
    finally:
        git.close()
    require(retained["unchanged_inputs"] is True and len(retained["logs"]) == 4,
            "original unchanged-input checker failed")
    expected = {target + "-test." + ext
                for target in ["git-utils-unit-tests", "queue-queue_service-test"] for ext in ["log", "xml"]}
    require({entry["file"] for entry in retained["logs"]} == expected, "wrong retained reports")
    for row in retained["logs"]:
        data = members[prefix + row["file"]]
        require(len(data) == row["bytes"] and sha(data) == row["sha256"], "original report bytes differ")
    results = {}
    for target, count in [("git-utils-unit-tests", 33), ("queue-queue_service-test", 35)]:
        log_raw = members[prefix + target + "-test.log"]
        xml_raw = members[prefix + target + "-test.xml"]
        log = log_raw.decode("utf-8-sig").replace("\r\n", "\n")
        xml = ET.fromstring(xml_raw)
        suites, cases = xml.findall("testsuite"), xml.findall(".//testcase")
        require(len(suites) == 1 and len(cases) == 1, "original Bazel wrapper count differs")
        require(suites[0].get("tests") == "1" and suites[0].get("failures") == "0"
                and suites[0].get("errors") == "0"
                and not any(cases[0].find(tag) is not None for tag in ["failure", "error", "skipped"]),
                "original Bazel wrapper failed")
        stdout = suites[0].find("system-out")
        require(stdout is not None and (stdout.text or "").replace("\r\n", "\n").strip() == log.strip(),
                "XML/log payload mismatch")
        summaries = [list(map(int, row)) for row in re.findall(
            r"^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out",
            log, re.M)]
        nested = [[1, 0, 0, 0, 32]] if target == "git-utils-unit-tests" else []
        require(summaries == [*nested, [count, 0, 0, 0, 0]], "incomplete original native suite")
        names = set(re.findall(r"^test (\S+) \.\.\. ok$", log, re.M))
        require(len(names) == count and not re.search(r"^test .* \.\.\. (FAILED|ignored)", log, re.M)
                and "skipping test:" not in log.lower(), "missing or skipped original cases")
        results[target] = {"outer_passed": count, "outer_failed": 0, "outer_ignored": 0,
                           "outer_filtered": 0, "names": sorted(names), "nested_summaries": nested,
                           "log_sha256": sha(log_raw), "xml_sha256": sha(xml_raw)}
    api = "https://api.github.com/repos/" + spec["repository"]
    job = json.loads(request(api + "/actions/jobs/" + str(spec["job_id"]), os.environ["GITHUB_TOKEN"]))
    require(job["run_id"] == spec["run_id"] and job["conclusion"] == "success", "original job failed")
    steps = {row["name"]: row["conclusion"] for row in job["steps"]}
    for name in ["Record unchanged source and original runner configuration",
                 "Run original Bazel process suites without cached test results",
                 "Retain the actual test logs and unchanged-input checks", "Check for a clean worktree"]:
        require(steps.get(name) == "success", "original gate was not successful: " + name)
    report = {"schema": 1, "key": spec["key"], "source": spec["source"], "source_tree": source["tree"],
              "original_run": spec["run_id"], "original_job": spec["job_id"],
              "artifact_id": spec["artifact_id"], "zip_bytes": len(raw), "zip_sha256": sha(raw),
              "crc_all_members": True, "git_inputs_verified": len(INPUTS),
              "source_before": source["inputs"], "input_byte_verification": input_bytes,
              "original_checker_reports_unchanged": True,
              "source_after_map_not_retained_by_original_reader": True,
              "qualifier_workflow_sha256": sha(workflow), "pre_test_powershell_probe": False,
              "original_qualification_status": "passed", "evidence_verification": "passed",
              "result": results,
              "scope": "Historical exact source only; no current dependency-union qualification."}
    (args.output / "original.zip").write_bytes(raw)
    (args.output / "VERIFIED.json").write_text(json.dumps(report, indent=2) + "\n")
    (args.output / "artifact-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (args.output / "original-job.json").write_text(json.dumps(job, indent=2) + "\n")
    print("LEGACY_EVIDENCE_VERIFIED_JSON=" + json.dumps(report, separators=(",", ":")))


if __name__ == "__main__":
    main()
