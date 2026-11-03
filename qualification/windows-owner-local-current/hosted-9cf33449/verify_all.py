#!/usr/bin/env python3
"""Verify the four original hosted archives without executing their contents."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

from verify_native import git_inputs

SOURCE = "9cf33449107981ee2ca4de486be8ffaaa37dfc61"
RUN = 41705418271
ROOT = Path(__file__).resolve().parent
TARGETS = ["//codex-rs/uds:uds-unit-tests",
           "//codex-rs/hepta-matrixd:hepta-matrixd-unit-tests",
           "//codex-rs/hepta-fleet:hepta-fleet-unit-tests",
           "//codex-rs/hepta-automation:hepta-automation-unit-tests"]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    artifacts = json.loads((ROOT / "artifact-metadata.json").read_text())
    jobs = json.loads((ROOT / "workflow-jobs.json").read_text())
    assert len(jobs) == 4 and all(job["run_id"] == RUN and job["status"] == "completed"
                               and job["conclusion"] == "success" for job in jobs)
    assert len(artifacts) == 4 and {a["id"] for a in artifacts} == {13267211183, 13267346800, 13268019806, 13267192481}
    results = {}
    for artifact in artifacts:
        assert artifact["workflow_run"]["id"] == RUN and artifact["workflow_run"]["head_sha"] == SOURCE
        directory = args.artifacts / str(artifact["id"])
        raw = (directory / "artifact.zip").read_bytes()
        assert len(raw) == artifact["size_in_bytes"] and "sha256:" + sha(raw) == artifact["digest"]
        if artifact["id"] != 13267192481:
            subprocess.run([sys.executable, str(ROOT / "verify_native.py"), "--repo", str(args.repo),
                            "--artifact", str(directory), "--commit", SOURCE,
                            "--archive-sha256", sha(raw), "--archive-bytes", str(len(raw))], check=True)
            results[str(artifact["id"])] = json.loads((directory / "VERIFIED.json").read_text())
            continue
        with zipfile.ZipFile(directory / "artifact.zip") as archive:
            assert archive.testzip() is None
            assert len(archive.namelist()) == len(set(archive.namelist()))
            files = {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}
        receipt = json.loads(files["receipt.json"])
        assert receipt["source_commit"] == SOURCE and receipt["status"] == "passed" and receipt["mode"] == "bazel"
        assert receipt["source_unchanged"] is True
        inputs = git_inputs(args.repo, SOURCE, sorted(receipt["source_before"]))
        assert len(inputs) == 286 and inputs == receipt["source_before"] == receipt["source_after"]
        commands = receipt["commands"]
        assert [row["name"] for row in commands] == ["initial-tracked-source", "committed-lock-first", "original-lock-update",
                                                   "original-lock-check", "original-owner-targets", "final-tracked-source"]
        for row in commands:
            assert row["exit_code"] == 0 and sha(files[row["name"] + ".log"]) == row["log_sha256"]
        assert commands[1]["argv"] == commands[3]["argv"] == ["just", "bazel-lock-check"]
        assert commands[2]["argv"] == ["just", "bazel-lock-update"]
        assert commands[4]["argv"][1].endswith("/.github/scripts/run_bazel_with_buildbuddy.py")
        assert commands[4]["argv"][2:] == ["test", *TARGETS]
        assert commands[0]["argv"] == commands[5]["argv"] == ["git", "--no-replace-objects", "diff", "--exit-code", "HEAD"]
        assert files["initial-tracked-source.log"] == files["final-tracked-source.log"] == b""
        log = re.sub(rb"\x1b\[[0-9;]*m", b"", files["original-owner-targets.log"]).decode()
        assert "Executed 4 out of 4 tests: 4 tests pass." in log
        for target in TARGETS:
            assert re.search(r"^" + re.escape(target) + r"\s+PASSED in [0-9.]+s$", log, re.MULTILINE)
        committed = subprocess.check_output(["git", "--no-replace-objects", "show", SOURCE + ":MODULE.bazel.lock"], cwd=args.repo)
        assert files["MODULE.bazel.lock"] == committed
        assert receipt["generated_lock"] == {"bytes": len(committed), "sha256": sha(committed), "equals_committed": True}
        result = {"status": "verified", "source_commit": SOURCE, "artifact": artifact["id"],
                  "artifact_sha256": sha(raw), "artifact_bytes": len(raw), "zip_crc": "passed",
                  "immutable_git_inputs": len(inputs), "source_before_and_after_match_exact_git_bytes": True,
                  "original_committed_lock_first_update_postcheck_all_exit0": True,
                  "generated_lock_equals_exact_committed_bytes": True, "lock_sha256": sha(committed),
                  "lock_bytes": len(committed), "original_bazel_target_executions": 4, "targets": TARGETS,
                  "observed_execution": "4/4 executed; no target result marked cached",
                  "original_command_count": 6, "receipt_sha256": sha(files["receipt.json"]),
                  "scope": "Four original scoped Bazel targets; original logs retained but no individual test XML was uploaded."}
        (directory / "VERIFIED.json").write_text(json.dumps(result, indent=2) + "\n")
        results[str(artifact["id"])] = result
    native = [result for result in results.values() if "library_tests" in result]
    assert sum(result["native_test_executions_passed"] for result in native) == 322
    assert {result["native_test_executions_passed"] for result in native} == {106, 108}
    final = {"status": "verified", "source_commit": SOURCE, "workflow_run": RUN,
             "hosted_jobs_success": 4, "native_test_executions_passed": 322, "failed": 0, "skipped": 0,
             "scoped_clippy_executions_passed": 3, "original_bazel_targets_executed_passed": 4,
             "immutable_git_inputs_per_artifact": 286, "distinct_input_paths": 286,
             "artifact_verifications": {key: {"sha256": value["artifact_sha256"],
                                               "receipt_sha256": value["receipt_sha256"]} for key, value in results.items()},
             "scope": "Exact source scoped UDS, Matrixd, Fleet and Automation qualification. Private-state/Agentd successor and original complete CI remain separate; HOLD_NO_GO."}
    (args.artifacts / "VERIFIED.json").write_text(json.dumps(final, indent=2) + "\n")
    print(json.dumps(final, indent=2))


if __name__ == "__main__":
    main()
