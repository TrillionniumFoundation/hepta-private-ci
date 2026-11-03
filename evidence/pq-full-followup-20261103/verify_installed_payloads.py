#!/usr/bin/env python3
"""Verify the completed installed V5 run and preserve its failed business gate."""

import hashlib
import io
import json
from pathlib import Path
import re
import tarfile


ROOT = Path(__file__).resolve().parent
HEPTA = "a7c523f366de3aaf9bce923be885ad275d0ecc22"
CHAIN = "12fe5f2c1f19704fe7eb635dede6839ed8b1e91e"
TREES = {HEPTA: "070d61d7525d55938aa2d6ddcdbf666a138b3125",
         CHAIN: "c44112da731e3f958e55eb024e5762d6723ea2c9"}
COUNTS = {"artifact-controls.json": 17, "execution-source-controls.json": 51,
          "diverse-source-controls.json": 32, "original-handoff.json": 14,
          "installed-handoff.json": 8, "current-pq-continuous.json": 14,
          "current-history-import.json": 15, "current-growth-cli.json": 7,
          "current-from-zero-host-controls.json": 20,
          "current-from-zero-reader-controls.json": 98}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def counts(data):
    text = data.decode(errors="strict")
    summaries = re.findall(r"^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; \d+ measured; (\d+) filtered out;", text, re.M)
    if summaries:
        values = [tuple(map(int, row)) for row in summaries]
        assert all(failed == ignored == 0 for _, failed, ignored, _ in values)
        return dict(passed=sum(row[0] for row in values), summaries=values)
    python = re.findall(r"Ran (\d+) tests? in [^\n]+\n\s*\n?OK([^\n]*)", text)
    assert len(python) == 1 and python[0][1] == ""
    actual = len(re.findall(r"^test_\S+ \([^\n]+\) \.\.\. ok$", text, re.M))
    assert actual == int(python[0][0])
    return dict(passed=actual, skipped=0)


def main():
    data = {}
    for path in sorted((ROOT / "installed").glob("*.manifest.json")):
        manifest = json.loads(path.read_bytes())
        raw = (path.parent / manifest["payload_file"]).read_bytes()
        assert len(raw) == manifest["payload_bytes"]
        assert digest(raw) == manifest["payload_sha256"]
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:xz") as archive:
            members = archive.getmembers()
            assert all(member.isfile() for member in members)
            assert len(members) == len({member.name for member in members})
            contents = {member.name: archive.extractfile(member).read() for member in members}
        assert set(contents) == {member["path"] for member in manifest["members"]}
        assert not data.keys() & contents.keys()
        for member in manifest["members"]:
            value = contents[member["path"]]
            assert len(value) == member["bytes"] and digest(value) == member["sha256"]
        data.update(contents)

    records = []
    for name, raw in sorted(data.items()):
        if "/" in name or not name.endswith(".json"):
            continue
        record = json.loads(raw)
        if "command" not in record:
            continue
        source = record["source_sha"]
        assert source in TREES and record["tested_sha"] == source
        assert record["before"] == record["after"]
        assert record["before"]["commit"] == source
        assert record["before"]["tree"] == TREES[source]
        assert record["before"]["dirty"] is False
        assert record["run_id"] == "41634290628" and record["run_attempt"] == "1"
        assert record["job"] == "cell-installed-host-v3"
        assert record["timed_out"] is False and record["output_limit_exceeded"] is False
        log = data[record["log_file"]]
        assert len(log) == record["log_bytes"] and digest(log) == record["log_sha256"]
        if name == "current-from-zero.json":
            assert record["status"] == "failed"
            assert record["exit_code"] == record["command_exit_code"] == 1
        else:
            assert record["status"] == "passed"
            assert record["exit_code"] == record["command_exit_code"] == 0
        result = dict(name=name, source=source, status=record["status"],
                      command=record["command"], log_bytes=len(log), log_sha256=digest(log))
        if name in COUNTS:
            actual = counts(log)
            assert actual["passed"] == COUNTS[name] == record["observed_passed_tests"]
            assert record["observed_failed_tests"] == 0
            result["observed"] = actual
        records.append(result)
    assert COUNTS.keys() <= {row["name"] for row in records}
    installed = json.loads(data["installed-controls.json"])
    assert installed["status"] == "passed" and installed["command_statuses"] == [0, 0]
    assert installed["before"] == installed["after"]
    assert installed["binaries_before"] == installed["binaries_after"]
    imported = json.loads(data["verified-native.json"])
    assert imported["binary"] == installed["binaries_before"]["hepta"]
    assert imported["source_identity"] == installed["before"]["hepta"]
    assert imported["candidate"] == installed["hepta_candidate"]
    assert imported["producer"]["binary"] == imported["binary"]
    assert imported["ci"] == installed["ci"]
    for flag in ("model_qualified", "native_pair_qualification", "pn0_closed", "production_activation"):
        assert installed[flag] is False
    binary = json.loads((ROOT / "installed/binary-hash-observations.json").read_bytes())
    chain_image = next(row for row in binary["observations"] if row["path"] == "trnm-cell.gz")
    assert chain_image["decompressed_sha256"] == installed["binaries_before"]["chain"]["sha256"]
    assert chain_image["decompressed_bytes"] == installed["binaries_before"]["chain"]["bytes"]
    for gzip_name, digest_file in (("trnm-cell.gz", "chain-binary.sha256"),
                                   ("current-node-pq.gz", "current-node-binary.sha256")):
        image = next(row for row in binary["observations"] if row["path"] == gzip_name)
        recorded = {line.split()[0] for line in data[digest_file].decode().splitlines()}
        assert recorded == {image["sha256"], image["decompressed_sha256"]}
    native = json.loads(data["current-from-zero/manifest.json"])
    assert native["source_before"] == native["source_after"]
    assert native["source_before"]["commit"] == CHAIN
    assert native["source_before"]["tree"] == TREES[CHAIN]
    assert native["passed"] is False and native["all_named_tests_passed"] is True
    assert native["failures"] == ["CONFIRMATION_TARGET"]
    native_image = next(row for row in binary["observations"]
                        if row["path"] == "current-from-zero/public_v3_from_zero")
    assert native_image["sha256"] == native["binary_sha256_before"] == native["binary_sha256_after"]
    assert len(native["runs"]) == 5
    assert all(run["process"]["exit_code"] == 0 for run in native["runs"])
    report_raw = data["current-from-zero/confirmation/report.json"]
    report = json.loads(report_raw)
    assert report["finite_target_met"] is False and report["invariant_target_met"] is True
    phases = []
    for phase in report["phases"]:
        replay = phase["independent_history_page_replay"]
        phases.append(dict(mode=phase["mode"], original_window_ns=phase["requested_window_ns"],
            confirmations=phase["client_confirmed_transactions"],
            confirmation_latency_ns=phase["client_confirmation_latency_ns"],
            full_native_state_equal=phase["full_native_state_equal"],
            verification_errors=phase["verification_errors"],
            successful_submissions=sum(row["status"] == "ok" for row in phase["honest_submissions"]),
            last_submission_ended_ns=max(row["ended_ns"] for row in phase["honest_submissions"]),
            downloaded_history_pages=sum(row["status"] == "ok" for row in phase["honest_history"]),
            accepted_replay_pages=sum(row["replay_accepted"] for row in replay),
            replay=[{key: row[key] for key in ("history_call_index", "replay_accepted",
                    "replay_started_ns", "replay_ended_ns", "replay_thread_cpu_ns", "replay_wall_ns")}
                    for row in replay]))
    result = dict(schema="hepta-installed-v5-retained-observations-v1", run_id=41634290628,
                  artifact_id=13233273505, source_hepta=HEPTA, source_chain=CHAIN,
                  records=records, original_named_native_cases=5,
                  confirmation_report_sha256=digest(report_raw), phases=phases,
                  original_gate_failures=native["failures"], whole_system_qualified=False,
                  production_activation=False)
    (ROOT / "installed-verified-observations.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"verified_receipts": len(records), "selected_counts": COUNTS,
                      "original_gate_failures": native["failures"], "phases": phases}))


if __name__ == "__main__":
    main()
