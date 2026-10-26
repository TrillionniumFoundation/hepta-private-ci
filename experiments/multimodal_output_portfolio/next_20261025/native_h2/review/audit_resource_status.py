"""Independent journal-to-process census for the preserved H2 resource addendum."""

from collections import Counter
import hashlib
import json
from pathlib import Path


ROOT = Path("/tmp/hepta-ndu-next-native-h2/confirm-001")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def main():
    addendum = read(ROOT / "RESOURCE_STATUS_ADDENDUM.json")
    actual = read(ROOT / "results.json")
    primary = read(ROOT / "AUDIT.json")
    assert sha(ROOT / "results.json") == addendum["original_results_sha256"]
    assert sha(ROOT / "AUDIT.json") == addendum["original_audit_sha256"]
    assert sha(ROOT.parent / "resource_status_addendum.py") == addendum["source_sha256"]
    assert sha(addendum["resource_function_path"]) == addendum["resource_function_sha256"]
    output, totals, evidence = {}, Counter(), {}
    for policy in ("ndu", "correctness"):
        journal = ROOT / policy / "state/control.jsonl"
        evidence[str(journal)] = sha(journal)
        events = [json.loads(line)["event"] for line in journal.read_text().splitlines()]
        decisions = [event for event in events if event["kind"] == "decision"]
        receipts = {}
        for decision in decisions:
            assert len(decision["candidates"]) == 5
            sequences = []
            for candidate in decision["candidates"]:
                sequence = candidate["native_sequence"]
                assert sequence not in receipts
                receipts[sequence] = candidate
                sequences.append(sequence)
            assert sequences == list(range(decision["native_sequence"] - 4, decision["native_sequence"] + 1))
        assert list(receipts) == list(range(1, len(receipts) + 1))
        assert len(receipts) == primary["execution"][policy]["native_forwards"]
        assert len(decisions) == primary["execution"][policy]["decisions"]
        statuses = actual["process_status"][policy]
        recoveries = [row for row in actual["recoveries"] if row["policy"] == policy]
        assert len(statuses) == 3 and len(recoveries) == 2
        assert Counter(row["kind"] for row in recoveries) == {"abrupt_pending_H2_decision": 1, "graceful_observed_H2_before_H1": 1}
        recoveries = {row["kind"]: row for row in recoveries}
        covered, frontier, processes = set(), 0, []
        for index, status in enumerate(statuses):
            endpoint = status["native_sequence"]
            indices = set(range(frontier + 1, endpoint + 1))
            assert not covered.intersection(indices)
            covered.update(indices)
            assert len(indices) == status["ticks_in_process"] == status["model_forwards_in_process"]
            assert status["training_steps"] == 0
            record = {"index": index, "frontier_before": frontier, "frontier_after": endpoint, "sample_count": len(indices)}
            recorded = addendum["policies"][policy]["processes"][index]
            assert (recorded["native_frontier_before"], recorded["native_frontier_after"], recorded["ticks"]) == (frontier, endpoint, len(indices))
            if not indices:
                assert index == 1 and frontier == endpoint == 5
                assert status["native_resource_summary"] is None and status["native_resource_summary_passed"] is None
                assert status["pending"] is None and status["episodes"]["pending"] is None
                assert status["episodes"]["continuation"] is not None
                first, second = recoveries["abrupt_pending_H2_decision"], recoveries["graceful_observed_H2_before_H1"]
                assert first["before"] == first["after"] and second["before"] == second["after"]
                assert first["after"]["native_sequence"] == second["before"]["native_sequence"] == endpoint
                assert first["after"]["anchor"] == second["before"]["anchor"] == status["anchor"] == statuses[0]["anchor"]
                assert first["after"]["requests"] == second["before"]["requests"] == status["requests"] == 1
                assert first["after"]["outcomes"] + 1 == second["before"]["outcomes"] == status["outcomes"] == 1
                assert recorded["qualified_performance_sample"] is False
                record["classification"] = "not_applicable_zero_ticks"
                totals["zero_tick_processes"] += 1
            else:
                sample = [receipts[sequence] for sequence in sorted(indices)]
                execution = sorted(row["native_execution_micros"] for row in sample)
                n = len(sample)
                reconstructed = {"sample_count": n,
                    "p95_execution_micros": execution[(95 * n + 99) // 100 - 1],
                    "p99_execution_micros": execution[(99 * n + 99) // 100 - 1],
                    "maximum_transient_allocation_bytes": max(row["native_transient_bytes"] for row in sample),
                    "maximum_checkpoint_bytes": max(row["native_checkpoint_bytes"] for row in sample),
                    "maximum_write_amplification_ppm": max(row["native_write_amplification_ppm"] for row in sample)}
                assert all(status["native_resource_summary"][key] == value for key, value in reconstructed.items())
                assert reconstructed == recorded["summary_reproduced_from_every_candidate_receipt"]
                ceilings = {"p95_execution_micros": 3000, "p99_execution_micros": 8000,
                    "maximum_transient_allocation_bytes": 524288, "maximum_checkpoint_bytes": 1048576,
                    "maximum_write_amplification_ppm": 4000000}
                assert all(reconstructed[key] <= bound for key, bound in ceilings.items())
                assert status["native_resource_summary_passed"] is True
                assert status["native_resource_summary"]["pilot_ceiling_passed_for_supplied_samples"] is True
                record.update(classification="original_resource_ceilings_pass", reconstructed=reconstructed)
                totals["measured_processes"] += 1
            processes.append(record)
            frontier = endpoint
        assert covered == set(receipts) and frontier == len(receipts)
        assert sum(status["ticks_in_process"] for status in statuses) == len(receipts)
        assert statuses[-1]["requests"] == len(decisions)
        assert primary["execution"][policy]["all_process_resource_summaries_pass"] is False
        assert addendum["policies"][policy]["original_all_process_boolean_preserved"] is False
        totals["decisions"] += len(decisions); totals["timed_candidate_ticks"] += len(receipts)
        output[policy] = {"decisions": len(decisions), "candidate_ticks": len(receipts),
                          "all_ticks_covered_once": True, "processes": processes}
    assert totals == {"zero_tick_processes": 2, "measured_processes": 4, "decisions": 708, "timed_candidate_ticks": 3540}
    assert actual["actual_owner_decisions"] == totals["decisions"] == addendum["actual_decisions"]
    assert totals["timed_candidate_ticks"] == addendum["actual_timed_candidate_ticks"]
    assert addendum["quality_CI_or_thresholds_changed"] is False and addendum["all_six_processes_measured_or_passed_claimed"] is False
    result = {"schema": "hepta.next.native-h2-independent-resource-review.v1", "status": "passed",
              "audit_source_sha256": sha(__file__), "resource_addendum_sha256": sha(ROOT / "RESOURCE_STATUS_ADDENDUM.json"),
              "original_results_sha256": sha(ROOT / "results.json"), "original_audit_sha256": sha(ROOT / "AUDIT.json"),
              "journal_sha256": evidence, "totals": dict(totals), "policies": output,
              "original_files_or_gates_changed": False, "model_or_native_execution_rerun": False,
              "scope": "Native tick resource receipts only. Zero-tick processes are N/A. Original primary quality and whole Python/model-service cost results remain unchanged."}
    destination = Path(__file__).resolve().parent / "RESOURCE_STATUS_REVIEW.json"
    with destination.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True); stream.write("\n")
    print(json.dumps({"status": "passed", "totals": dict(totals), "review_sha256": sha(destination)}))


if __name__ == "__main__":
    main()
