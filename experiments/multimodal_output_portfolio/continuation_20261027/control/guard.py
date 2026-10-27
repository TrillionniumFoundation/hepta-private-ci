"""Exercise actual durable owner retries, cold restore, forks and fail-closed gaps."""
import argparse
import json
from pathlib import Path
import shutil

from ...repair_20261026.risk_feedback.media import emit, readback
from .client import Native, Q, digest, sha, write
from .training import prefix


def files(root):
    return {name: sha(root / name) for name in ("owner.journal", "owner.witness", "events.jsonl", "IDENTITY.json")}


def resume_request(root, model, calibration):
    return {"command": "Resume", "directory": str(root), "case": "durable-guard", "expires": 7,
        "model": str(model), "model_sha256": sha(model), "calibration": str(calibration),
        "calibration_sha256": sha(calibration)}


def unchanged(native, root, request, *, conflict):
    before_state, before_files = native.call({"command": "Status"}), files(root)
    result = native.call(request, expect_error=conflict)
    after_state, after_files = native.call({"command": "Status"}), files(root)
    if before_state != after_state or before_files != after_files:
        raise ValueError("Retry/conflict changed actual native/ledger state")
    if not conflict and (not result["duplicate_event_ignored"] or result["native_transition_executed"]):
        raise ValueError("Duplicate event executed a native tick")
    if conflict and "Conflicting retry" not in result["error"]:
        raise ValueError("Unexpected rejection mechanism")
    return {"request": request, "result": result, "state_and_files_unchanged": True,
        "before_state": before_state, "before_file_sha256": before_files}


def validate(binary, model, calibration, output):
    output.mkdir(parents=True, exist_ok=False)
    write(output / "FROZEN_GUARD.json", {"binary_sha256": sha(binary), "guard_source_sha256": sha(__file__),
        "model_sha256": sha(model), "calibration_sha256": sha(calibration),
        "registered_cases": ["live_retry", "payload_conflicts", "cold_process_retry", "fork_inherited_retry",
            "missing_last_ledger_commit", "altered_event_payload", "altered_event_identity", "altered_readout", "altered_abstention"]})
    root = output / "owner"
    native = Native(binary)
    native.open(root, "durable-guard", 7, model, calibration)
    first = prefix(native, 0)
    inherited = dict(native.transcript[1]["request"])
    branch = native.call({"command": "Forecast", "feedback_q24": -Q // 2, "branch": "guard"})
    paths = emit(output / "initial", 1, 1)
    observed = readback(paths)
    write(output / "DELIVERED.json", {"paths": paths, "observed": observed,
        "host_permit": "User-authorized experimental output below this guard directory",
        "initial_native_nonabstention": all(not t["native_abstain"] for t in first)})
    request = {"command": "Tick", "event_id": "durable-guard.initial.phase.1", "phase": 1,
        "feedback_q24": -Q // 2, "receipt_digest": digest(observed)}
    acknowledged = native.call(request)
    checks = {"live_retry": unchanged(native, root, request, conflict=False)}
    checks["feedback_conflict"] = unchanged(native, root, dict(request, feedback_q24=-Q), conflict=True)
    checks["receipt_conflict"] = unchanged(native, root, dict(request, receipt_digest=digest({"other": True})), conflict=True)
    checks["phase_conflict"] = unchanged(native, root, dict(request, phase=2, feedback_q24=0), conflict=True)
    write(output / "LIVE_TRANSCRIPT.json", native.transcript)
    # EOF terminates the process without Close. All ack durability precedes EOF;
    # this is a real cold-process restore, not a simulated hardware power loss.
    native.finish()
    native = Native(binary)
    restored = native.call(resume_request(root, model, calibration))
    checks["cold_process_retry"] = unchanged(native, root, request, conflict=False)
    checks["cold_process_conflict"] = unchanged(native, root, dict(request, feedback_q24=-Q), conflict=True)
    native.case = "durable-guard"
    hold = native.tick(2, 0, observed)
    decision = native.tick(3, 0, observed)
    if not decision["proposed_repair"] or decision["native_abstain"]:
        raise ValueError("After-restart feedback did not mediate the permitted later action")
    repaired = readback(emit(output / "repair", 1, 0))
    if repaired["fault_class"] != 0:
        raise ValueError("Actual later repair delivery failed")
    native.close()
    write(output / "RESTORE_TRANSCRIPT.json", native.transcript)
    native.finish()

    fork = root / "forecast-guard"
    native = Native(binary)
    native.call(resume_request(fork, model, calibration))
    checks["fork_inherited_retry"] = unchanged(native, fork, inherited, conflict=False)
    checks["fork_inherited_conflict"] = unchanged(native, fork, dict(inherited, receipt_digest=digest("conflict")), conflict=True)
    native.close()
    write(output / "FORK_TRANSCRIPT.json", native.transcript)
    native.finish()

    mutations = {}
    for mode in ("missing_last_ledger_commit", "altered_event_payload", "altered_event_identity", "altered_readout", "altered_abstention"):
        target = output / mode
        target.mkdir()
        for name in files(root):
            shutil.copyfile(root / name, target / name)
        records = [json.loads(line) for line in (target / "events.jsonl").read_text().splitlines()]
        if mode == "missing_last_ledger_commit":
            records.pop()
        elif mode == "altered_event_payload":
            records[4]["feedback_q24"] = -Q
        elif mode == "altered_event_identity":
            records[4]["event_id"] += ".renamed"
        elif mode == "altered_readout":
            records[-1]["output"]["proposed_repair"] = False
        elif mode == "altered_abstention":
            records[-1]["output"]["native_abstain"] = True
        (target / "events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
        before = files(target)
        native = Native(binary)
        response = native.call(resume_request(target, model, calibration), expect_error=True)
        if before != files(target):
            raise ValueError("Rejected restore changed durable evidence")
        write(target / "REJECTION_TRANSCRIPT.json", native.transcript)
        native.finish()
        mutations[mode] = {"rejected": True, "durable_files_unchanged": True, "response": response}
    transcripts = [json.loads((output / name).read_text()) for name in
        ("LIVE_TRANSCRIPT.json", "RESTORE_TRANSCRIPT.json", "FORK_TRANSCRIPT.json")]
    responses = [r for transcript in transcripts for r in transcript]
    charged = sum(int(r["response"]["result"]["native_transition_executed"]) for r in responses
        if r["request"]["command"] == "Tick" and r["response"]["ok"])
    charged += sum(len(r["response"]["result"]["ticks"]) for r in responses if r["request"]["command"] == "Forecast")
    duplicate_responses = [r for r in responses if r["request"]["command"] == "Tick"
        and r["response"]["ok"] and r["response"]["result"]["duplicate_event_ignored"]]
    result = {"schema": "hepta.continuation.durable-event-validation.v2", "passed": True,
        "checks": checks, "restore_mutations": mutations, "actual_original_owner_ticks": charged,
        "acknowledged_duplicate_rpc_count": len(duplicate_responses), "duplicate_native_ticks": 0,
        "duplicate_rpc_physical_receipt_processing_micros": sum(r["response"]["physical_receipt_processing_micros"] for r in duplicate_responses),
        "all_rpc_physical_receipt_processing_micros": sum(r["response"]["physical_receipt_processing_micros"] for r in responses),
        "acknowledged_feedback": acknowledged, "cold_restored_state": restored,
        "later_hold": hold, "later_decision": decision, "actual_repaired_readback": repaired,
        "fork_preserved_parent": branch["committed_parent_unchanged"],
        "power_loss_simulated": False, "single_writer_only": True,
        "commit_gap_policy": "Reject restore; preserve evidence; do not silently rerun an event",
        "production_authority": False}
    write(output / "RESULT.json", result)
    print(json.dumps({key: value for key, value in result.items() if key in
        ("passed", "actual_original_owner_ticks", "acknowledged_duplicate_rpc_count", "duplicate_native_ticks", "fork_preserved_parent")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "model", "calibration", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    validate(args.binary.resolve(), args.model.resolve(), args.calibration.resolve(), args.output.resolve())
