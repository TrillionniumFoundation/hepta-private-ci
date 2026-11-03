#!/usr/bin/env python3
"""Read original hosted archives without executing their embedded files."""

import hashlib
import json
from pathlib import Path
import re
import zipfile


ROOT = Path(__file__).resolve().parent
HEAD = "a7c523f366de3aaf9bce923be885ad275d0ecc22"
TREE = "070d61d7525d55938aa2d6ddcdbf666a138b3125"
MERGE = "f561bfafef1171db955a886227de698e49609913"
BASE = "3a81000aae08c658276958d678874aca4db5eedd"
PARENT = "b446a3f0745e0f7fa9ace98749aeb3e2f845807f"
IDS = (13231852839, 13231791727, 13231069848, 13230918312,
       13230351389, 13229013661)
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
REQUIRED = {
    "host-material.json": 23,
    "cli-process.json": 3,
    "arg0-owner.json": 7,
    "original-owner.json": 42,
    "canonical-pq-contracts.json": 195,
    "pq-initial-material.json": 1,
    "pq-initial-clock.json": 1,
    "initial-startup-budget.json": 1,
    "pq-native-turn-start.json": 1,
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def observed(log):
    text = ANSI.sub("", log.decode(errors="strict"))
    cases = re.findall(r"^\s*PASS\s+\[[^\n]+?\]\s+(\S+\s+\S+)\s*$", text, re.M)
    summaries = re.findall(r"Summary\s+\[[^\n]+?\]\s+(\d+) tests? run: (\d+) passed, (\d+) skipped", text)
    if cases:
        assert len(cases) == len(set(cases)), "duplicate selected test completion"
        assert len(summaries) == 1, "missing or duplicate nextest terminal summary"
        run, passed, skipped = map(int, summaries[0])
        assert run == passed == len(cases), "test case/summary mismatch"
        assert not re.search(r"^\s*(FAIL|RETRY|TRY [2-9]|TIMEOUT|LEAK)\b", text, re.M)
        return dict(passed=passed, skipped_outside_selection=skipped, cases=cases)
    assert not summaries, "summary with no selected passing cases"
    return dict(passed=0, skipped_outside_selection=None, cases=[])


def audit(artifact_id):
    metadata = json.loads((ROOT / f"{artifact_id}.metadata.json").read_bytes())
    raw = (ROOT / f"{artifact_id}.zip").read_bytes()
    assert len(raw) == metadata["size_in_bytes"]
    assert "sha256:" + digest(raw) == metadata["digest"]
    assert metadata["workflow_run"]["head_sha"] == HEAD
    assert metadata["workflow_run"]["id"] == 41634290628
    lane = "base-merge" if "base-merge" in metadata["name"] else "source-head"
    tested = MERGE if lane == "base-merge" else HEAD
    parents = [BASE, HEAD] if lane == "base-merge" else [PARENT]
    source = dict(commit=tested, tree=TREE, dirty=False, parents=parents)
    result = dict(artifact_id=artifact_id, name=metadata["name"],
                  zip_bytes=len(raw), zip_sha256=digest(raw), lane=lane,
                  source_sha=HEAD, tested_sha=tested, tested_tree=TREE,
                  records=[], members=[])
    with zipfile.ZipFile(ROOT / f"{artifact_id}.zip") as z:
        assert len(z.namelist()) == len(set(z.namelist()))
        members = {name: z.read(name) for name in z.namelist()}
        result["members"] = [dict(path=name, bytes=len(data), sha256=digest(data))
                             for name, data in sorted(members.items())]
        if "candidate-tuple.json" in members:
            candidate = json.loads(members["candidate-tuple.json"])
            for key, value in dict(source_sha=HEAD, tested_sha=tested,
                                   base_sha=BASE, lane=lane,
                                   source_tree=TREE, tested_tree=TREE).items():
                assert candidate[key] == value, key
            for name, data in sorted(members.items()):
                if not name.endswith(".json"):
                    continue
                record = json.loads(data)
                if "command" not in record:
                    continue
                assert record["before"] == record["after"] == source, name
                assert record["source_sha"] == HEAD and record["tested_sha"] == tested
                assert record["base_sha"] == BASE and record["lane"] == lane
                assert record["run_id"] == "41634290628" and record["run_attempt"] == "1"
                assert record["job"] == "cell-host-v2"
                assert record["status"] == "passed"
                assert record["command_exit_code"] == record["exit_code"] == 0
                assert record["timed_out"] is False and record["output_limit_exceeded"] is False
                log = members[record["log_file"]]
                assert len(log) == record["log_bytes"] and digest(log) == record["log_sha256"]
                counts = observed(log)
                assert counts["passed"] == record["observed_passed_tests"]
                assert record["observed_failed_tests"] == 0
                assert counts["passed"] >= record["minimum_tests"]
                if name in REQUIRED:
                    assert counts["passed"] == REQUIRED[name], name
                result["records"].append(dict(name=name, command=record["command"],
                    log_sha256=digest(log), log_bytes=len(log), elapsed_seconds=record["elapsed_seconds"],
                    minimum_tests=record["minimum_tests"], **counts))
            assert REQUIRED.keys() <= {r["name"] for r in result["records"]}
            binding = json.loads(members["pq-codex-binding.json"])
            build = json.loads(members["pq-build-codex.json"])
            assert binding["source"] == source
            assert binding["workflow_event_commit"] == MERGE
            assert binding["build_record_sha256"] == digest(members["pq-build-codex.json"])
            assert binding["build_log_sha256"] == digest(members[build["log_file"]])
            assert re.fullmatch("[0-9a-f]{64}", binding["sha256"])
            result["binary_binding"] = binding
            result["binary_independently_downloaded_and_rehashed"] = False
        else:
            before = json.loads(members["source-before.json"])
            assert before == json.loads(members["source-after.json"])
            for key, value in dict(source_sha=HEAD, tested_sha=tested, tree=TREE,
                                   base_sha=BASE, lane=lane, parents=parents,
                                   symlink_placeholders=0).items():
                assert before[key] == value, key
            outcome = json.loads(members["result.json"])
            assert outcome["source"] == before and outcome["status"] == "passed"
            assert outcome["run_id"] == "41634290628" and outcome["run_attempt"] == "1"
            for group, expected in (("witness", 6), ("evaluated-shadow", 11)):
                record = json.loads(members[group + ".json"])
                assert record == outcome["tests"][group]
                log = members[group + ".log"]
                assert digest(log) == record["log_sha256"]
                assert record["status"] == "passed"
                assert record["returncode"] == record["logging_returncode"] == 0
                counts = observed(log)
                assert counts["passed"] == record["observed_passed_tests"] == expected
                assert record["observed_failed_tests"] == 0
                result["records"].append(dict(name=group, log_sha256=digest(log),
                    log_bytes=len(log), minimum_tests=record["minimum_tests"], **counts))
    return result


def main():
    results = [audit(artifact_id) for artifact_id in IDS]
    report = dict(schema="hepta-hosted-archive-audit-v1", run_id=41634290628,
        interpretation="Source-specific component observations; selections overlap.",
        whole_system_qualified=False, pq_128_qualified=False,
        production_activation=False, artifacts=results)
    (ROOT / "archive-audit.json").write_text(json.dumps(report, indent=2) + "\n")
    for result in results:
        print(json.dumps({"artifact_id": result["artifact_id"],
            "name": result["name"], "records": len(result["records"]),
            "tests": {r["name"]: r["passed"] for r in result["records"] if r["passed"]}}))


if __name__ == "__main__":
    main()
