#!/usr/bin/env python3
"""Verify retained historical pair observations; never dispatch a workload."""

import hashlib
import io
import json
from pathlib import Path
import tarfile


ROOT = Path(__file__).resolve().parent


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    observations = []
    for path in sorted((ROOT / "pair").glob("*.manifest.json")):
        manifest = json.loads(path.read_bytes())
        payload = path.parent / manifest["payload_file"]
        raw = payload.read_bytes()
        assert len(raw) == manifest["payload_bytes"]
        assert sha256(raw) == manifest["payload_sha256"]
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:xz") as archive:
            members = archive.getmembers()
            assert all(member.isfile() for member in members)
            assert len(members) == len({member.name for member in members})
            data = {member.name: archive.extractfile(member).read() for member in members}
        assert set(data) == {member["path"] for member in manifest["members"]}
        for member in manifest["members"]:
            original = data[member["path"]]
            assert len(original) == member["bytes"]
            assert sha256(original) == member["sha256"]
        report_raw = data["chain-from-zero-native/confirmation/report.json"]
        report = json.loads(report_raw)
        native = json.loads(data["chain-from-zero-native/manifest.json"])
        assert native["source_before"] == native["source_after"]
        assert native["passed"] is False
        assert "CONFIRMATION_TARGET" in native["failures"]
        assert native["all_named_tests_passed"] is True
        assert report["finite_target_met"] is False
        assert report["invariant_target_met"] is True
        assert report["production_activation"] is False
        entry = dict(artifact_id=manifest["artifact"]["id"],
                     artifact_name=manifest["artifact"]["name"],
                     original_zip_sha256=manifest["artifact"]["digest"],
                     original_report_sha256=sha256(report_raw),
                     source_tuple=data["tuple.txt"].decode(),
                     native_source=native["source_before"], phases=[])
        for phase in report["phases"]:
            submissions = phase["honest_submissions"]
            history = phase["honest_history"]
            entry["phases"].append(dict(mode=phase["mode"],
                original_window_ns=phase["requested_window_ns"],
                confirmed_transactions=phase["client_confirmed_transactions"],
                confirmation_latency_ns=phase["client_confirmation_latency_ns"],
                full_native_state_equal=phase["full_native_state_equal"],
                invariant_target_met=phase["invariant_target_met"],
                accounting_closed=phase["accounting_closed"],
                verification_errors=phase["verification_errors"],
                successful_submissions=sum(row["status"] == "ok" for row in submissions),
                last_submission_ended_ns=max(row["ended_ns"] for row in submissions),
                successful_history_pages=sum(row["status"] == "ok" for row in history),
                history_errors=[row["error"] for row in history if row["status"] != "ok"]))
        observations.append(entry)
    assert len(observations) == 4
    result = dict(schema="hepta-pair-retained-observations-v1", run_id=41634290628,
                  workload_rerun=False, failure_waived=False,
                  whole_system_qualified=False, observations=observations)
    (ROOT / "pair-verified-observations.json").write_text(json.dumps(result, indent=2) + "\n")
    for item in observations:
        print(json.dumps({"artifact_id": item["artifact_id"], "name": item["artifact_name"],
                          "phases": item["phases"]}))


if __name__ == "__main__":
    main()
