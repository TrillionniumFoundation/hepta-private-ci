#!/usr/bin/env python3
"""Audit only retained bytes from d0f's one original Windows-current attempt."""
import collections
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
HEAD = "d0f6507e08f7f5c5855f5164d07c049a34d1a6d9"
TREE = "658fa040046285116b1fd81b94ff8c96444072ad"
RUN = 43062473110
JOB = 130668436858
SCOPE_BLOB = "72f75127e9f92236def02a67a099fd90bb2a9b09"
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
TERM = re.compile(r"^\s*(PASS|FAIL|TIMEOUT|EXECFAIL|LEAK|SKIP)\s+\[[^\]\n]+\]\s+(?:\(\s*\d+/\d+\)\s+)?(\S+)\s+(\S+)\s*$", re.MULTILINE)


def pin(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def payload(value):
    if "structuredContent" in value:
        return json.loads(value["structuredContent"]["content"])
    return value


def verify(directory):
    frozen = json.loads((directory / "ORIGINAL_BYTE_PINS.json").read_bytes())
    assert frozen["run_id"] == RUN and frozen["job_id"] == JOB and frozen["head"] == HEAD
    for row in frozen["files"]:
        p = PurePosixPath(row["path"])
        assert not p.is_absolute() and ".." not in p.parts
        assert pin((directory / p).read_bytes()) == {k: row[k] for k in ("bytes", "sha256", "git_blob")}
    scope_raw = (directory / "source/.github/fixtures/windows-current-ci-scope.json").read_bytes()
    assert pin(scope_raw)["git_blob"] == SCOPE_BLOB
    scope = json.loads(scope_raw)["groups"]
    assert len(scope) == 19
    all_ids = {(g["package"], case) for g in scope for case in g["requiredTests"]}
    assert len(all_ids) == sum(g["expectedTestCount"] for g in scope) == 167
    jobs = payload(json.loads((directory / "TERMINAL_JOBS.json").read_bytes()))["jobs"]
    assert len(jobs) == 1 and jobs[0]["id"] == JOB and jobs[0]["run_id"] == RUN
    job = jobs[0]
    assert job["head_sha"] == HEAD and job["run_attempt"] == 1
    assert job["head_branch"] == "codex/mem8-integrated-source-20261111-ed353817"
    assert job["status"] == "completed" and job["conclusion"] in ("success", "failure", "cancelled", "timed_out")
    metadata = json.loads((directory / "ARTIFACT_METADATA.json").read_bytes())
    assert metadata["workflow_run"]["id"] == RUN and metadata["workflow_run"]["head_sha"] == HEAD
    zip_data = (directory / "ORIGINAL_ARTIFACT.zip").read_bytes()
    assert len(zip_data) == metadata["size_in_bytes"]
    assert "sha256:" + pin(zip_data)["sha256"] == metadata["digest"]
    archive = zipfile.ZipFile(directory / "ORIGINAL_ARTIFACT.zip")
    assert archive.testzip() is None
    names = archive.namelist()
    assert len(names) == len(set(names))
    members = []
    for name in names:
        p = PurePosixPath(name)
        assert not p.is_absolute() and ".." not in p.parts and not name.endswith("/")
        assert (archive.getinfo(name).external_attr >> 16) & 0o170000 != 0o120000
        members.append({"path": name, **pin(archive.read(name))})
    before = json.loads(archive.read("source-before.json"))
    assert before["head"] == HEAD and before["tree"] == TREE and before["trackedChanges"] == ""
    for path, expected in {
        ".github/workflows/hepta-windows-current-ci.yml": "d9dc4986a86a6d29e51203e34b7cc3e4f08c536b",
        ".github/scripts/windows_current_ci.py": "161ed1149c8ffb5f2bb2a8272f555f8b91d729fe",
    }.items():
        assert pin((directory / "source" / path).read_bytes())["git_blob"] == expected
    preparation = json.loads(archive.read("sandbox-helper-preparation.json"))
    assert preparation["command"] == ["cargo", "build", "--locked", "-p", "codex-windows-sandbox", "--profile", "dev-small", "--message-format=json", "--bin", "codex-windows-sandbox-setup", "--bin", "codex-command-runner"]
    assert preparation["exitCode"] == 0 and preparation["passed"] is True
    assert {a["name"] for a in preparation["artifacts"]} == {"codex-windows-sandbox-setup", "codex-command-runner"}
    assert all(a["bytes"] > 0 and re.fullmatch(r"[0-9a-f]{64}", a["sha256"]) for a in preparation["artifacts"])
    assert archive.read("compiler.txt").startswith(b"rustc 1.96.0 ")
    groups = json.loads(archive.read("groups.json")) if "groups.json" in names else []
    assert [g["id"] for g in groups] == [g["id"] for g in scope[:len(groups)]]
    recorded_by_id = {g["id"]: g for g in groups}
    assert len(recorded_by_id) == len(groups)
    uuids, observed_ids = set(), set()
    totals = collections.Counter()
    audited = []
    for index, declared in enumerate(scope):
        gid = declared["id"]
        name = gid + ".log"
        if name not in names:
            assert gid not in recorded_by_id
            audited.append({"id": gid, "state": "not_started_no_original_log", "declared_cases": declared["expectedTestCount"]})
            continue
        data = archive.read(name)
        text = ANSI.sub("", data.decode())
        starts = re.findall(r"^\s*Starting (\d+) tests? across (\d+) binar(?:y|ies)(?: \((\d+) tests? skipped\))?\s*$", text, re.MULTILINE)
        run_ids = re.findall(r"Nextest run ID ([a-f0-9-]{36}) with nextest profile: local", text)
        assert len(starts) <= 1 and len(run_ids) <= 1
        for uuid in run_ids:
            assert uuid not in uuids
            uuids.add(uuid)
        cases = {}
        repeats = 0
        for outcome, package, case in TERM.findall(text):
            assert package == declared["package"] and case in declared["requiredTests"]
            assert outcome != "SKIP", "declared selected regression unexpectedly skipped"
            if case in cases:
                assert cases[case] == outcome
                repeats += 1
            cases[case] = outcome
        for case in cases:
            key = (declared["package"], case)
            assert key not in observed_ids
            observed_ids.add(key)
        counts = collections.Counter(cases.values())
        totals.update(counts)
        record = {"id": gid, "package": declared["package"], "raw": pin(data),
                  "nextest_run_ids": run_ids, "start_headers": starts,
                  "declared_cases": declared["expectedTestCount"], "terminal_counts": dict(counts),
                  "terminal_cases": cases, "duplicate_summary_terminal_rows": repeats,
                  "missing_original_terminal_ids": sorted(set(declared["requiredTests"]) - set(cases))}
        if gid not in recorded_by_id:
            assert index == len(groups), "more than one partial unreceipted group"
            record["state"] = "partial_log_without_final_group_receipt"
            record["strict_pass"] = False
            audited.append(record)
            continue
        recorded = recorded_by_id[gid]
        argv = ["just", "test", "--locked", "-p", declared["package"], "--lib", "--cargo-profile", "dev-small", "-E", declared["filter"], "--test-threads", "1", "--no-tests", "fail", "--retries", "0"]
        assert recorded["command"] == argv
        if not starts:
            assert not run_ids and not cases
            assert recorded["selectedTestCount"] is None and recorded["observedTests"] == []
            assert recorded["missingRequiredTests"] == sorted(declared["requiredTests"])
            assert recorded["selectionMatches"] is False and recorded["passed"] is False
            record.update(state="command_finished_without_original_test_start", exit_code=recorded["exitCode"],
                          strict_pass=False, duration_seconds_includes_compile=recorded["durationSeconds"], command=argv)
            audited.append(record)
            continue
        assert len(starts) == len(run_ids) == 1
        selected, binary_count, skipped = starts[0]
        assert binary_count == "1"
        summaries = re.findall(r"^\s*Summary \[[^\]\n]+\] (\d+) tests? run: .*, (\d+) skipped\s*$", text, re.MULTILINE)
        assert len(summaries) == 1 and int(selected) == int(summaries[0][0])
        assert not skipped or int(skipped) == int(summaries[0][1])
        assert set(cases) == set(declared["requiredTests"])
        assert int(selected) == len(cases) == declared["expectedTestCount"]
        assert recorded["selectedTestCount"] == recorded["expectedTestCount"] == len(cases)
        assert recorded["observedTests"] == sorted(cases) and recorded["missingRequiredTests"] == []
        bad = sorted(case for case, outcome in cases.items() if outcome != "PASS")
        assert recorded["nonPassingTests"] == bad and recorded["selectionMatches"] is True
        strict = recorded["exitCode"] == 0 and not bad
        assert recorded["passed"] == strict
        record.update(state="original_completed_group_receipt", skipped=int(summaries[0][1]),
                      exit_code=recorded["exitCode"], strict_pass=strict,
                      duration_seconds_includes_compile=recorded["durationSeconds"], command=argv)
        audited.append(record)
    final = json.loads(archive.read("receipt.json")) if "receipt.json" in names else None
    if final is not None:
        assert final["sourceBefore"] == before and final["groups"] == groups
        assert len(groups) == 19 and final["testRetries"] == 0
        assert final["productionAuthorityGranted"] is False and final["finalProductQualification"] is False
        intact = final["sourceAfter"] == before and not before["trackedChanges"]
        assert final["sourceUnchanged"] == intact
        success = intact and final["sandboxHelperPreparation"]["passed"] and all(g["passed"] for g in groups)
        assert final["status"] == ("PASS_DECLARED_WINDOWS_SCOPE" if success else "FAIL_DECLARED_WINDOWS_SCOPE")
    raw = (directory / "ORIGINAL_JOB.log").read_bytes()
    raw_lines = raw.splitlines(keepends=True)
    preflight_rows = [(i, line) for i, line in enumerate(raw_lines, 1) if b"Ran 9 tests in " in line]
    assert len(preflight_rows) == 1
    preflight_line, preflight_bytes = preflight_rows[0]
    assert any(re.search(rb"Z OK\s*$", line) for line in raw_lines[preflight_line:preflight_line + 3])
    delete_raw = archive.read("sandbox-native-delete-routes.log")
    delete_lines = delete_raw.splitlines(keepends=True)
    observations = []
    for needle in (b"delete_control verified_before_resume", b"ordinary-host-cmd-done after_release=", b"elevated-child-done after_release=", b"elevated_terminal_observation cleanup="):
        matches = [(i, line) for i, line in enumerate(delete_lines, 1) if needle in line]
        assert len(matches) == 1
        number, data = matches[0]
        observations.append({"line": number, "bytes": pin(data), "text": data.decode().rstrip("\r\n")})
    ordinary, elevated = observations[1]["text"], observations[2]["text"]
    route_pattern = r"route: (Neither|TargetOnly|ParentOnly|Both), file_deleted: (true|false), directory_deleted: (true|false)"
    ordinary_routes = re.findall(route_pattern, ordinary)
    elevated_routes = re.findall(route_pattern, elevated)
    expected_observed = [("Neither", "false", "false"), ("TargetOnly", "true", "true"), ("ParentOnly", "true", "true"), ("Both", "true", "true")]
    assert ordinary_routes == elevated_routes == expected_observed
    assert "distinct_token=true backup_present=false restore_present=false other_privileges_unchanged=true" in observations[0]["text"]
    return {"schema": "mem.d0f.windows-current-original-audit.v1", "run_id": RUN, "job_id": JOB,
            "attempt": 1, "head": HEAD, "tree": TREE, "job_conclusion": job["conclusion"],
            "job_started_at": job["started_at"], "job_completed_at": job["completed_at"],
            "raw": pin(raw), "artifact_id": metadata["id"], "archive": pin(zip_data), "members": members,
            "original_scope_groups": 19, "original_scope_cases": 167,
            "completed_group_receipts": len(groups), "strict_passing_groups": sum(g["passed"] for g in groups),
            "terminal_distinct_original_case_ids": len(observed_ids), "terminal_counts": dict(totals),
            "no_observed_terminal_case_count": len(all_ids - observed_ids), "groups": audited,
            "original_final_receipt": final, "source_before": before,
            "sandbox_helper_preparation": preparation,
            "helper_binary_bytes_archived": False,
            "helper_boundary": "original source-pinned driver retained compiler-artifact and PE/hash receipt; actual helper executables are not inside this artifact",
            "source_after_observation": "present_in_original_final_receipt" if final else "UNOBSERVED_NO_FINAL_RECEIPT",
            "python_driver_preflight": {"observed_summary_count": 9, "result": "OK", "summary_line": preflight_line,
                "summary_line_bytes": pin(preflight_bytes), "individual_ids_in_original_raw": "not enumerated by unittest",
                "fixture_fake_nextest_rows": "excluded from Rust counts; Rust cases come only from original per-group logs"},
            "delete_failure_observations": {"original_group_raw": pin(delete_raw), "exact_lines": observations,
                "ordinary_control_routes": ordinary_routes, "elevated_outside_routes": elevated_routes,
                "ordinary_child_privilege_check_is_not_elevated_child_token_inventory": True,
                "elevated_child_token_inventory": "UNOBSERVED", "production_authority_or_global_isolation_claim": False},
            "cancellation_scheduler_cause": "UNKNOWN_UNLESS_ADDITIONAL_ORIGINAL_METADATA_IDENTIFIES_REASON",
            "three_new_hardlink_helpers_in_167_scope": False, "native_or_model_executions_by_auditor": 0,
            "memory_benefit_or_original_owner_recovery_established": False}


if __name__ == "__main__":
    directory = Path(sys.argv[1]).resolve()
    print(json.dumps(verify(directory), indent=2, sort_keys=True))
