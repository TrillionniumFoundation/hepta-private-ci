"""Gate 1: reconcile actual forward rows, batches, reuse and complete schedules.

This checks trace consistency. It never upgrades an unsigned Python trace into
native Worker/Artifact CAS evidence and never assumes joint/state model parity.
"""
from itertools import product
import math

from four_gate_common import (
    digest, integer, lifecycle, number, percentile, require, result, sha, text,
)

SCALES = (64, 256, 1024, 4096)
ACTIVE_BPS = (500, 2500, 10000)
REPEAT_BPS = (0, 5000, 9000)
ARMS = ("no_change", "joint_batch", "feature_reuse")


def workload_key(cells, active, repeat):
    return f"{cells}:{active}:{repeat}"


def encoding_key(row, arm, pipeline):
    return digest([row["principal"], row["scope"], row["purpose"],
                   row["generation"], row["authority_epoch"], pipeline,
                   row["state_sha256"] if arm == "feature_reuse" else row["joint_sha256"]])


def measure_arm(arm, schedule, sample, plan):
    require(sample["source_sha"] == plan["source_sha"], "compute source SHA drift")
    sha(sample["pipeline_sha256"])
    sha(sample["weights_sha256"])
    require(sample["weights_sha256"] == sha(plan["compute"]["arm_weights_sha256"][arm]),
            "compute arm is not the frozen original model")
    totals = lifecycle(sample["lifecycle"], plan["required_cost_axes"])
    number(sample["peak_rss_bytes"], "measured peak RSS", 1)
    integer(sample["resident_stem_copies"], "resident Stem copies", 1, 4096)
    forward = {}
    scheduled_keys = {encoding_key(row, arm, sample["pipeline_sha256"]) for row in schedule}
    for event in sample["encoder_forwards"]:
        event_id = text(event["id"], "encoder event")
        require(event_id not in forward, "duplicate physical Encoder call")
        require(type(event["keys"]) is list and 0 < len(event["keys"]) <= 4096,
                "empty or oversized native batch")
        require(all(key in scheduled_keys for key in event["keys"]),
                "Encoder key not bound to complete admitted input")
        integer(event["token_count"], "actual tokens", 1, 1_000_000_000)
        integer(event["start_ns"], "forward start", 0, 2**63 - 1)
        integer(event["end_ns"], "forward end", event["start_ns"], 2**63 - 1)
        forward[event_id] = event
    require(bool(forward), "no actual Encoder executions")
    observed = {}
    used_slots = set()
    latencies = []
    successes = 0
    for request in sample["requests"]:
        rid = request["request_id"]
        require(rid not in observed, "duplicate terminal request")
        observed[rid] = request
    require(set(observed) == {row["request_id"] for row in schedule},
            "missing/cancelled/failed requests may not disappear")
    for row in schedule:
        request = observed[row["request_id"]]
        require(request["cell_id"] == row["cell_id"], "Cell dispatch identity drift")
        require(request["outcome"] in ("succeeded", "failed", "cancelled", "indeterminate"),
                "unknown terminal state")
        start = integer(request["start_ns"], "request start", 0, 2**63 - 1)
        end = integer(request["end_ns"], "request end", start, 2**63 - 1)
        event = forward.get(request["encoder_event_id"])
        require(event is not None, "request has no physical Encoder dependency")
        slot = integer(request["encoder_slot"], "Encoder slot", 0, len(event["keys"]) - 1)
        require(event["end_ns"] <= end and
                event["keys"][slot] == encoding_key(row, arm, sample["pipeline_sha256"]),
                "reuse crosses scope/generation/input or occurs before computation")
        slot_id = (event["id"], slot)
        if arm != "feature_reuse":
            require(slot_id not in used_slots, "joint/no-change arm secretly reuses features")
        used_slots.add(slot_id)
        latencies.append(end - start)
        successes += request["outcome"] == "succeeded"
    duration = sample["lifecycle"]["inference"]["cost"]["wall_ns"]
    number(duration, "inference wall time", 1)
    require(duration >= max(r["end_ns"] for r in observed.values()) -
            min(r["start_ns"] for r in observed.values()), "truncated end-to-end wall time")
    return {
        "requests": len(schedule), "successful_requests": successes,
        "encoder_calls": len(forward),
        "encoder_rows": sum(len(e["keys"]) for e in forward.values()),
        "encoded_tokens": sum(e["token_count"] for e in forward.values()),
        "unique_admitted_inputs": len(scheduled_keys),
        "reused_requests": len(schedule) - len(used_slots),
        "feature_reuse_rate": (len(schedule) - len(used_slots)) / len(schedule),
        "p99_end_to_end_ns_all_outcomes": percentile(latencies, .99),
        "throughput_success_rps": successes * 1e9 / duration,
        "peak_rss_bytes": sample["peak_rss_bytes"],
        "resident_stem_copies": sample["resident_stem_copies"],
        "lifecycle_cost": totals,
    }


def review_compute(plan, evidence):
    require(evidence["schema"] == "hepta.four-gate.compute-traces.v1", "compute schema")
    cfg = plan["compute"]
    expected = {workload_key(*values) for values in product(SCALES, ACTIVE_BPS, REPEAT_BPS)}
    require(set(cfg["schedule_sha256s"]) == expected, "full frozen 36-workload matrix required")
    workloads = evidence["workloads"]
    require(type(workloads) is list and len(workloads) == len(expected), "incomplete compute matrix")
    seen = set()
    metrics = {}
    passes = []
    repeated_savings = []
    for workload in workloads:
        key = workload_key(workload["cells"], workload["active_bps"], workload["repeat_bps"])
        require(key in expected and key not in seen, "duplicate or unsupported workload")
        seen.add(key)
        schedule = workload["schedule"]
        require(type(schedule) is list and 0 < len(schedule) <= 100_000, "empty/oversized schedule")
        require(digest(schedule) == sha(cfg["schedule_sha256s"][key]), "precommitted schedule drift")
        request_ids = set()
        cells = set()
        for row in schedule:
            text(row["request_id"], "request id")
            require(row["request_id"] not in request_ids, "duplicate planned request")
            request_ids.add(row["request_id"])
            integer(row["cell_id"], "Cell id", 0, workload["cells"] - 1)
            cells.add(row["cell_id"])
            for field in ("principal", "scope", "purpose"):
                text(row[field], field)
            for field in ("generation", "authority_epoch"):
                integer(row[field], field, 1, 2**63 - 1)
            for field in ("state_sha256", "joint_sha256"):
                sha(row[field])
        require(len(cells) == math.ceil(workload["cells"] * workload["active_bps"] / 10000),
                "actual active Cell coverage does not match the registered scale")
        unique_states = {encoding_key(row, "feature_reuse", "1" * 64) for row in schedule}
        expected_unique = max(1, round(len(schedule) * (1 - workload["repeat_bps"] / 10000)))
        require(len(unique_states) == expected_unique, "actual scoped input-repeat ratio does not match plan")
        samples = workload["arms"]
        require(set(samples) == set(ARMS), "three compute controls required")
        require(len({(s["host_sha256"], s["environment_sha256"]) for s in samples.values()}) == 1,
                "unpaired host or runtime environment")
        for sample in samples.values():
            sha(sample["host_sha256"])
            sha(sample["environment_sha256"])
        require(samples["joint_batch"]["weights_sha256"] == samples["feature_reuse"]["weights_sha256"],
                "shared computation comparison changed the Encoder weights")
        measurements = {arm: measure_arm(arm, schedule, samples[arm], plan) for arm in ARMS}
        joint, shared = measurements["joint_batch"], measurements["feature_reuse"]
        parity = all(m["successful_requests"] == m["requests"] for m in measurements.values())
        resource_ok = (shared["p99_end_to_end_ns_all_outcomes"] <= cfg["p99_ceiling_ns"] and
                       shared["peak_rss_bytes"] <= cfg["rss_ceiling_bytes"] and
                       shared["throughput_success_rps"] >= cfg["throughput_floor_rps"] and
                       shared["p99_end_to_end_ns_all_outcomes"] <=
                       joint["p99_end_to_end_ns_all_outcomes"] * cfg["max_p99_ratio"])
        passes.append(parity and resource_ok)
        if workload["repeat_bps"] > 0:
            repeated_savings.append(shared["encoder_rows"] < joint["encoder_rows"])
        metrics[key] = {"arms": measurements, "all_terminal_success": parity,
                        "resource_caps_met": resource_ok,
                        "joint_state_quality_equivalence_assumed": False}
    return result(all(passes) and any(repeated_savings), metrics,
                  [] if all(passes) and any(repeated_savings) else
                  ["full matrix resource/terminal/reuse requirements not met"])
