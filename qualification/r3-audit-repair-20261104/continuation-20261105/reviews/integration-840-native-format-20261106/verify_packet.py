#!/usr/bin/env python3
"""Offline custody, CI cut, JUnit and formatter verification. No native execution."""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path

HEAD = "840e8b5dbffca017753cdf87482ce325938f313c"
TREE = "b38cc55050c74f8765bdee397a24066c100a179a"
RUN = 42197896368
JOBS = {"ubuntu-24.04": 127825647336, "windows-latest": 127825647542}
ARTIFACTS = {
    13493637703: ("ubuntu-24.04", "protocol", 14),
    13493467276: ("windows-latest", "protocol", 14),
    13493168627: ("ubuntu-24.04", "supervisor", 3),
    13493122898: ("windows-latest", "supervisor", 3),
}
SUPERVISOR_NAMES = {
    "unexpected_agent_crashes_back_off_and_stop_after_three_restarts",
    "restart_budget_survives_repeated_supervisord_recovery",
    "unsigned_digest_abort_directive_cannot_clear_signed_production_recovery_fence",
}
COMMANDS = [
    "just test --locked -p codex-hepta-supervisor --test restart_budget --test restart_budget_recovery --test signed_intent_recovery --no-tests fail --retries 0 --status-level all --final-status-level all",
    "just test --locked -p codex-hepta-agent-protocol --profile default --test-threads 2 --no-tests fail --retries 0 --status-level all --final-status-level all",
    "cargo +1.95.0 clippy --locked -p codex-hepta-supervisor --all-targets -- -D warnings",
]


def identity(b):
    return {"bytes": len(b), "git_blob": hashlib.sha1(b"blob " + str(len(b)).encode() + b"\0" + b).hexdigest(), "sha256": hashlib.sha256(b).hexdigest()}


def read(path):
    return json.loads(path.read_bytes())


def unpack(raw):
    raw = raw.get("raw", raw)
    assert not raw.get("isError", False)
    data = raw.get("structuredContent", raw)
    return json.loads(data["content"]) if isinstance(data, dict) and isinstance(data.get("content"), str) else data


def counts(rows):
    return dict(sorted(Counter(x["conclusion"] if x["status"] == "completed" else x["status"] for x in rows).items()))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.root, args.output
    out.mkdir(parents=True, exist_ok=False)
    author, independent, ci = root / "author", root / "independent", root / "ci"
    for directory, manifest in [(author, "FREEZE.json"), (independent, "DELIVERY-MANIFEST.json")]:
        data = read(directory / manifest)
        for item in data["files"]:
            assert identity((directory / item["path"]).read_bytes()) == {k: item[k] for k in ["bytes", "git_blob", "sha256"]}
    assert identity((independent / "REVIEW.json").read_bytes())["git_blob"] == "ef03d24a5f8a16c598f0dab38044436810d0a562"
    replays = []
    commands = [
        ([sys.executable, str(author / "verify_candidate.py"), "--root", str(author), "--output", str(out / "author-replay")], author / "verification-02.stdout.json", "author"),
        ([sys.executable, str(independent / "verify_independent.py"), "--source", str(author), "--review", str(independent), "--output", str(out / "independent-replay")], independent / "independent-01.stdout.json", "independent"),
    ]
    for command, expected, name in commands:
        result = subprocess.run(command, capture_output=True)
        (out / (name + ".stdout.json")).write_bytes(result.stdout)
        (out / (name + ".stderr.txt")).write_bytes(result.stderr)
        assert result.returncode == 0 and not result.stderr, (name, result.returncode, result.stderr.decode())
        assert result.stdout == expected.read_bytes(), name
        replays.append({"name": name, "exit_code": 0, "stderr_bytes": 0, "stdout": identity(result.stdout), "full_stdout_equal": True})
    cuts = []
    run_sets = []
    expected_counts = [{"in_progress": 5, "pending": 4, "queued": 7, "skipped": 2}, {"failure": 1, "in_progress": 4, "pending": 2, "queued": 6, "skipped": 2, "success": 3}]
    for index, label in enumerate(["first", "second"]):
        path = ci / f"840e8b5-head-runs-{label}.original.json"
        data = unpack(read(path)); runs = data["workflow_runs"]
        assert data["total_count"] == len(runs) == len({x["id"] for x in runs}) == 18
        assert all(x["head_sha"] == HEAD and x["event"] == "pull_request" and x["run_attempt"] == 1 for x in runs)
        assert counts(runs) == expected_counts[index]
        run_sets.append({x["id"] for x in runs})
        cuts.append({"kind": "complete_head_runs", "label": label, "file": path.name, **identity(path.read_bytes()), "total": 18, "counts": counts(runs), "runs": [{k: x[k] for k in ["id", "name", "status", "conclusion", "head_sha", "run_attempt"]} for x in runs]})
    assert run_sets[0] == run_sets[1]
    for label, total, expected in [("first", 0, {}), ("second", 3, {"in_progress": 1, "queued": 1, "success": 1})]:
        path = ci / f"blocking-42197896439-jobs-{label}.original.json"
        data = unpack(read(path)); jobs = data["jobs"]
        assert data["total_count"] == len(jobs) == len({x["id"] for x in jobs}) == total
        assert all(x["head_sha"] == HEAD and x["run_id"] == 42197896439 for x in jobs)
        assert counts(jobs) == expected
        cuts.append({"kind": "complete_blocking_jobs", "label": label, "file": path.name, **identity(path.read_bytes()), "total": total, "counts": expected, "jobs": [{k: x[k] for k in ["id", "name", "status", "conclusion"]} for x in jobs]})
    artifact_api = unpack(read(ci / "artifacts-full.original.json"))
    assert artifact_api["total_count"] == len(artifact_api["artifacts"]) == 4
    actual_artifacts = {x["id"]: x for x in artifact_api["artifacts"]}
    assert actual_artifacts.keys() == ARTIFACTS.keys()
    artifact_results, platform_cases = [], {platform: set() for platform in JOBS}
    for aid, (platform, scope, expected_count) in ARTIFACTS.items():
        api = actual_artifacts[aid]
        assert api["workflow_run"]["id"] == RUN and api["workflow_run"]["head_sha"] == HEAD
        assert not api["expired"]
        path = ci / "artifacts" / f"supervisor-840-artifact-{aid}.original.zip"
        raw = path.read_bytes()
        assert len(raw) == api["size_in_bytes"] and "sha256:" + hashlib.sha256(raw).hexdigest() == api["digest"]
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None and archive.namelist() == ["junit.xml"]
            xml = archive.read("junit.xml"); member = archive.getinfo("junit.xml")
        assert xml == (ci / "artifacts" / str(aid) / "junit.xml").read_bytes()
        report = ET.fromstring(xml); cases = report.findall(".//testcase")
        assert len(cases) == expected_count == int(report.get("tests"))
        assert report.get("failures") == report.get("errors") == "0"
        assert all(not any(case.find(tag) is not None for tag in ["failure", "error", "skipped"]) for case in cases)
        pairs = {(case.get("classname"), case.get("name")) for case in cases}
        assert len(pairs) == expected_count
        if scope == "supervisor":
            assert {name for _, name in pairs} == SUPERVISOR_NAMES
        else:
            assert all(cls == "codex-hepta-agent-protocol" for cls, _ in pairs)
            assert ("codex-hepta-agent-protocol", "tests::automation_effect_wire_round_trip_is_strict_and_bounded") in pairs
        platform_cases[platform] |= pairs
        artifact_results.append({"id": aid, "platform": platform, "scope": scope, "archive": identity(raw), "official_digest_equal": True, "CRC_valid": True, "XML": identity(xml), "member_CRC": member.CRC, "XML_root_attributes": report.attrib, "passed": expected_count, "failed": 0, "errors": 0, "skipped": 0, "cases": sorted([{"classname": cls, "name": name} for cls, name in pairs], key=lambda x: (x["classname"], x["name"]))})
    workflow_raw = read(author / "authority/workflow-full-GET.original.json")
    workflow = workflow_raw["structuredContent"]["content"]
    assert identity(workflow.encode())["git_blob"] == "fdeb340099f9f720a353aa8b69372e75a335387e"
    base_leaves = {x["path"]: x["sha"] for x in read(author / "authority/base-full-tree.json")["tree"] if x["type"] == "blob"}
    assert base_leaves[".github/workflows/hepta-supervisor-p0-crossplatform.yml"] == identity(workflow.encode())["git_blob"]
    assert all(command in workflow for command in COMMANDS)
    job_map = {x["id"]: x for x in unpack(read(author / "original/jobs-full.original.json"))["jobs"]}
    native_jobs = []
    for platform, jid in JOBS.items():
        job = job_map[jid]; steps = job["steps"]
        assert job["head_sha"] == HEAD and job["run_id"] == RUN and job["conclusion"] == "failure"
        failures = [x for x in steps if x["conclusion"] == "failure"]
        assert len(failures) == 1 and "canonical Rust format" in failures[0]["name"]
        names = ["Verify exact source identity", "Execute actual restart budget, repeated recovery and signed intent recovery", "Verify named native test evidence", "Execute the complete Agentd protocol package", "Verify signed protocol wire regression evidence", "Strict Supervisor Clippy", "Preserve native JUnit evidence", "Preserve Agentd protocol JUnit evidence", "Ensure test checkout remained immutable"]
        for name in names:
            selected = [x for x in steps if x["name"] == name]
            assert len(selected) == 1 and selected[0]["conclusion"] == "success"
        raw = (author / f"original/job-{jid}.original.log").read_bytes()
        lines = [re.sub(r"\x1b\[[0-9;]*m", "", re.sub(r"^\d{4}-\d\d-\d\dT\S+Z ", "", line)) for line in raw.decode().splitlines()]
        assert lines.count(f"source={HEAD} tree={TREE} parents=875b774885c002bbe157fd2919fcb590ee1e0131") == 1
        for command in COMMANDS:
            assert "##[group]Run " + command in lines
        passed = set()
        for line in lines:
            match = re.fullmatch(r"\s*PASS\s+\[\s*[0-9.]+s\]\s+(\S+)\s+(\S+)", line)
            if match: passed.add(match.groups())
        assert passed == platform_cases[platform]
        json_results = [json.loads(line) for line in lines if line.startswith('{"passed":')]
        assert len(json_results) == 2 and {x["passed"] for x in json_results} == {3, 14}
        assert all(x["source_sha"] == HEAD for x in json_results)
        summaries = [line.strip() for line in lines if re.search(r"Summary \[", line)]
        assert len(summaries) == 2 and "3 tests run: 3 passed, 0 skipped" in summaries[0] and "14 tests run: 14 passed, 0 skipped" in summaries[1]
        native_jobs.append({"platform": platform, "job": jid, "actual_checkout": HEAD, "tree": TREE, "job_conclusion": "failure", "failed_step": failures[0]["name"], "Supervisor_selected_integration_tests": 3, "Agentd_protocol_tests": 14, "native_XML_and_console_cases_equal": True, "Strict_Supervisor_all_targets_Clippy": "success", "immutable_source_guard": "success", "raw_log": identity(raw), "raw_CR_count": raw.count(b"\r"), "six_new_Unix_unit_tests_executed": False, "paired_process_product_executed": False})
    result = {"schema": "hepta-current-head-ci-and-native-format-v1", "source_head": HEAD, "source_tree": TREE, "source_merge": "e0993cb056c30ae4b694f5c0a187759f0edeefe1", "cuts": cuts, "native_run": RUN, "native_jobs": native_jobs, "artifacts": artifact_results, "static_formatter_candidate_tree": "25020dc30888fa3ffa6f6e8d1073d91edded1756", "independent_review_actual": "ef03d24a5f8a16c598f0dab38044436810d0a562", "static_replays": replays, "scope": {"original_two_jobs_remain_failure": True, "source_840_local_native_acceptance_only": True, "candidate_or_successor_native_acceptance": False, "uncached_native_qualification_claimed": False, "complete_required_CI_pass_claimed": False, "additional_blockers_closed": 0, "manual_CI_operations": [], "private_capacity_queries": False}, "snapshot_note": "Each original API response is a separate observation. Run-list status and jobs status are not an atomic snapshot. Prior 09:30 package is unchanged."}
    encoded = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode()
    (out / "VERIFICATION.json").write_bytes(encoded)
    print(encoded.decode(), end="")


if __name__ == "__main__":
    main()
