"""Verify c895 original retained bytes, without running archived commands."""
import hashlib
import json
from pathlib import Path
import re
import zipfile

HERE = Path(__file__).resolve().parent
HEAD = "c89540598693697577cda8cba31cb07f6ce65317"
TREE = "5a7c897a33e4eef48ea8f4bf52eaf48ea7c866ae"
BASE = "96038ccf0660154fac143ba6cbe4be81e00813e8"
MERGE = "84f1cc53ffddce902df541cdef33524ecaa93c7b"

def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}

def load(path):
    return json.loads(path.read_bytes())

def verify_artifact(artifact_id):
    root = HERE / "artifacts" / str(artifact_id)
    manifest = load(root / "MANIFEST.json")
    data = (root / "original.zip").read_bytes()
    measured = identity(data)
    assert measured["bytes"] == manifest["artifact"]["size_in_bytes"]
    assert "sha256:" + measured["sha256"] == manifest["artifact"]["digest"]
    assert manifest["artifact"]["workflow_run"]["head_sha"] == HEAD
    with zipfile.ZipFile(root / "original.zip") as archive:
        assert archive.testzip() is None
        names = [item.filename for item in archive.infolist() if not item.is_dir()]
        assert len(names) == len(set(names))
        assert set(names) == {row["name"] for row in manifest["members"]}
        for row in manifest["members"]:
            raw = archive.read(row["name"])
            assert raw == (root / "files" / row["name"]).read_bytes()
            assert len(raw) == row["bytes"] and hashlib.sha256(raw).hexdigest() == row["sha256"]
    return {"artifact_id": artifact_id, "archive": measured, "members": len(names)}

def python_case_ids(text):
    lines = text.splitlines()
    starts = []
    for number, line in enumerate(lines):
        match = re.match(r"^(test\S+) \(([^)]+)\)(?: \.\.\..*)?$", line)
        if match:
            starts.append((number, match.group(2)))
    result = []
    for number, (start, name) in enumerate(starts):
        end = starts[number + 1][0] if number + 1 < len(starts) else len(lines)
        terminals = []
        for line in lines[start:end]:
            match = re.search(r"(?:^|\.\.\.)\s*(ok|FAIL|ERROR|skipped[^\n]*)$", line)
            if match:
                terminals.append(match.group(1))
        assert terminals == ["ok"], (name, terminals)
        result.append(name)
    summaries = [int(value) for value in re.findall(r"^Ran (\d+) tests? in [^\n]+$", text, re.M)]
    assert summaries == ([len(result)] if result else [])
    if result:
        assert text.rstrip().endswith("\nOK")
    assert len(result) == len(set(result))
    return result

def python_receipts(artifact_id, run, lane, tested):
    root = HERE / "artifacts" / str(artifact_id) / "files"
    rows = []
    for path in sorted(root.glob("*.json")):
        receipt = load(path)
        if not isinstance(receipt, dict) or "command" not in receipt:
            continue
        assert receipt["status"] == "passed"
        assert receipt["command_exit_code"] == receipt["exit_code"] == receipt["returncode"] == 0
        assert receipt["timed_out"] is False and receipt["output_limit_exceeded"] is False
        assert (receipt["source_sha"], receipt["tested_sha"], receipt["base_sha"], receipt["lane"]) == (HEAD, tested, BASE, lane)
        assert int(receipt["run_id"]) == run and str(receipt["run_attempt"]) == "1"
        assert receipt["before"] == receipt["after"]
        before = receipt["before"]
        assert before["commit"] == tested and before["tree"] == TREE and before["dirty"] is False
        if lane == "base-merge":
            assert before["parents"] == [BASE, HEAD] and receipt["recomputed_merge_tree"] == TREE
        else:
            assert before["parents"] == ["1c063ba9e934f060181d4fc17d724361ba2a37fd"]
        raw = (root / receipt["log_file"]).read_bytes()
        assert len(raw) == receipt["log_bytes"] and hashlib.sha256(raw).hexdigest() == receipt["log_sha256"]
        cases = python_case_ids(raw.decode())
        assert len(cases) == receipt["observed_passed_tests"] >= receipt["minimum_tests"]
        assert receipt["observed_failed_tests"] == 0
        rows.append({"artifact_id": artifact_id, "receipt": path.name, "receipt_identity": identity(path.read_bytes()),
                     "log": receipt["log_file"], "log_identity": identity(raw), "command": receipt["command"],
                     "case_ids": cases, "passed": len(cases), "failed": 0, "lane": lane,
                     "tested_sha": tested, "source_sha": HEAD, "tree": TREE, "source_before_after_clean": True,
                     "started_at": receipt["started_at"], "finished_at": receipt["finished_at"]})
    return rows

def campaign():
    root = HERE / "artifacts/13868481966/files/campaign"
    report = load(root / "REPORT.json")
    assert report["planned_scenarios"] == report["passed_scenarios"] == report["fresh_read_processes"] == 14
    assert report["model_calls"] == 0 and report["exited_writer_processes"] == 3
    assert all(report["invariants"].values())
    for key in ("complete_cost_coverage", "external_effect_fencing", "full_owner_cold_recovery", "independent_trust_domain", "production_adoption", "real_successor_task_benefit"):
        assert report[key] is False
    def check(row):
        data = (root / row["path"]).read_bytes()
        assert len(data) == row["bytes"] and hashlib.sha256(data).hexdigest() == row["sha256"]
        return data
    check(report["plan"])
    pids, scenarios = [], []
    for mutation in report["mutations"]:
        assert mutation["returncode"] == 0 and mutation["writer_exited_before_readers"] is True
        for key in ("response", "stderr", "stdout"):
            check(mutation[key])
        pids.append(mutation["pid"])
    for row in report["rows"]:
        assert row["passed"] is True and row["request_bound"] is True and row["process"]["returncode"] == 0
        check(row["request"])
        check(row["process"]["stderr"])
        response = json.loads(check(row["process"]["stdout"]))
        assert response["receipt"] == row["receipt"]
        context = response["context"].encode()
        assert len(context) == row["receipt"]["context_bytes"]
        assert hashlib.sha256(context).hexdigest() == row["receipt"]["context_sha256"]
        assert row["receipt"]["delivered_ids"] == row["expected_ids"]
        assert row["receipt"]["scientific_acceptance"] == "HOLD"
        assert row["receipt"]["real_task_benefit_established"] is False
        pids.append(row["process"]["pid"])
        scenarios.append(row["scenario"])
    assert len(scenarios) == len(set(scenarios)) == 14
    assert len(pids) == len(set(pids)) == 17
    return {"reader_processes": 14, "writer_processes": 3, "scenario_ids": scenarios,
            "request_response_context_hashes_checked": True, "model_calls": 0,
            "deletion_scope": report["deletion_scope"], "real_task_benefit": False,
            "independent_trust_domain": False, "full_owner_cold_recovery": False}

def main():
    artifacts = [verify_artifact(aid) for aid in (13868481966, 13867373162)]
    integrity = python_receipts(13868481966, 43048568457, "source-head", HEAD)
    merge = python_receipts(13867373162, 43048568183, "base-merge", MERGE)
    assert len(integrity) == 1 and sum(row["passed"] for row in integrity) == 35
    assert len(merge) == 4 and sum(row["passed"] for row in merge) == 136
    candidate = load(HERE / "artifacts/13867373162/files/candidate-tree.json")
    assert candidate["native_execution_required"] is False
    assert candidate["requires_source_head_success"] is True
    assert candidate["source_tree"] == candidate["tested_tree"] == TREE
    assert candidate["source_sha"] == HEAD and candidate["tested_sha"] == MERGE
    report = {"schema": "mem8.c895.completed-receipts.partial.v1", "scope": "Only the two completed original jobs retained here; not overall CI acceptance",
              "source_commit": HEAD, "source_tree": TREE, "artifacts": artifacts,
              "MEM_integrity": {"passed": 35, "failed": 0, "job": 130619112947},
              "Architecture_base_merge": {"passed": 136, "failed": 0, "job": 130619111431,
                                          "merge_commit": MERGE, "native_reused_only_if_source_head_succeeds": True},
              "synthetic_campaign": campaign(), "groups": integrity + merge,
              "archived_commands_executed_by_verifier": 0, "historical_pass_results_transferred": False,
              "real_successor_benefit_established": False}
    (HERE / "COMPLETED_RECEIPTS_PARTIAL_AUDIT.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "groups"}, indent=2))

if __name__ == "__main__":
    main()
