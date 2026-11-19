#!/usr/bin/env python3
"""Read-only reconstruction of one cancelled original Windows-current attempt."""
import collections
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
HEAD = "9bd2f589debdba4a93baa363817c3669cb103721"
TREE = "c77785ecb368c44ea699769001a47402c9f50591"
ZIP_SHA = "93d6c384d7f2d804124825e90b90b81d33a8634456d2b06e5f9b78dc8b535898"
RAW_SHA = "9aa9dd6d0adba6b7639e8bc6295f54d2f8608f329acd975fd0a611891d21c8e6"
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
TERM = re.compile(
    r"^\s*(PASS|FAIL|TIMEOUT|EXECFAIL|LEAK|SKIP)\s+\[[^\]\n]+\]\s+"
    r"(?:\(\s*\d+/\d+\)\s+)?(\S+)\s+(\S+)\s*$", re.MULTILINE
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def verify():
    index = json.loads((ROOT / "SOURCE_INDEX.json").read_text())
    assert index["head"] == HEAD and index["tree"] == TREE
    for pin in index["files"]:
        data = (ROOT / "source" / pin["path"]).read_bytes()
        assert (len(data), sha(data), blob(data)) == (
            pin["bytes"], pin["sha256"], pin["git_blob"]
        ), pin["path"]
    scope = json.loads((ROOT / "source/.github/fixtures/windows-current-ci-scope.json").read_text())
    assert len(scope["groups"]) == 19
    expected_ids = [(g["package"], n) for g in scope["groups"] for n in g["requiredTests"]]
    assert len(expected_ids) == len(set(expected_ids)) == 167
    raw_bytes = (ROOT / "job-130526720080-decoded.log").read_bytes()
    assert len(raw_bytes) == 152256 and sha(raw_bytes) == RAW_SHA
    raw = raw_bytes.decode("utf-8-sig")
    assert "Ran 9 tests in 0.100s" in raw
    assert "The operation was canceled." in raw and "KeyboardInterrupt" in raw
    zip_bytes = (ROOT / "ORIGINAL_ARTIFACT.zip").read_bytes()
    assert len(zip_bytes) == 108223 and sha(zip_bytes) == ZIP_SHA
    metadata = json.loads((ROOT / "ARTIFACT_METADATA.json").read_text())
    assert metadata["id"] == 13858954851
    assert metadata["workflow_run"]["id"] == 43021840561
    assert metadata["workflow_run"]["head_sha"] == HEAD
    assert metadata["digest"] == "sha256:" + ZIP_SHA
    job_response = json.loads((ROOT / "TERMINAL_JOBS.json").read_text())
    jobs = job_response["structuredContent"]["jobs"]
    assert len(jobs) == 1
    job = jobs[0]
    assert job["id"] == 130526720080 and job["run_id"] == 43021840561
    assert (job["status"], job["conclusion"]) == ("completed", "cancelled")
    z = zipfile.ZipFile(ROOT / "ORIGINAL_ARTIFACT.zip")
    assert z.testzip() is None
    names = z.namelist()
    assert len(names) == len(set(names)) == 20
    members = []
    for name in names:
        path = PurePosixPath(name)
        assert not path.is_absolute() and ".." not in path.parts
        data = z.read(name)
        members.append({"path": name, "bytes": len(data), "sha256": sha(data)})
    before = json.loads(z.read("source-before.json"))
    assert before["head"] == HEAD and before["tree"] == TREE
    assert before["trackedChanges"] == ""
    assert before["cargoLockSha256"] == "564bc3f207a9f15cd66b0a18a81e4146522deb43c7cf8e90fc2f3d4d6638fd9b"
    assert "receipt.json" not in names and "source-after.json" not in names
    helper = json.loads(z.read("sandbox-helper-preparation.json"))
    assert helper["exitCode"] == 0 and helper["passed"] is True
    assert sorted(a["name"] for a in helper["artifacts"]) == ["codex-command-runner", "codex-windows-sandbox-setup"]
    groups = json.loads(z.read("groups.json"))
    assert [g["id"] for g in groups] == [g["id"] for g in scope["groups"][:13]]
    result_groups, case_ids, uuids = [], set(), set()
    totals = collections.Counter()
    for original, recorded in zip(scope["groups"], groups, strict=False):
        gid = original["id"]
        data = z.read(gid + ".log")
        text = ANSI.sub("", data.decode())
        starts = re.findall(r"^\s*Starting (\d+) tests? across 1 binary(?: \((\d+) tests? skipped\))?\s*$", text, re.MULTILINE)
        assert len(starts) == 1, gid
        summaries = re.findall(r"^\s*Summary \[[^\]\n]+\] (\d+) tests? run: .*, (\d+) skipped\s*$", text, re.MULTILINE)
        assert len(summaries) == 1, gid
        selected, skipped = map(int, summaries[0])
        assert selected == int(starts[0][0])
        assert not starts[0][1] or skipped == int(starts[0][1])
        run_ids = re.findall(r"Nextest run ID ([a-f0-9-]{36}) with nextest profile: local", text)
        assert len(run_ids) == 1 and run_ids[0] not in uuids, gid
        uuids.add(run_ids[0])
        cases = {}
        duplicate_rows = 0
        for status, package, name in TERM.findall(text):
            assert status != "SKIP", (gid, name)
            assert package == original["package"]
            if name in cases:
                assert cases[name] == status, (gid, name, "conflicting terminal rows")
                duplicate_rows += 1
            cases[name] = status
        assert set(cases) == set(original["requiredTests"]), gid
        assert selected == len(cases) == original["expectedTestCount"]
        assert recorded["selectedTestCount"] == recorded["expectedTestCount"] == selected
        assert recorded["observedTests"] == sorted(cases)
        failures = sorted(n for n, s in cases.items() if s != "PASS")
        assert recorded["nonPassingTests"] == failures and recorded["missingRequiredTests"] == []
        assert recorded["selectionMatches"] is True
        assert recorded["passed"] == (recorded["exitCode"] == 0 and not failures)
        command = ["just", "test", "--locked", "-p", original["package"], "--lib", "--cargo-profile", "dev-small", "-E", original["filter"], "--test-threads", "1", "--no-tests", "fail", "--retries", "0"]
        assert recorded["command"] == command
        for name in cases:
            key = (original["package"], name)
            assert key not in case_ids
            case_ids.add(key)
        counts = collections.Counter(cases.values())
        totals.update(counts)
        result_groups.append({"id": gid, "package": original["package"], "nextest_run_id": run_ids[0], "selected": selected, "skipped": skipped, "exit_code": recorded["exitCode"], "strict_pass": recorded["passed"], "counts": dict(counts), "cases": cases, "reprinted_terminal_rows_not_additional_executions": duplicate_rows, "raw_bytes": len(data), "raw_sha256": sha(data), "duration_seconds_includes_compile": recorded["durationSeconds"]})
    assert dict(totals) == {"PASS": 122, "LEAK": 1, "FAIL": 1}
    assert sum(g["strict_pass"] for g in result_groups) == 11
    partial_name = scope["groups"][13]["id"] + ".log"
    partial = z.read(partial_name).decode()
    assert "KeyboardInterrupt" in partial
    assert not re.search(r"Starting \d+ tests? across|Nextest run ID", partial)
    assert not TERM.findall(ANSI.sub("", partial))
    assert all(g["id"] + ".log" not in names for g in scope["groups"][14:])
    unfinished = [{"id": g["id"], "required_cases": g["requiredTests"], "expected": g["expectedTestCount"], "state": "compilation_interrupted_no_test_start" if i == 13 else "not_started"} for i, g in enumerate(scope["groups"]) if i >= 13]
    assert sum(g["expected"] for g in unfinished) == 43
    delete_text = z.read("sandbox-native-delete-routes.log").decode()
    outcomes = {}
    for label in ["ordinary-host-cmd-done", "elevated-child-done"]:
        rows = re.findall(r"delete_matrix " + label + r" after_release=(.+)", delete_text)
        assert len(rows) == 1
        cells = re.findall(r"route: (\w+), file_deleted: (true|false), directory_deleted: (true|false)", rows[0])
        assert cells == [("Neither", "false", "false"), ("TargetOnly", "true", "true"), ("ParentOnly", "true", "true"), ("Both", "true", "true")]
        outcomes[label] = [{"route": route, "file_deleted": file == "true", "directory_deleted": directory == "true"} for route, file, directory in cells]
    return {"schema": "mem.windows-current-original-audit.v1", "run_id": 43021840561, "attempt": 1, "job_id": 130526720080, "source_before": before, "final_source_state": "UNOBSERVED_NO_FINAL_RECEIPT", "job_conclusion": "cancelled", "cancellation_scheduler_cause": "UNKNOWN; timing is compatible with the configured 65-minute job budget but the original record does not identify the scheduler reason", "artifact_id": 13858954851, "artifact_sha256": ZIP_SHA, "raw_sha256": RAW_SHA, "members": members, "scope_groups": 19, "scope_cases": 167, "completed_groups": 13, "strict_passing_groups": 11, "selected_distinct_cases": 124, "strict_terminal_counts": dict(totals), "groups": result_groups, "uncompleted_cases": 43, "uncompleted_groups": unfinished, "outside_delete_original_outcomes": outcomes, "helper_preparation": helper, "new_three_hardlink_helper_cases_included": False, "ordinary_control_candidate_included": False, "new_executions_by_this_audit": 0, "software_tests_are_memory_benefit_evidence": False}


if __name__ == "__main__":
    json.dump(verify(), sys.stdout, ensure_ascii=False, indent=2)
    print()
