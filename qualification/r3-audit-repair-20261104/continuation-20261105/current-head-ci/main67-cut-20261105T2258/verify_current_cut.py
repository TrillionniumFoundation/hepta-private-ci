"""Read-only verification of one frozen main67 CI cut and completed originals.

ZIP members are read directly; no native command, test, network call, or Git
operation is performed by this verifier.
"""

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
import zipfile


HEAD = "67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed"
MERGE = "b7a57dbb61b00e51c05da9cf5c4bc95b365d85ae"
TREE = "3982ba56dc5a3f1da0c1de7ea57992f88125c359"
BASE = Path(__file__).resolve().parent
CASE = re.compile(r"^test (.+?)(?: - should panic)? \.\.\. (ok|FAILED|ignored)(?:,.*)?$", re.M)
SUMMARY = re.compile(r"^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out; finished in ([0-9.]+)s$", re.M)
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def api(path):
    envelope = json.loads(path.read_bytes())
    return envelope, json.loads(envelope["api_content"])


def parse_log(body):
    text = body.decode()
    cases = CASE.findall(text)
    summaries = SUMMARY.findall(text)
    assert cases and summaries
    assert all(status != "FAILED" for _, status in cases)
    assert all(row[0] == "ok" and row[2] == row[4] == "0" for row in summaries)
    by_name = {}
    for name, status in cases:
        assert name not in by_name or by_name[name] == status
        by_name[name] = status
    return {"unique_cases": by_name, "case_occurrences": Counter(name for name, _ in cases), "summaries": summaries}


def successful_xml(data):
    root = ET.fromstring(data)
    assert not any(root.findall(".//" + tag) for tag in ("failure", "error", "skipped", "rerunFailure", "flakyFailure"))
    return root


def verify(base=BASE):
    envelopes = []
    runs_envelope, runs = api(base / "originals/runs.original.json")
    envelopes.append(runs_envelope)
    assert len(runs["workflow_runs"]) == runs["total_count"] == 19
    assert all(row["head_sha"] == HEAD and row["run_attempt"] == 1 and row["head_commit"]["tree_id"] == TREE for row in runs["workflow_runs"])
    jobs = []
    for run in runs["workflow_runs"]:
        envelope, payload = api(base / "originals" / f"jobs-{run['id']}.original.json")
        envelopes.append(envelope)
        assert len(payload["jobs"]) == payload["total_count"]
        assert all(row["head_sha"] == HEAD and row["run_attempt"] == 1 for row in payload["jobs"])
        jobs.extend(payload["jobs"])
    assert len(jobs) == len({row["id"] for row in jobs}) == 53
    job_states = dict(Counter(row["conclusion"] or row["status"] for row in jobs))
    assert job_states == {"queued": 30, "in_progress": 10, "cancelled": 1, "success": 10, "skipped": 2}
    job_map = {row["id"]: row for row in jobs}
    linux_fmt = job_map[127581905245]
    assert linux_fmt["status"] == "queued" and linux_fmt["runner_id"] == 0 and linux_fmt["steps"] == []
    core_job = job_map[127581864284]
    assert core_job["conclusion"] == "success"
    assert all(step["conclusion"] == "success" for step in core_job["steps"])

    for sha in (HEAD, MERGE):
        _, commit = api(base / "originals" / f"commit-{sha}.original.json")
        assert commit["sha"] == sha and commit["tree"]["sha"] == TREE
        parents = [row["sha"] for row in commit["parents"]]
        assert parents == (["eed4d6bb61b789b19f60facc79f9e031765fa4c9"] if sha == HEAD else ["63652be658ebed8d3052eb789b951793384fd5e4", HEAD])

    artifacts = {}
    artifact_rows = []
    api_paths = [base / "core-originals/artifacts-api.original.json", *sorted((base / "other-originals").glob("run-*-artifacts.original.json"))]
    for path in api_paths:
        _, payload = api(path)
        assert payload["total_count"] == len(payload["artifacts"])
        for metadata in payload["artifacts"]:
            artifact_id = metadata["id"]
            assert metadata["workflow_run"]["head_sha"] == HEAD
            archive = path.parent / f"artifact-{artifact_id}.zip"
            raw = archive.read_bytes()
            ident = identity(raw)
            assert metadata["size_in_bytes"] == ident["bytes"] and metadata["digest"] == "sha256:" + ident["sha256"]
            with zipfile.ZipFile(archive) as zipped:
                assert zipped.testzip() is None and len(zipped.namelist()) == len(set(zipped.namelist()))
                members = {row.filename: zipped.read(row) for row in zipped.infolist() if not row.is_dir()}
            artifacts[artifact_id] = members
            artifact_rows.append({"artifact_id": artifact_id, "run_id": metadata["workflow_run"]["id"], "name": metadata["name"], **ident, "members": len(members), "official_digest_and_all_member_CRCs_match": True})
    assert len(artifacts) == 10

    # The complete Core target is represented by exactly eight shard logs. The
    # old unsharded ownership log in the same artifact is not a ninth shard.
    core = artifacts[13459634435]
    source = json.loads(core["source.json"])
    assert source["source_head"] == HEAD and source["source_tree"] == TREE
    assert artifacts[13460219641]["source.json"] == core["source.json"]
    assert artifacts[13460219641]["core-resume.log"] == core["core-resume.log"]
    retained_manifest = json.loads(core["native-test-logs.json"])
    for row in retained_manifest:
        body = core["native-test-logs/" + row["path"]]
        assert len(body) == row["bytes"] and hashlib.sha256(body).hexdigest() == row["sha256"]
    shard_paths = sorted(path for path in core if re.fullmatch(r"native-test-logs/codex-rs/core/core-unit-tests/shard_[1-8]_of_8/test.log", path))
    assert len(shard_paths) == 8
    roster, occurrences, shards = {}, Counter(), []
    for path in shard_paths:
        result = parse_log(core[path])
        for name, status in result["unique_cases"].items():
            assert name not in roster
            roster[name] = status
        occurrences.update(result["case_occurrences"])
        assert all(sum(map(int, row[1:6])) == 2343 for row in result["summaries"])
        shards.append({"path": path, **identity(core[path]), "unique_case_counts": dict(Counter(result["unique_cases"].values())), "libtest_summaries": result["summaries"]})
    assert len(roster) == 2343 and Counter(roster.values()) == {"ok": 2340, "ignored": 3}
    child_case = "environment_selection::tests::blocking_snapshot_waits_for_starting_environment"
    duplicates = {name: count for name, count in occurrences.items() if count != 1}
    assert duplicates == {child_case: 2}
    all_shards = b"\n".join(core[path] for path in shard_paths)
    assert all_shards.count(b"BLOCKING_SNAPSHOT_CHILD: original_body_started") == 1
    assert all_shards.count(b"BLOCKING_SNAPSHOT_CHILD: original_body_passed") == 1
    controls = {}
    for name, expected_count in (("core-resume.log", 4), ("core-fork.log", 1), ("core-ownership.log", 3)):
        parsed = parse_log(core[name])
        assert len(parsed["unique_cases"]) == expected_count and set(parsed["unique_cases"].values()) == {"ok"}
        assert set(parsed["unique_cases"]) <= set(roster)
        assert re.search(rb"^//codex-rs/core:core-unit-tests\s+PASSED in [0-9.]+s$", core[name], re.M)
        assert b"Executed 1 out of 1 test: 1 test passes." in core[name]
        controls[name] = {"cases": list(parsed["unique_cases"]), "unique_passed": expected_count, "extra_owned_child_occurrences": sum(parsed["case_occurrences"].values()) - expected_count, "summaries": parsed["summaries"]}
    unsharded = parse_log(core["native-test-logs/codex-rs/core/core-unit-tests/test.log"])
    assert unsharded["unique_cases"] == parse_log(core["core-ownership.log"])["unique_cases"]
    full_console = core["core-unit-target.log"]
    assert re.search(rb"^//codex-rs/core:core-unit-tests\s+PASSED in [0-9.]+s$", full_console, re.M)
    assert b"Executed 1 out of 1 test: 1 test passes." in full_console

    scopes = []
    for artifact_id in (13460796017, 13460661166):
        members = artifacts[artifact_id]
        source = json.loads(members["ordinary-consumers/source.json"])
        expected_head = HEAD if artifact_id == 13460796017 else MERGE
        assert source["head"] == expected_head and source["tree"] == TREE
        result = json.loads(members["ordinary-consumers/result.json"])
        assert result["exit_code"] == 0 and result["unchanged_inputs"]
        assert "--nocache_test_results" in result["command"] and "--flaky_test_attempts=1" in result["command"]
        target_results = {}
        for target, expected_count in (("hepta-intelligence", 78), ("hepta-bao-adapter", 19), ("hepta-codex-adapter", 21)):
            stem = f"ordinary-consumers/native-test-logs/codex-rs/{target}/{target}-unit-tests/test"
            parsed = parse_log(members[stem + ".log"])
            assert len(parsed["unique_cases"]) == expected_count and set(parsed["unique_cases"].values()) == {"ok"}
            xml = successful_xml(members[stem + ".xml"])
            assert len(xml.findall(".//testcase")) == 1 and xml.findtext(".//system-out") == members[stem + ".log"].decode()
            target_results[target] = expected_count
        scopes.append({"scope": "original Windows business libraries", "artifact_id": artifact_id, "actual_head": expected_head, "tree": TREE, "passed_by_target": target_results, "original_retry_cache_flags_preserved": True, "XML_systemout_equals_each_complete_raw_log": True})

    for artifact_id in (13461041455, 13459374806):
        members = artifacts[artifact_id]
        source = json.loads(members["bazel-process-evidence/source.json"])
        expected_head = HEAD if artifact_id == 13461041455 else MERGE
        assert source["head"] == expected_head and source["tree"] == TREE
        results = {}
        for target, count in (("git-utils-unit-tests", 35), ("queue-queue_service-test", 36)):
            prefix = "bazel-process-evidence/" + target + "-test"
            parsed = parse_log(members[prefix + ".log"])
            assert len(parsed["unique_cases"]) == count and set(parsed["unique_cases"].values()) == {"ok"}
            xml = successful_xml(members[prefix + ".xml"])
            assert len(xml.findall(".//testcase")) == 1 and xml.findtext(".//system-out") == members[prefix + ".log"].decode()
            duplicates = {name: n for name, n in parsed["case_occurrences"].items() if n > 1}
            assert duplicates == ({"info::tests::git_metadata_commands_do_not_inherit_stdin": 2} if count == 35 else {})
            results[target] = {"unique_passed": count, "owned_child_duplicate_rows": duplicates}
        scopes.append({"scope": "original Windows Git and queue controls", "artifact_id": artifact_id, "actual_head": expected_head, "tree": TREE, "targets": results, "XML_systemout_equals_each_complete_raw_log": True})

    retained = artifacts[13460941149]
    source = json.loads(retained["source.json"])
    assert source["source_head"] == HEAD and source["source_tree"] == TREE
    command = json.loads(retained["result.json"])
    assert command["command"] == ["just", "test", "--locked", "-p", "codex-utils-path", "-p", "codex-state", "-p", "codex-hepta-memory", "--lib", "--no-capture", "--retries", "0"]
    assert command["returncode"] == 0 and command["log_bytes"] == len(retained["native-library.log"])
    assert command["log_sha256"] == hashlib.sha256(retained["native-library.log"]).hexdigest()
    xml = successful_xml(retained["junit-0.xml"])
    suites = {suite.attrib["name"]: int(suite.attrib["tests"]) for suite in xml.findall(".//testsuite")}
    assert suites == {"codex-hepta-memory": 299, "codex-state": 209, "codex-utils-path": 24}
    assert len(xml.findall(".//testcase")) == int(xml.attrib["tests"]) == 532
    clean = ANSI.sub("", retained["native-library.log"].decode())
    assert "532 tests run: 532 passed, 7 skipped" in clean
    scopes.append({"scope": "original Windows retained recovery libraries", "artifact_id": 13460941149, "actual_head": HEAD, "tree": TREE, "executed_passed": 532, "passed_by_package": suites, "raw_reported_skipped_not_counted_as_pass": 7, "original_command": command["command"], "skipped_case_names_not_in_this_JUnit": True})

    operator = artifacts[13459303585]
    assert operator["source.txt"].decode().splitlines() == [HEAD, TREE]
    xml = successful_xml(operator["junit.xml"])
    assert len(xml.findall(".//testcase")) == 40 and xml.attrib["tests"] == "40"
    assert "40 tests run: 40 passed, 0 skipped" in ANSI.sub("", operator["tests.log"].decode())
    scopes.append({"scope": "original Windows operator controls", "artifact_id": 13459303585, "actual_head": HEAD, "tree": TREE, "executed_passed": 40, "JUnit_raw_summary_agree": True})

    operator = artifacts[13459049091]
    source = json.loads(operator["operator-bazel/source.json"])
    assert source["head"] == HEAD and source["tree"] == TREE and source["target_triple"] == "x86_64-apple-darwin"
    parsed = parse_log(operator["operator-bazel/test.log"])
    assert len(parsed["unique_cases"]) == 33 and set(parsed["unique_cases"].values()) == {"ok"}
    xml = successful_xml(operator["operator-bazel/test.xml"])
    original = operator["operator-bazel/test.log"].decode()
    systemout = xml.findtext(".//system-out")
    prefix = "\nGenerated test.log (if the file is not UTF-8, then this may be unreadable):\n"
    assert systemout.startswith(prefix) and systemout[len(prefix):].rstrip() == original.rstrip()
    scopes.append({"scope": "original native macOS x86_64 operator Bazel target", "artifact_id": 13459049091, "actual_head": HEAD, "tree": TREE, "executed_passed": 33, "XML_outer_success": True, "XML_raw_relation": "Original XML adds its displayed Generated test.log prefix and trailing whitespace; all other log text equals the complete retained raw log."})

    keyring = artifacts[13460316261]
    assert len(keyring) == 1 and next(iter(keyring.values())) == b""
    report = {
        "schema": "main67-bounded-original-CI-cut-and-terminal-evidence-v1",
        "head": HEAD, "tree": TREE,
        "observed_utc_range": [min(row["requested_utc"] for row in envelopes), max(row["observed_utc"] for row in envelopes)],
        "original_complete_run_job_API_responses": len(envelopes),
        "runs": 19, "run_states": dict(Counter(row["conclusion"] or row["status"] for row in runs["workflow_runs"])),
        "jobs": 53, "job_states": job_states, "actual_failed_jobs": [],
        "API_state_not_case_qualification": True, "snapshot_not_atomic": True,
        "canonical_full_workspace_fmt": {"job_id": 127581905245, "run_id": 42123581479, "status": "queued", "runner_id": 0, "steps": [], "qualified": False},
        "Windows_Supervisor": {"job_id": 127581904781, "status": "in_progress", "qualified": False},
        "Core": {"run_id": 42123569750, "job_id": 127581864284, "completed_at": core_job["completed_at"], "actual_head": HEAD, "actual_tree": TREE, "full_native_shards": 8, "unique_compiled_case_names": 2343, "unique_passed": 2340, "failed": 0, "ignored": [name for name, status in roster.items() if status == "ignored"], "owned_child_additional_PASS_row": child_case, "separate_controls": controls, "shards": shards, "stale_unsharded_log": "Exact earlier three-case ownership scope; retained as original evidence and excluded from full-target shard counts.", "XML_or_compact_execution_log_in_Core_artifact": False},
        "other_original_terminal_scopes": scopes,
        "keyring_diagnostic": {"job_id": 127581904534, "artifact_id": 13460316261, "empty_lock_diff": True, "security_product_qualification": False},
        "artifacts": artifact_rows,
        "scope_limits": ["All named results are bound to current67 or its actual b7a57dbb merge tree, never transferred from parent eed.", "This is one bounded read-only cut. No rerun, dispatch, cancellation, source mutation or native resource query occurred.", "No assertion of whole-repository or full workspace qualification; the Linux canonical format job remained unstarted at this cut.", "Core artifacts preserve complete raw shard logs but no XML or compact execution log. Runtime early-return behavior of every passing test was not separately audited.", "Bazel compact execution originals for other scopes are retained losslessly but were not decoded in this bounded pass; no new per-action environment or cache/placement proof is claimed.", "API successes, diagnostic-only Cargo work, ignored/skipped cases and duplicate child outputs do not become additional product passes."]
    }
    return report


if __name__ == "__main__":
    print(json.dumps(verify(Path(sys.argv[1]) if len(sys.argv) > 1 else BASE), ensure_ascii=False, indent=2))
