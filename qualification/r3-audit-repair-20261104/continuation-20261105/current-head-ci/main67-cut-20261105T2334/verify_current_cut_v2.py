#!/usr/bin/env python3
"""Read-only replay of the frozen 23:34 main67 CI cut and original artifacts.

This verifier performs no network, Git, native execution, or source mutation.
"""
from pathlib import Path, PurePosixPath
import collections
import hashlib
import json
import re
import stat
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parent
HEAD = "67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed"
MERGE = "b7a57dbb61b00e51c05da9cf5c4bc95b365d85ae"
TREE = "3982ba56dc5a3f1da0c1de7ea57992f88125c359"
ORIGINAL = ROOT / "originals"
TERMINAL = ROOT / "terminal-originals"
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
STATUS = re.compile(r"^\s*(PASS|FAIL|SKIP|ABORT|TIMEOUT|LEAK)\s+\[[^\]]*\]\s+(\S+)\s+(.+?)\s*$")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def identity(data):
    return {"bytes": len(data), "sha256": digest(data), "git_blob": hashlib.sha1(
        b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def read_json(path):
    return json.loads(path.read_bytes())


def api(path):
    record = read_json(path)
    return record, json.loads(record["api_content"])


def log_lines(data):
    return [re.sub(r"^\d{4}-\d\d-\d\dT\S+Z\s?", "", ANSI.sub("", line))
            for line in data.decode("utf-8").splitlines()]


def statuses(data):
    rows = [m.groups() for line in log_lines(data) if (m := STATUS.match(line))]
    unique = collections.defaultdict(set)
    for status, binary, name in rows:
        unique[status].add((binary, name))
    return rows, unique


def nextest(data, passed, skipped=0, failed=0):
    rows, unique = statuses(data)
    assert set(unique) <= {"PASS", "SKIP", "FAIL"}
    assert {k: len(v) for k, v in unique.items()} == {
        k: n for k, n in (("PASS", passed), ("SKIP", skipped), ("FAIL", failed)) if n}
    assert not (unique["PASS"] & unique["SKIP"] or unique["PASS"] & unique["FAIL"]
                or unique["SKIP"] & unique["FAIL"])
    summaries = [line.strip() for line in log_lines(data) if re.match(r"\s*Summary \[", line)]
    assert len(summaries) == 1
    summary = summaries[0]
    assert f"{passed + failed} tests run: {passed} passed" in summary
    if failed:
        assert f"{failed} failed" in summary
    if skipped:
        assert f"{skipped} skipped" in summary
    return {"passed": passed, "failed": failed, "skipped": skipped,
            "raw_status_rows": dict(collections.Counter(r[0] for r in rows)),
            "unique_status_names": {k: len(v) for k, v in unique.items() if v},
            "summary": summary, "status_names": unique}


def public_result(result):
    return {k: v for k, v in result.items() if k != "status_names"}


def junit(data, expected):
    root = ET.fromstring(data)
    cases = list(root.iter("testcase"))
    assert int(root.attrib["tests"]) == len(cases) == expected
    assert int(root.attrib.get("failures", "0")) == int(root.attrib.get("errors", "0")) == 0
    keys = {(case.attrib["classname"], case.attrib["name"]) for case in cases}
    assert len(keys) == expected
    assert all(not case.findall("failure") and not case.findall("error")
               and not case.findall("skipped") for case in cases)
    suites = list(root.iter("testsuite"))
    assert sum(int(s.attrib["tests"]) for s in suites) == expected
    assert all(int(s.attrib.get("failures", "0")) == 0
               and int(s.attrib.get("errors", "0")) == 0
               and int(s.attrib.get("disabled", "0")) == 0 for s in suites)
    return keys, {"cases": expected, "failures": 0, "errors": 0, "skipped_elements": 0,
                  "uuid": root.attrib["uuid"], "suites": [s.attrib for s in suites]}


def check_command(command):
    assert command[0:2] == ["just", "test"]
    assert command[command.index("--no-tests") + 1] == "fail"
    assert command[command.index("--retries") + 1] == "0"


run_record, run_api = api(ORIGINAL / "runs.original.json")
runs = run_api["workflow_runs"]
assert run_api["total_count"] == len(runs) == 19
assert all(r["head_sha"] == HEAD and r["run_attempt"] == 1 for r in runs)
records, jobs = [run_record], []
for run in runs:
    record, body = api(ORIGINAL / f"jobs-{run['id']}.original.json")
    assert record["run_id"] == run["id"]
    assert body["total_count"] == len(body["jobs"])
    assert all(j["run_id"] == run["id"] and j["head_sha"] == HEAD
               and j["run_attempt"] == 1 for j in body["jobs"])
    records.append(record)
    jobs.extend(body["jobs"])
assert len(records) == 20 and len(jobs) == len({j["id"] for j in jobs}) == 53
job_by_id = {j["id"]: j for j in jobs}
states = collections.Counter(j["conclusion"] if j["status"] == "completed" else j["status"] for j in jobs)
assert dict(states) == {"queued": 23, "success": 18, "cancelled": 8, "skipped": 2, "in_progress": 2}
assert not any(j["conclusion"] in ("failure", "timed_out", "action_required", "startup_failure") for j in jobs)
source_authority = []
for commit in (HEAD, MERGE):
    record, body = api(ROOT / "prior-originals" / f"commit-{commit}.original.json")
    assert body["sha"] == commit and body["tree"]["sha"] == TREE
    source_authority.append({"commit": commit, "tree": body["tree"]["sha"],
                             "parents": [p["sha"] for p in body["parents"]],
                             "prior_actual_GET_observed_utc": record["observed_utc"]})
assert source_authority[1]["parents"] == ["63652be658ebed8d3052eb789b951793384fd5e4", HEAD]

official_artifacts = {}
for path in sorted(TERMINAL.glob("run-*-artifacts.original.json")):
    record, body = api(path)
    assert body["total_count"] == len(body["artifacts"])
    for artifact in body["artifacts"]:
        assert not artifact["expired"]
        assert artifact["id"] not in official_artifacts
        official_artifacts[artifact["id"]] = (record, artifact)
assert len(official_artifacts) == 7
archives, artifact_report = {}, []
for artifact_id, (record, artifact) in sorted(official_artifacts.items()):
    path = TERMINAL / f"artifact-{artifact_id}.zip"
    data = path.read_bytes()
    assert len(data) == artifact["size_in_bytes"]
    assert "sha256:" + digest(data) == artifact["digest"]
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == len(set(archive.namelist()))
        entries = {}
        members = []
        for info in archive.infolist():
            name = info.filename
            assert "\\" not in name and not PurePosixPath(name).is_absolute()
            assert ".." not in PurePosixPath(name).parts and not stat.S_ISLNK(info.external_attr >> 16)
            assert not info.is_dir()
            member = archive.read(info)
            assert len(member) == info.file_size
            entries[name] = member
            members.append({"name": name, "CRC": info.CRC, **identity(member)})
        archives[artifact_id] = entries
        artifact_report.append({"id": artifact_id, "name": artifact["name"],
                                "run_id": record["run_id"], **identity(data),
                                "official_size_digest_and_CRC_verified": True,
                                "members": members})

readbacks = read_json(TERMINAL / "full-original-readbacks.final.json")
assert len(readbacks["files"]) == 11
raw_logs = {}
log_report = []
for entry in readbacks["files"]:
    path = TERMINAL / Path(entry["path"]).name
    data = path.read_bytes()
    assert len(data.decode("utf-8").encode("utf-16-le")) // 2 == entry["characters"]
    assert entry["complete_tool_body_preserved"] and entry["full_local_string_readback_equal"]
    if entry["kind"] == "log":
        job_id = entry["id"]
        assert job_by_id[job_id]["status"] == "completed" and job_by_id[job_id]["conclusion"] == "success"
        assert entry["newlines_preserved"]
        raw_logs[job_id] = data
        log_report.append({"job_id": job_id, **identity(data), "characters": entry["characters"],
                           "complete_original_tool_text_readback_equal": True,
                           "CRLF_count": data.count(b"\r\n")})
assert len(raw_logs) == 6 and sum(r["characters"] for r in log_report) == 7_085_040

supervisor_keys, supervisor_xml = junit(archives[13461481887]["junit.xml"], 3)
protocol_keys, protocol_xml = junit(archives[13461007387]["junit.xml"], 14)
_, supervisor_status = statuses(raw_logs[127581904781])
assert supervisor_status["PASS"] == supervisor_keys | protocol_keys and set(supervisor_status) == {"PASS"}
expected_supervisor = {
    "unsigned_digest_abort_directive_cannot_clear_signed_production_recovery_fence",
    "unexpected_agent_crashes_back_off_and_stop_after_three_restarts",
    "restart_budget_survives_repeated_supervisord_recovery"}
assert {name for _, name in supervisor_keys} == expected_supervisor
supervisor_steps = {s["name"]: s for s in job_by_id[127581904781]["steps"]}
assert supervisor_steps["Strict Supervisor Clippy"]["conclusion"] == "success"
assert supervisor_steps["Verify Supervisor canonical Rust format on Windows"]["conclusion"] == "success"
assert supervisor_steps["Verify full-workspace canonical Rust format on Linux"]["conclusion"] == "skipped"
assert b"cargo +1.95.0 fmt -p codex-hepta-supervisor -- --check" in raw_logs[127581904781]
linux_supervisor = job_by_id[127581905245]
assert linux_supervisor["status"] == "queued" and linux_supervisor["steps"] == []

owner = archives[13461107605]
assert owner["source.txt"].decode().split() == [HEAD, TREE]
assert b"host: x86_64-pc-windows-msvc" in owner["toolchain.txt"]
owner_results = {}
for package, count in (("uds", 14), ("matrixd", 31), ("agentd", 172)):
    result = nextest(owner[f"{package}.log"], count)
    owner_results[package] = {**public_result(result),
                              "cases": [list(x) for x in sorted(result["status_names"]["PASS"])]}

memory = archives[13461945442]
memory_result = json.loads(memory["native-result.json"])
assert memory_result["source_sha"] == HEAD and memory_result["source_tree"] == TREE
assert memory_result["passed"] == 2
assert not memory_result["full_package_qualification"] and not memory_result["target_hardware_qualification"]
assert not memory_result["production_authorized"]
memory_keys, memory_xml = junit(memory["junit.xml"], 2)
memory_raw = nextest(memory["native.log"], 2, skipped=404)
assert memory_raw["status_names"]["PASS"] == memory_keys
assert {name for _, name in memory_keys} == set(memory_result["required_tests"])
assert memory_xml["uuid"] == memory_result["nextest_uuid"]

recovery_results = []
for artifact_id, commit in ((13463050432, HEAD), (13462565685, MERGE)):
    files = archives[artifact_id]
    source = json.loads(files["source.json"])
    retained = json.loads(files["retained.json"])
    assert source["source"] == commit and source["tree"] == TREE
    assert source["run_id"] == "42123581270" and source["run_attempt"] == "1"
    assert retained["unchanged_inputs"] is True and retained["after"] == source["inputs"]
    scopes = []
    for scope, passed, skipped in (("server", 254, 0), ("rollout", 121, 0), ("resume", 13, 35)):
        receipt = json.loads(files[f"{scope}.json"])
        assert receipt["scope"] == scope and receipt["exit"] == 0 and receipt["valid"] is True
        assert receipt["passed"] == passed and receipt["invalid"] == receipt["missing"] == []
        check_command(receipt["command"])
        assert receipt["log_sha256"] == digest(files[f"{scope}.log"])
        assert receipt["junit_sha256"] == digest(files[f"{scope}-junit.xml"])
        assert receipt == next(x for x in retained["scopes"] if x["scope"] == scope)
        keys, xml = junit(files[f"{scope}-junit.xml"], passed)
        raw = nextest(files[f"{scope}.log"], passed, skipped)
        assert raw["status_names"]["PASS"] == keys
        assert set(receipt["required"]) <= {name for _, name in keys}
        scopes.append({"scope": scope, "command": receipt["command"],
                       **public_result(raw), "JUnit": xml,
                       "required_names": receipt["required"],
                       "manifest_log_JUnit_hashes_verified": True,
                       "raw_unique_PASS_names_equal_JUnit": True,
                       "skip_limit": "Raw SKIP entries are excluded from the successful JUnit cases."})
    recovery_results.append({"artifact_id": artifact_id, "source": commit, "tree": TREE,
                             "unchanged_inputs": True, "scopes": scopes})

private = archives[13460552442]
manifest = json.loads(private["manifest.json"])
assert manifest["source_head"] == HEAD and manifest["source_tree"] == TREE
check_command(manifest["command"])
assert manifest["restored"] is True and manifest["qualified"] is True
assert manifest["production_sha256"] == digest(private["positive.rs"])
expected_failures = {
    "unchecked-create": "private_state_windows::directory::tests::rejects_junction_before_creating_private_leaf",
    "path-check-open": "private_state_windows::directory::tests::rejects_ancestor_substitution_at_retained_open"}
lanes = []
for lane in manifest["lanes"]:
    name = lane["lane"]
    assert lane["production_sha256"] == digest(private[f"{name}.rs"])
    assert lane["log_sha256"] == digest(private[f"{name}.log"])
    if name == "positive":
        assert lane["exit_code"] == 0
        raw = nextest(private[f"{name}.log"], 2, skipped=22)
    else:
        assert name in expected_failures and lane["exit_code"] == 1
        assert lane["patch_sha256"] == digest(private[f"{name}.patch"])
        raw = nextest(private[f"{name}.log"], 1, skipped=22, failed=1)
        assert {case for _, case in raw["status_names"]["FAIL"]} == {expected_failures[name]}
    actual_status = {case: status for status, keys in raw["status_names"].items()
                     if status != "SKIP" for _, case in keys}
    assert actual_status == lane["statuses"]
    for kind, observation in lane["observations"].items():
        assert f"PRIVATE_STATE_ACQUISITION {kind} {observation}" in private[f"{name}.log"].decode()
    lanes.append({"lane": name, "exit_code": lane["exit_code"], **public_result(raw),
                  "statuses": actual_status, "physical_observations": lane["observations"],
                  "complete_source_patch_and_log_hashes_verified": True})
assert {x["lane"] for x in lanes} == {"positive", "unchecked-create", "path-check-open"}
assert manifest["lanes"][0]["observations"] == {"substitution": "swapped=true denied=true redirected=false", "creation": "denied=true created=false"}
assert next(x for x in lanes if x["lane"] == "unchecked-create")["physical_observations"]["creation"] == "denied=true created=true"
assert next(x for x in lanes if x["lane"] == "path-check-open")["physical_observations"]["substitution"] == "swapped=true denied=false redirected=true"
_, private_status = statuses(raw_logs[127581904209])
assert len(private_status["PASS"]) == 53 and set(private_status) == {"PASS"}
private_summaries = [line.strip() for line in log_lines(raw_logs[127581904209])
                     if re.match(r"\s*Summary \[", line)]
assert len(private_summaries) == 6

pty = read_json(ROOT / "prior-originals" / "native10-pty-retention-manifest.original.json")
pty_target = "//codex-rs/utils/pty:pty-unit-tests"
assert pty["source"]["commit"] == "5ce73498a9e8ee843d156c43593b1bc2fede416f"
assert pty["source"]["tree"] == "36ca349de7f4c7c5a2914cf1960a81d8621350fa"
assert pty["retention"]["targets"][pty_target]["status"] == "NOT_REPORTED"
assert pty["retention"]["targets"][pty_target]["collect_existing_logs"] is False
assert pty["files"] == []
assert all(pty_target.encode() not in data for data in raw_logs.values())
fresh_pty_case_names = set()
for data in list(raw_logs.values()) + [data for files in archives.values()
                                      for name, data in files.items() if name.endswith(".log")]:
    rows, _ = statuses(data)
    for _, binary, name in rows:
        if re.search(r"(^|[^a-z0-9])(pty|conpty)($|[^a-z0-9])", binary + " " + name, re.I):
            fresh_pty_case_names.add((binary, name))
assert not fresh_pty_case_names

cancelled = [j for j in jobs if j["conclusion"] == "cancelled"]
assert len(cancelled) == 8 and all(j["runner_id"] == 0 and not j["steps"] for j in cancelled)
result = {
    "schema": "main67-2334-complete-original-review-v1", "head": HEAD, "tree": TREE,
    "observed_utc_range": [min(r["requested_utc"] for r in records), max(r["observed_utc"] for r in records)],
    "complete_run_job_API_responses": 20, "runs": 19, "jobs": 53,
    "run_states": dict(collections.Counter(r["conclusion"] if r["status"] == "completed" else r["status"] for r in runs)),
    "job_states": dict(states), "actual_failed_jobs": 0,
    "API_state_not_case_qualification": True, "snapshot_not_atomic": True,
    "prior_actual_source_authority": source_authority,
    "new_complete_raw_logs": log_report, "new_original_artifacts": artifact_report,
    "canonical_full_workspace_fmt": {"run_id": 42123581479, "job_id": 127581905245,
                                      "status": "queued", "steps": [], "qualified": False},
    "Unix_signal_qualification": "No newly completed original Linux job in this cut; pending Linux scopes are not qualified.",
    "Windows_Supervisor": {"job_id": 127581904781, "supervisor": supervisor_xml, "protocol": protocol_xml,
                            "required_supervisor_cases": sorted(expected_supervisor),
                            "raw_unique_PASS_names_match_both_JUnit_archives": True,
                            "strict_Clippy_step": "success", "fmt_command": "cargo +1.95.0 fmt -p codex-hepta-supervisor -- --check",
                            "fmt_scope": "Supervisor package on Windows only; full-workspace Linux fmt remains queued."},
    "Windows_owner_local": {"job_id": 127581904496, "source": HEAD, "tree": TREE, "packages": owner_results},
    "Windows_Memory": {"job_id": 127581904898, **public_result(memory_raw), "JUnit": memory_xml,
                        "required_cases": memory_result["required_tests"], "full_package_qualification": False},
    "Windows_exec_recovery": recovery_results,
    "Windows_private_state": {"job_id": 127581904209, "original_positive_unique_cases": 53,
                               "original_scope_summaries": private_summaries,
                               "acquisition_lanes": lanes, "manifest_restored": True,
                               "negative_exit_1_is_expected": True,
                               "limit": "The acquisition positive controls overlap the original 19 path cases; do not add them as new unique product cases."},
    "PTY": {"new_original_target_qualification": False, "fresh_explicit_PTY_case_names": [],
            "prior_native10_manifest_source": pty["source"],
            "prior_native10_target_entry": pty["retention"]["targets"][pty_target],
            "prior_native10_actual_registry": "6930d8ab9054f099c7e08dc6c791c1a670733dfc",
            "limit": "Allowlist retention and dependency compilation do not prove target execution; indirect consumers are not separately qualified PTY target cases."},
    "cancelled_jobs": [{"id": j["id"], "name": j["name"], "runner_id": 0, "steps": []} for j in cancelled],
    "in_progress_jobs": [{"id": j["id"], "name": j["name"]} for j in jobs if j["status"] == "in_progress"],
    "scope_limits": ["One bounded run/job API collection; no second poll, dispatch, retry, cancel, or native resource query.",
                     "Six new terminal raw logs and seven original ZIPs only; previously frozen terminal originals are not re-fetched.",
                     "Nextest live/final duplicate status rows are deduplicated by binary and exact case name.",
                     "SKIP entries are not PASS and successful JUnit cases do not contain the skipped roster.",
                     "Eight cancelled jobs have no recorded steps; the API alone does not establish why they were cancelled.",
                     "No product source tests, compilation, formatting, or ref changes are performed by this verifier.",
                     "This does not independently audit every successful test for platform-specific early returns.",
                     "Earlier source GETs and the native10 retention manifest retain their original provenance and are not new execution evidence."]}
print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
