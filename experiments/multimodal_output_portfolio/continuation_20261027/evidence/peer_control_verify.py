"""Read-only cross-check of completed owner run002 and durable guard receipts.

This reads frozen evidence. It does not rerun models, change a qualification,
or repackage the separately frozen joint-likelihood archive.
"""
import argparse
from collections import defaultdict
import datetime
import hashlib
from itertools import product
import json
import math
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def key(row):
    return (row["cue"], row["expires"], row["media_budget"], row["arm"], row["realized_transport_fault"])


def verify(root, output):
    run = root / "native_owner_run_20261027_002"
    old = root / "native_owner_run_20261027_001"
    guard = root / "native_owner_guard_20261027_001"
    build = root / "native_owner_build_20261027"
    repo = root / "hepta-private-ci"
    p, frozen, result, rows = map(read, [run / n for n in ("PROTOCOL.json", "FROZEN.json", "RESULT.json", "ROWS.json")])
    bykey, oldrows = {key(r): r for r in rows}, {key(r): r for r in read(old / "ROWS.json")}
    expected = set(product(range(4), p["expiry_contexts"], p["media_budget_contexts"], p["arms"], range(3)))
    assert len(bykey) == len(rows) == 240 and set(bykey) == expected
    assert len(result["groups"]) == 80
    assert {k[:4] for k in expected} == {(r["cue"], r["expires"], r["media_budget"], r["arm"]) for r in result["groups"]}
    assert all(sha(run / "executed-sources" / n) == h for n, h in frozen["sources"].items())
    for name, field in (("PROTOCOL.json", "protocol_sha256"), ("MODEL.json", "model_sha256"),
                        ("ENCODER_DOMAIN_PROOF.json", "calibration_sha256"), ("COMMON_ROOT_TABLE.json", "common_root_table_sha256")):
        assert sha(run / name) == frozen[field]
    receipt = read(build / "BUILD-v2_RECEIPT.json")
    assert receipt["binary_sha256"] == frozen["binary_sha256"] == sha(receipt["binary"])
    assert all(sha(repo / n) == h for n, h in receipt["source_sha256"].items())
    for name in ("owner_host.rs", "events.rs", "port.rs", "profile.rs"):
        assert sha(build / "hepta-neuron/examples" / name) == frozen["sources"][name]
    files, groups, changes, prices = set(), defaultdict(lambda: [0., 0., 0., 0.]), [], []
    count = extra = statechanged = proposalchanged = actionchanged = deniedchanged = 0
    maxcost = maxutility = maxmetric = 0.
    oldbytes = True
    for row in rows:
        assert read(run / "evaluation" / row["name"] / "EPISODE.json") == row
        ticks, initial, final = row["actual_continuation_ticks"], row["initial_observed"], row["final_observed"]
        fault = initial["fault_class"]
        assert fault == row["realized_transport_fault"]
        assert initial["codes"]["text"] == final["codes"]["text"] == row["action"]
        assert row["actual_original_owner_executed"] and not row["native_owner_granted_action_authority"] and not row["production_authority"]
        wanted = 0 if row["arm"] == "risk_zero" else p["numeric_feedback_by_fault"][fault]
        assert ticks[0]["feedback_q24"] == round(wanted * (1 << 24))
        assert [t["feedback_q24"] for t in ticks[1:]] == [0, 0]
        assert all(t["owner_authority"] == "DENY_ALL" for t in ticks + row["actual_root_ticks"])
        allowed = all(not t["native_abstain"] for t in ticks)
        proposed = fault != 0 if row["arm"] == "risk_history" else ticks[-1]["proposed_repair"]
        executed = bool(allowed and row["media_budget"] >= 2 and proposed)
        denied = bool(proposed and not executed)
        assert (executed, denied) == (row["executed_repair"], row["denied_attempt"])
        transcript = read(run / "evaluation" / row["name"] / "TRANSCRIPT.json")
        owner_steps = replays = 0
        for item in transcript:
            if item["request"]["command"] == "Tick":
                owner_steps += int(item["response"]["result"]["native_transition_executed"])
            if item["request"]["command"] == "Forecast":
                branch = item["response"]["result"]
                owner_steps += len(branch["ticks"])
                assert branch["start"]["sequence"] == branch["ledger_validation_kernel_steps"] == branch["original_journal_replayed_prefix_steps"] == 4
                replays += 8
        assert owner_steps == row["actual_native_ticks_including_planning"] == 16
        assert replays == 24 and row["total_original_sparse_kernel_executions"] == 40
        count += owner_steps
        extra += replays
        cost = p["initial_action_cost"][row["action"]] + p["channel_cost_by_fault"][fault]
        cost += owner_steps * p["native_tick_charge"] + replays * p["verification_replay_step_charge"]
        cost += p["repair_cost"] if executed else p["denied_repair_attempt_cost"] if denied else 0
        maxcost = max(maxcost, abs(cost - row["complete_task_charge"]))
        utility = [u - p["irreversible_first_delivery_damage"][fault] - p["terminal_mismatch_penalty"][final["fault_class"]] - cost
                   for u in p["semantic_utility_action_by_target"][final["codes"]["text"]]]
        maxutility = max(maxutility, max(abs(a - b) for a, b in zip(utility, row["return_by_private_target"])))
        mass, target = p["fault_law_by_action"][row["action"]][fault], p["target_law_by_cue"][row["cue"]]
        aggregate = groups[key(row)[:4]]
        aggregate[0] += sum(mass * t * math.exp(-p["gamma"] * u) for t, u in zip(target, utility))
        aggregate[1] += sum(mass * t * u for t, u in zip(target, utility))
        aggregate[2] += sum(mass * t * s for t, s in zip(target, row["strict_by_private_target"]))
        aggregate[3] += mass * cost
        for stage in ("initial", "final"):
            for kind, path in row[stage + "_paths"].items():
                path = Path(path)
                assert path.resolve().is_relative_to(run.resolve())
                assert sha(path) == row[stage + "_observed"]["media_sha256"][kind]
                files.add(str(path))
        prior = oldrows[key(row)]
        assert all(row[f] == prior[f] for f in ("action", "proposed_repair", "executed_repair"))
        oldbytes &= final["media_sha256"] == prior["final_observed"]["media_sha256"]
        prices.append(row["complete_task_charge"] - prior["complete_task_charge"])
        if row["arm"] == "risk_numeric":
            zero = bykey[(row["cue"], row["expires"], row["media_budget"], "risk_zero", fault)]
            assert row["action"] == zero["action"]
            statechanged += ticks[-1]["eligibility_before_q24"] != zero["actual_continuation_ticks"][-1]["eligibility_before_q24"]
            actionchanged += row["executed_repair"] != zero["executed_repair"]
            proposalchanged += row["proposed_repair"] != zero["proposed_repair"]
            deniedchanged += row["denied_attempt"] != zero["denied_attempt"]
            if row["proposed_repair"] != zero["proposed_repair"]:
                changes.append({"cue": row["cue"], "expires": row["expires"], "budget": row["media_budget"], "fault": fault,
                    "actual_repair_changed": row["executed_repair"] != zero["executed_repair"],
                    "denied_attempt_changed": row["denied_attempt"] != zero["denied_attempt"],
                    "return_difference_by_target": [a - b for a, b in zip(row["return_by_private_target"], zero["return_by_private_target"])]})
    for row in result["groups"]:
        values = groups[(row["cue"], row["expires"], row["media_budget"], row["arm"])]
        for value, name in zip(values, ("actual_moment", "actual_mean", "actual_strict_success", "actual_cost")):
            maxmetric = max(maxmetric, abs(value - row[name]))
            assert math.isclose(value, row[name], rel_tol=1e-12, abs_tol=1e-10)
    guard_freeze, guard_result = read(guard / "FROZEN_GUARD.json"), read(guard / "RESULT.json")
    assert all(guard_freeze[n] == frozen[n] for n in ("binary_sha256", "model_sha256", "calibration_sha256"))
    assert guard_freeze["guard_source_sha256"] == frozen["sources"]["guard.py"]
    duplicates = conflicts = 0
    for filename in ("LIVE_TRANSCRIPT.json", "RESTORE_TRANSCRIPT.json", "FORK_TRANSCRIPT.json"):
        transcript = read(guard / filename)
        for i, item in enumerate(transcript):
            if item["request"]["command"] != "Tick":
                continue
            if item["response"]["ok"] and item["response"]["result"]["duplicate_event_ignored"]:
                assert not item["response"]["result"]["native_transition_executed"]
                duplicates += 1
            elif not item["response"]["ok"]:
                assert "Conflicting retry" in item["response"]["error"]
                conflicts += 1
            else:
                continue
            assert transcript[i - 1]["request"]["command"] == transcript[i + 1]["request"]["command"] == "Status"
            assert transcript[i - 1]["response"]["result"] == transcript[i + 1]["response"]["result"]
    assert duplicates == 3 and conflicts == 5 and guard_result["duplicate_native_ticks"] == 0
    assert guard_result["later_hold"]["feedback_q24"] == guard_result["later_decision"]["feedback_q24"] == 0
    assert guard_result["later_decision"]["proposed_repair"] and not guard_result["later_decision"]["native_abstain"]
    assert guard_result["actual_repaired_readback"]["fault_class"] == 0
    for name, item in guard_result["restore_mutations"].items():
        rejection = read(guard / name / "REJECTION_TRANSCRIPT.json")
        assert len(rejection) == 1 and rejection[0]["request"]["command"] == "Resume"
        assert not rejection[0]["response"]["ok"] and item["rejected"] and item["durable_files_unchanged"]
    auditpath = root / "native_owner_audit_20261027_002/AUDIT.json"
    audit = read(auditpath)
    assert audit["passed"] and audit["auditor_source_sha256"] == frozen["sources"]["audit.py"]
    assert audit["result_sha256"] == sha(run / "RESULT.json")
    identities = [run / "FROZEN.json", run / "ROWS.json", run / "RESULT.json", build / "BUILD-v2_RECEIPT.json",
                  guard / "FROZEN_GUARD.json", guard / "RESULT.json", auditpath]
    report = {"schema": "hepta.ndu.peer-control-run002-review.v1", "reviewed_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "Read-only grid, byte identity, transcript and arithmetic check. The existing independent auditor separately decodes media and replays original owner. No new qualification or threshold change.",
        "reviewer_source_sha256": sha(__file__), "run": str(run), "identity_files": {str(p): sha(p) for p in identities},
        "frozen_source_and_artifact_hashes_valid": True, "compiled_source_files_match_build_and_frozen_snapshot": True,
        "binary_sha256": frozen["binary_sha256"], "exact_unique_episode_grid": 240, "exact_unique_group_grid": 80,
        "actual_media_files_rehashed": len(files), "native_owner_calls": count, "additional_restore_kernel_calls": extra,
        "total_sparse_kernel_calls": count + extra, "maximum_cost_error": maxcost, "maximum_terminal_utility_error": maxutility,
        "maximum_aggregate_metric_error": maxmetric, "executed_behavior_and_delivered_bytes_equal_run001": oldbytes,
        "per_episode_cost_increase_vs_run001_range": [min(prices), max(prices)],
        "cost_increase_decomposition": {"previously_unpriced_original_journal_replays": .0012, "new_event_binding_validation": .0012},
        "paired_numeric_zero_cases": 48, "late_eligibility_changed": statechanged, "repair_proposal_changed": proposalchanged,
        "executed_repair_changed": actionchanged, "denied_attempt_changed": deniedchanged, "consequential_feedback_cases": changes,
        "feedback_benefit_interpretation": "Avoids four unnecessary actual repairs and twelve unnecessary denied attempts, all in fault-zero cases; no repair change on fault1/2. Mean gain0.036375 under registered law, no strict-success gain. Same-information history policy matches numeric return.",
        "guard_duplicate_receipts_without_state_transition": duplicates, "guard_conflicting_live_cold_fork_retries_rejected": conflicts,
        "guard_mutated_restore_rejections_verified": sorted(guard_result["restore_mutations"]), "guard_post_cold_restore_real_later_repair": True,
        "guard_limits": ["Single writer and registered event-ID dispatcher; same physical event assigned a new ID is not deduplicated by content.",
            "Original-kernel transition idempotency does not establish exactly-once external media dispatch.",
            "Cold EOF process restore and deterministic corruptions tested; physical power loss and concurrent writers not tested.",
            "Commit-without-complete-ledger gap fails closed and requires forensic recovery; availability across all crash points not established."],
        "independent_audit_passed": True, "production_semantic_qualification": False}
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("identity_files", "consequential_feedback_cases", "guard_limits")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify(args.root.resolve(), args.output.resolve())
