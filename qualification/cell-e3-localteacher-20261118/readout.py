"""Audit retained raw calls and report the frozen paired-teacher diagnostic."""

import argparse
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_bytes())


def sha(value):
    return hashlib.sha256(value).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode())


def report(originals, evidence):
    index = read(originals / "ARCHIVE_MANIFEST.json")
    for name, expected in index["files"].items():
        raw = (originals / name).read_bytes()
        assert len(raw) == expected["bytes"] and sha(raw) == expected["sha256"]
    run = originals / "candidate-8080/run-1"
    freeze = read(run / "FREEZE.json")
    protocol = read(evidence / "PROTOCOL.json")
    records = read(evidence / "A_RECORDS.json")
    assert freeze["protocol"] == protocol
    assert freeze["records_digest"] == digest(records)
    baseline = read(evidence / "BASELINE_RECHECK.json")
    assert baseline["calls"] == 12 and baseline["successes"] == 0
    assert all(row["first_feedback_exactly_matches_original_second_request"]
               for row in baseline["rows"] if row["attempt"] == 0)
    stages, calls = {}, []
    for stage in ("first", "second"):
        receipts = read(evidence / "verification" / stage / "VERIFICATIONS.json")
        summary = read(evidence / "verification" / stage / "SUMMARY.json")
        assert len(receipts) == summary["verified_calls"] == 6
        assert read(run / (stage.upper() + "_COMPLETE.json"))["model_calls"] == 6
        stages[stage] = receipts
        for index, (record, receipt) in enumerate(zip(records, receipts)):
            folder = run / stage
            request = read(folder / f"REQUEST-{index}.json")
            output = read(folder / f"OUTPUT-{index}.json")
            assert output["freeze_digest"] == digest(freeze)
            assert output["request_digest"] == digest(request["payload"])
            assert output["logical_messages_digest"] == digest(request["logical_messages"])
            assert output["record_id"] == record["record_id"] == receipt["record_id"]
            answer = output["raw_response"]["choices"][0]["message"].get("content") or ""
            assert output["answer"] == answer
            assert sha(answer.encode()) == receipt["answer_sha256"]
            if stage == "first":
                assert request["logical_messages"] == [{"role": "user", "content": record["task"]["input"]}]
            else:
                first = read(run / "first" / f"OUTPUT-{index}.json")
                feedback = read(evidence / "verification/first/FEEDBACK.json")[index]
                assert feedback["verification_digest"] == digest(stages["first"][index])
                assert request["logical_messages"] == [
                    {"role": "user", "content": record["task"]["input"]},
                    {"role": "assistant", "content": first["answer"]},
                    {"role": "tool", "content": feedback["content"]},
                ]
            usage = output["usage"]
            assert 0 < usage["prompt_tokens"] <= 4096
            assert 0 < usage["completion_tokens"] <= 384
            calls.append({"stage": stage, "record_id": record["record_id"],
                          "success": receipt["success"],
                          "reason": receipt["result"]["reason"],
                          "input_tokens": usage["prompt_tokens"],
                          "output_tokens": usage["completion_tokens"],
                          "http_wall_seconds": output["wall_seconds"],
                          "finish_reason": output["raw_response"]["choices"][0]["finish_reason"],
                          "request_digest": output["request_digest"],
                          "output_digest": digest(output),
                          "verification_digest": digest(receipt)})
    rows = []
    for record, first, last in zip(records, stages["first"], stages["second"]):
        a, b = first["success"], last["success"]
        rows.append({"record_id": record["record_id"], "first": a, "last": b,
                     "selected": a or b, "recovered": not a and b, "regressed": a and not b})
    aggregate = {key: sum(row[key] for row in rows)
                 for key in ("first", "last", "selected", "recovered", "regressed")}
    result = {
        "schema": "hepta.real-second-teacher-readout.v1", "status": "COMPLETE",
        "sampling_source": "16f21699a4cd661ed998333369f3734a572caf96",
        "protocol_file_sha256": sha((evidence / "PROTOCOL.json").read_bytes()),
        "original_archive_sha256": "0ee947fdd6833a46b52a1165795268ac697969c0f2b167ca261c1b71a0e5f132",
        "original_index_sha256": sha((originals / "ARCHIVE_MANIFEST.json").read_bytes()),
        "verified_original_files": len(read(originals / "ARCHIVE_MANIFEST.json")["files"]),
        "teacher_1": {"model_digest": "f63def6407c72c0b6e19647f5879582ab8ed35e4f6207352be931a9f417b0ff6",
                      "checkpoint": "Qwen2.5-Coder-1.5B-Instruct", "reused_calls": 12,
                      "tasks": 6, "first": 0, "last": 0, "selected": 0},
        "teacher_2": {"weight_sha256": "cedf1e08063f6df77926e1169f67b327dcc6301b5b329589615bdf09d4895f7e",
                      "checkpoint": "Qwen3.8-Flash-Next-Uncensored-IQ4XS-NGQ4", "new_calls": 12,
                      "tasks": 6, **aggregate},
        "union_selected": aggregate["selected"],
        "gain_over_best_teacher": 0, "mutual_complementarity_observed": False,
        "same_logical_information_and_call_caps": True, "physical_compute_matched": False,
        "rows": rows, "calls": calls,
        "cost": {"new_model_calls": 12, "baseline_model_calls_reused": 12,
                 "input_tokens": sum(row["input_tokens"] for row in calls),
                 "output_tokens": sum(row["output_tokens"] for row in calls),
                 "http_wall_seconds": sum(row["http_wall_seconds"] for row in calls),
                 "output_limit_calls": sum(row["finish_reason"] == "length" for row in calls),
                 "new_candidate_verifier_calls": 12, "baseline_recheck_verifier_calls": 12,
                 "reference_verifier_calls": 6,
                 "verification_wall_seconds": sum(read(evidence / "verification" / stage / "SUMMARY.json")["verification_wall_seconds"] for stage in ("first", "second")),
                 "baseline_recheck_wall_seconds": baseline["wall_seconds"],
                 "weight_bytes_hashed": 98403356224,
                 "weight_hash_wall_seconds": 134.143754767,
                 "weight_hash_cpu_seconds": 49.02022946,
                 "successful_owner_stage_windows": [read(originals / "candidate-8080" / owner / "EXIT.json") for owner in ("owned-first-1", "owned-second-1")],
                 "superseded_zero_call_exit": read(originals / "owned-first-1/EXIT.json"),
                 "cancelled_readonly_watch_job": "1a1ef0f5a91-ffbe-3e4",
                 "first_hash_attempt_failed_before_weight_read": "1a1eefdc153-ffbe-3b4",
                 "energy_joules": None, "service_compute_cost_known": False,
                 "full_system_cost_known": False, "nested_windows_are_not_additive": True},
        "negative_transfer_measured": False, "student_trained_on_teacher_outputs": False,
        "B_data_sent": False, "independent_users": 0,
        "scientific_confirmation_qualified": False, "native_adoption": False,
        "license_scope": "authorized internal private research; upstream community license/local Apache label conflict retained; external commercial rights not asserted",
    }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("originals", type=Path)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    print(json.dumps(report(args.originals, args.evidence), sort_keys=True, indent=2))
