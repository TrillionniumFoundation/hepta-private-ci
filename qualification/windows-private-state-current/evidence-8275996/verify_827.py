#!/usr/bin/env python3
"""Verify the original mixed-result run without granting its successor a pass."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile

SOURCE = "8275996f2c589a96843e116ac6f2c1d194ef3d2b"
RUN = 41713496978
ROOT = Path(__file__).resolve().parent
PACKAGES = ["codex-utils-path", "codex-hepta-contracts", "codex-hepta-prompt-registry", "codex-hepta-agentd"]
TARGETS = ["//codex-rs/utils/path-utils:path-utils-unit-tests",
           "//codex-rs/hepta-contracts:hepta-contracts-unit-tests",
           "//codex-rs/hepta-prompt-registry:hepta-prompt-registry-unit-tests",
           "//codex-rs/hepta-agentd:hepta-agentd-unit-tests"]
MAC_FAILURES = {
    "cognitive_context::tests::hnmf::changed_hnmf_context_before_publication_fails_closed",
    "cognitive_context::tests::hnmf::current_hnmf_context_filters_owner_candidates_before_delivery",
    "cognitive_context::tests::hnmf::final_use_revalidation_rejects_changed_hnmf_context",
    "cognitive_ranker::tests::running_socket_uses_launch_bound_model_and_isolates_ranker_revocation",
    "control::native_tests::ordinary_control_preserves_server_identity_and_launch_generation",
    "control::native_tests::saturated_ordinary_control_returns_original_overload_and_recovers",
    "state::isolation_tests::current_durable_run_start_requires_live_owner_trust",
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def plain(raw):
    return re.sub(rb"\x1b\[[0-9;]*m", b"", raw).decode("utf-8", errors="replace").replace("\r\n", "\n")


def exact_inputs(repo, names):
    process = subprocess.Popen(["git", "--no-replace-objects", "cat-file", "--batch"],
                               cwd=repo, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    hashes = {}
    total = 0
    try:
        for name in sorted(names):
            process.stdin.write((SOURCE + ":" + name + "\n").encode())
            process.stdin.flush()
            header = process.stdout.readline().split()
            assert len(header) == 3 and header[1] == b"blob", (name, header)
            remaining = int(header[2])
            assert 0 <= remaining < 100_000_000
            total += remaining
            digest = hashlib.sha256()
            while remaining:
                block = process.stdout.read(min(remaining, 65536))
                assert block
                digest.update(block)
                remaining -= len(block)
            assert process.stdout.read(1) == b"\n"
            hashes[name] = digest.hexdigest()
        process.stdin.close()
        assert process.stdout.read() == b"" and process.wait() == 0
    finally:
        process.stdout.close()
        if not process.stdin.closed:
            process.stdin.close()
        process.wait()
    return hashes, total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    artifacts = json.loads((ROOT / "artifact-metadata-8275996.json").read_text())
    assert {row["id"] for row in artifacts} == {13268992702, 13269466844, 13270382017, 13270157656}
    all_files = {}
    receipts = {}
    for row in artifacts:
        assert row["workflow_run"]["head_sha"] == SOURCE and row["workflow_run"]["id"] == RUN
        archive = args.artifacts / str(row["id"]) / "artifact.zip"
        raw = archive.read_bytes()
        assert len(raw) == row["size_in_bytes"] and "sha256:" + sha(raw) == row["digest"]
        with zipfile.ZipFile(archive) as z:
            assert len(z.namelist()) == len(set(z.namelist())) and z.testzip() is None
            assert sum(item.file_size for item in z.infolist()) < 100_000_000
            files = {name: z.read(name) for name in z.namelist() if not name.endswith("/")}
        all_files[row["id"]] = files
        receipts[row["id"]] = json.loads(files["receipt.json"])
    reference = receipts[13270382017]["source_before"]
    actual, total = exact_inputs(args.repo, reference)
    assert len(actual) == 8874
    link_path = "codex-rs/vendor/bubblewrap/LICENSE"
    target_path = "codex-rs/vendor/bubblewrap/COPYING"
    link_mode = subprocess.check_output(["git", "--no-replace-objects", "ls-tree", SOURCE, "--", link_path], cwd=args.repo)
    link_bytes = subprocess.check_output(["git", "--no-replace-objects", "show", SOURCE + ":" + link_path], cwd=args.repo)
    assert link_mode.startswith(b"120000 blob d24842f3cdcf2e447f9a7a26fa387ad63f5c4b91\t") and link_bytes == b"COPYING"
    assert actual[link_path] == "400d38e5cfee181230373a8b02d38f50271a5bf62c62410382efddb8e8b19e22"
    assert actual[target_path] == "b7993225104d90ddd8024fd838faf300bea5e83d91203eab98e29512acebd69c"
    link_representation = {"path": link_path, "git_mode": "120000", "link_bytes": "COPYING",
                           "link_blob_sha256": actual[link_path], "resolved_path": target_path,
                           "observed_resolved_bytes_sha256": actual[target_path]}
    actual[link_path] = actual[target_path]
    assert actual == reference
    summaries = {}
    for identifier, files in all_files.items():
        receipt = receipts[identifier]
        assert receipt["source_commit"] == SOURCE and receipt["source_unchanged"] is True
        assert receipt["source_before"] == receipt["source_after"] == actual
        commands = receipt["commands"]
        assert len({row["name"] for row in commands}) == len(commands)
        command_map = {row["name"]: row for row in commands}
        for row in commands:
            assert sha(files[row["name"] + ".log"]) == row["log_sha256"]
        summary = {"artifact_id": identifier, "receipt_sha256": sha(files["receipt.json"]),
                   "status": receipt["status"], "platform": receipt["platform"],
                   "git_checkout_inputs_verified": len(actual), "exact_git_blob_bytes": len(actual) - 1,
                   "resolved_git_symlinks": [link_representation],
                   "source_before_after_equal_verified_git_checkout": True,
                   "commands": [{"name": row["name"], "exit": row["exit_code"]} for row in commands]}
        if receipt["mode"] == "bazel":
            assert identifier == 13270157656 and receipt["status"] == "passed"
            assert all(row["exit_code"] == 0 for row in commands)
            assert [row["name"] for row in commands] == ["initial-tracked-source", "committed-lock-first", "original-lock-update", "original-lock-check", "original-private-state-targets", "final-tracked-source"]
            assert commands[1]["argv"] == commands[3]["argv"] == ["just", "bazel-lock-check"]
            assert commands[2]["argv"] == ["just", "bazel-lock-update"]
            assert commands[4]["argv"][2:] == ["test", "--nocache_test_results", "--test_output=all", *TARGETS]
            log = plain(files["original-private-state-targets.log"])
            assert "Executed 4 out of 4 tests: 4 tests pass." in log
            for target in TARGETS:
                assert re.search(r"^" + re.escape(target) + r"\s+PASSED in [0-9.]+s$", log, re.MULTILINE)
            committed = subprocess.check_output(["git", "--no-replace-objects", "show", SOURCE + ":MODULE.bazel.lock"], cwd=args.repo)
            assert files["MODULE.bazel.lock"] == committed
            assert receipt["generated_lock"] == {"bytes": len(committed), "sha256": sha(committed), "equals_committed": True}
            summary.update(original_bazel_targets_executed_passed=4, lock_sha256=sha(committed), committed_first_update_check_exit0=True)
        else:
            assert files["rustc-version.log"].startswith(b"rustc 1.96.0 ")
            metadata = gzip.decompress(files["metadata.json.gz"])
            assert receipt["metadata"]["exit_code"] == 0 and sha(metadata) == receipt["metadata"]["sha256"]
            assert len(json.loads(metadata)["packages"]) == receipt["metadata"]["package_count"] == 1517
            if identifier == 13269466844:
                assert receipt["status"] == "failed" and command_map["actual-acquisition-attacks"]["exit_code"] == 1
                original = json.loads(files["acquisition/manifest.json"])
                assert original["source_head"] == SOURCE and original["qualified"] is False and original["restored"] is True
                assert len(original["lanes"]) == 1 and original["lanes"][0]["lane"] == "positive"
                assert original["lanes"][0]["exit_code"] == 0 and sha(files["acquisition/positive.log"]) == original["lanes"][0]["log_sha256"]
                log = plain(files["acquisition/positive.log"])
                assert re.search(r"Summary[^\n]*2 tests run: 2 passed, 15 skipped", log)
                assert "PRIVATE_STATE_ACQUISITION substitution swapped=true denied=true redirected=false" in log
                assert "PRIVATE_STATE_ACQUISITION creation denied=true created=false" in log
                assert "wrong exact test outcomes: {}" in plain(files["actual-acquisition-attacks.log"])
                assert not any(package in command_map for package in PACKAGES)
                summary.update(positive_selected_cases_passed=2, unrelated_cases_filtered=15, mutants_executed=False, full_libraries_executed=False)
            else:
                outcomes = {}
                for package in PACKAGES:
                    row = command_map[package]
                    argv = ["just", "test", "--locked", "-p", package, "--lib", "--no-tests=fail", "--retries", "0", "--success-output=final"]
                    if package == "codex-hepta-agentd":
                        argv += ["--test-threads", "1"]
                    assert row["argv"] == argv
                    tree = ET.fromstring(files[package + ".junit.xml"])
                    cases = tree.findall(".//testcase")
                    names = [case.get("name") for case in cases]
                    assert len(names) == len(set(names)) == int(tree.get("tests"))
                    failed = {case.get("name") for case in cases if case.find("failure") is not None}
                    assert not any(case.find("skipped") is not None or case.find("error") is not None for case in cases)
                    for suite in tree.iter("testsuite"):
                        assert int(suite.get("errors", 0)) == int(suite.get("skipped", 0)) == 0
                    if identifier == 13268992702 and package == "codex-hepta-agentd":
                        assert len(cases) == 173 and failed == MAC_FAILURES and row["exit_code"] == 100
                    else:
                        assert not failed and row["exit_code"] == 0
                        recorded = receipt["tests"][package]
                        assert sorted(names) == recorded["names"] and len(cases) == recorded["count"]
                        assert sha(files[package + ".junit.xml"]) == recorded["sha256"]
                    outcomes[package] = {"total": len(cases), "passed": len(cases) - len(failed), "failed": sorted(failed), "skipped": 0}
                if identifier == 13270382017:
                    assert receipt["status"] == "passed" and sum(item["passed"] for item in outcomes.values()) == 404
                    assert command_map["scoped-clippy-fix"]["exit_code"] == 0
                    dbus = json.loads(files["pinned-dbus-receipt.json"])
                    assert dbus["status"] == "PASS" and len(dbus["commands"]) == 52 and all(row["exit"] == 0 for row in dbus["commands"])
                    assert all(actual["third_party/dbus/" + name] == digest for name, digest in dbus["inputs"].items())
                else:
                    assert receipt["status"] == "failed" and "scoped-clippy-fix" not in command_map
                summary["library_tests"] = outcomes
        summaries[str(identifier)] = summary
        (args.artifacts / str(identifier) / "VERIFIED.json").write_text(json.dumps(summary, indent=2) + "\n")
    result = {"source_commit": SOURCE, "workflow_run": RUN, "verification": "original_mixed_result_evidence_verified",
              "acceptance": "HOLD_NO_GO", "distinct_immutable_git_inputs": len(actual), "git_input_bytes": total,
              "all_four_before_after_maps_match_verified_git_checkout": True,
              "exact_git_blob_bytes": len(actual) - 1, "resolved_git_symlinks": [link_representation],
              "artifacts": summaries,
              "successor_qualification_transferred": False, "archive_content_executed": False}
    (args.artifacts / "VERIFIED.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "artifacts"}, indent=2))


if __name__ == "__main__":
    main()
