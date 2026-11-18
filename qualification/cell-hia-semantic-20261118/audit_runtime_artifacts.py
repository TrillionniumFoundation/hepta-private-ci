#!/usr/bin/env python3
"""Read retained CI artifacts without importing or executing their source code.

Audits exact bytes, protocol transcripts and SQLite snapshots. Workflow status
comes from separately fetched GitHub metadata; a local audit never promotes it.
All output must be outside the supplied original artifact directory.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import stat
import sys


def require(condition, message):
    if not condition:
        raise ValueError(message)


def strict(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "duplicate JSON member")
            value[key] = item
        return value

    def nonfinite(_):
        raise ValueError("nonfinite JSON constant")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def file_sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inventory(root):
    result = {}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        require(not stat.S_ISLNK(info.st_mode), "original artifact contains a symlink")
        if path.is_file():
            result[str(path.relative_to(root))] = {
                "bytes": info.st_size, "sha256": file_sha(path),
                "mode": stat.S_IMODE(info.st_mode), "mtime_ns": info.st_mtime_ns,
                "ctime_ns": info.st_ctime_ns, "inode": info.st_ino, "device": info.st_dev,
            }
    return result


class Audit:
    def __init__(self, root):
        self.root = root
        self.reads = {}

    def raw(self, name):
        path = (self.root / name).resolve(strict=True)
        require(path.is_relative_to(self.root), "read escapes original artifacts")
        raw = path.read_bytes()
        self.reads[str(path.relative_to(self.root))] = sha(raw)
        return raw

    def json(self, name):
        return strict(self.raw(name))

    def digest(self, name):
        return sha(self.raw(name))

    def database(self, name):
        path = self.root / name
        wal = Path(str(path) + "-wal")
        require(not wal.exists() or wal.stat().st_size == 0, "nonempty WAL cannot be ignored")
        checksum = self.digest(name)
        connection = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
        try:
            phases = dict(connection.execute("SELECT phase, COUNT(*) FROM hia_cell_calls GROUP BY phase"))
            intents = dict(connection.execute("SELECT status, COUNT(*) FROM intents GROUP BY status"))
        finally:
            connection.close()
        return {"sha256": checksum, "native_phases": phases, "intent_statuses": intents,
                "read_mode": "read-only immutable; nonempty WAL refused"}


def unwrap(record):
    request, response = record["request"], record["response"]
    require(response.get("id") == request.get("id") and "error" not in response, "RPC identity or error differs")
    result = response["result"]
    require(result.get("isError") is not True, "runtime tool error")
    if isinstance(result.get("structuredContent"), dict):
        return result["structuredContent"]
    values = [strict(row["text"]) for row in result.get("content", []) if row.get("type") == "text"]
    require(len(values) == 1 and isinstance(values[0], dict), "runtime observation is ambiguous")
    return values[0]


def proof(status, job):
    require(status.get("job_id") == job, "runtime status names another job")
    if status.get("state") not in ("succeeded", "failed", "cancelled", "timed_out"):
        return None
    require(status.get("status_authoritative") is not False and status.get("effect_outcome") != "unknown" and status.get("outcome") != "unknown", "terminal status is not authoritative")
    require(status.get("terminal_publication_protocol") == 1 and all(status.get(key) is True for key in ("terminal_publication_confirmed", "output_complete", "output_durable")), "terminal publication is incomplete")
    require(type(status.get("exit_code")) is int and type(status.get("timed_out")) is bool and type(status.get("cancelled")) is bool, "terminal outcome flags are incomplete")
    expected_state = "timed_out" if status["timed_out"] else "cancelled" if status["cancelled"] else "succeeded" if status["exit_code"] == 0 else "failed"
    require(status["state"] == expected_state, "terminal outcome flags disagree")
    counts = {}
    for stream in ("stdout", "stderr"):
        item = status["log_bytes"][stream]
        require(type(item["stored"]) is int and item["stored"] >= 0 and item["stored"] == item["seen"], "terminal byte count differs")
        require(status["log_truncated"][stream] is False and status["log_errors"][stream] is None and status["log_synced"][stream] is True, "terminal stream is truncated or unsynced")
        counts[stream] = item["stored"]
    return {"state": status["state"], "exit_code": status["exit_code"], "launch_nonce": status["launch_nonce"], "at_unix_ms": status["at_unix_ms"], "counts": counts}


def audit_lane(audit, report_name, profile, candidate_hash, runtime_pins, expected_request):
    report = audit.json(report_name)
    require(report["status"] == "PASS" and report["candidate_sha256"] == candidate_hash, "lane status/candidate mismatch")
    first, cold = report["first_observation"], report["recovered_observation"]
    require(first == cold and first["state"] == "TERMINAL" and first["runtime_state"] == "succeeded" and first["exit_code"] == 0, "cold observation differs or original job failed")
    require(first["automatic_replay"] is False and first["request_id"] == expected_request["request_id"], "request or replay policy differs")
    expected = {name: bytes.fromhex(row["bytes_hex"]) for name, row in first["streams"].items()}
    for name, raw in expected.items():
        require(len(raw) == first["streams"][name]["bytes"] == first["terminal_proof"]["counts"][name], "stream length differs")
        require(sha(raw) == first["streams"][name]["sha256"], "stream digest differs")
    domain = strict(expected["stdout"])
    domain_request = domain.get("request_id", domain.get("result", {}).get("request_id"))
    require(domain == report["worker_result"] and domain["candidate_sha256"] == candidate_hash and domain_request == expected_request["request_id"], "stdout JSON differs from retained worker observation")
    require(len(report["sessions"]) == 2, "two controller sessions required")
    sessions = []
    for index, session in enumerate(report["sessions"]):
        identity = session["runtime"]
        require(identity["transport"] == "actual_mcp_stdio", "non-runtime transport")
        for left, right in (("runtime_source_commit", "source_commit"), ("runtime_binary_sha256", "binary_sha256"), ("runtime_config_sha256", "config_sha256")):
            require(identity[left] == runtime_pins[right], "session runtime pin differs")
        require(sha(canonical({"profile": profile, "runtime": identity})) == first["profile_sha256"], "frozen runtime/profile binding differs")
        records = session["protocol"]
        initializes = [record for record in records if record["request"].get("method") == "initialize"]
        require(len(initializes) == 1 and initializes[0]["request"]["id"] == 1, "session lacks a fresh initialization")
        calls = [record for record in records if record["request"].get("method") == "tools/call"]
        counts = Counter(record["request"]["params"]["name"] for record in calls)
        require(counts["process_start"] == (1 if index == 0 else 0) and counts["process_status"] >= 2 and counts["process_read"] >= 1, "submission or cold fresh-read counts differ")
        streams = {name: bytearray() for name in expected}
        terminal_count = 0
        for record in calls:
            name, arguments = record["request"]["params"]["name"], record["request"]["params"]["arguments"]
            value = unwrap(record)
            if name == "process_start":
                job = value["job"]
                require(job["id"] == first["job_id"] and strict(arguments["stdin"]) == expected_request, "original launch/request differs")
                normalized = {key: arguments.get(key) for key in ("args", "cpu_quota_percent", "cwd", "env", "executable", "host", "memory_max_bytes", "nice", "stdin", "timeout_seconds")}
                normalized["args"], normalized["env"] = arguments.get("args", []), arguments.get("env", {})
                require(job["request_digest"] == sha(canonical(normalized)), "runtime normalized launch digest differs")
                require(job["idempotency_key"] == arguments["idempotency_key"] and all(arguments[key] == profile["process"][key] for key in profile["process"]), "fixed process profile changed")
            elif name == "process_status":
                observed = proof(value, first["job_id"])
                if observed is not None:
                    require(observed == first["terminal_proof"], "terminal nonce/count/proof changed")
                    terminal_count += 1
            elif name == "process_read":
                require(value["job_id"] == first["job_id"] and arguments["job_id"] == first["job_id"], "read page names another job")
                for stream in streams:
                    page, offset = value[stream], len(streams[stream])
                    raw = bytes.fromhex(page["bytes_hex"])
                    require(arguments[stream + "_offset"] == offset == page["offset"], "read cursor skipped or replayed bytes")
                    require(page["size"] == len(expected[stream]) and page["next_offset"] == offset + len(raw) and len(raw) <= arguments["limit"] <= 16384, "read page size differs")
                    require(page["eof"] is (offset + len(raw) == page["size"]), "read end marker differs")
                    streams[stream].extend(raw)
            else:
                raise ValueError("unexpected tool in successful lane: " + name)
        require(terminal_count >= 2 and all(bytes(streams[name]) == expected[name] for name in streams), "protocol pages do not reproduce original terminal bytes")
        sessions.append({"phase": "original" if index == 0 else "cold_controller", "calls": {name: counts[name] for name in ("process_start", "process_status", "process_read")}, "fresh_initialize": True, "terminal_proofs_equal": terminal_count, "reassembled_streams_equal": True, "runtime_tools_sha256": identity["runtime_tools_sha256"]})
    return report, domain, {
        "job_id": first["job_id"], "request_id": first["request_id"], "host": first["host"],
        "candidate_sha256": candidate_hash, "profile_sha256": first["profile_sha256"],
        "status": report["status"], "runtime_state": first["runtime_state"],
        "sessions": sessions, "original_equals_cold": True, "no_resubmission": True,
        "streams": {name: {"bytes": len(raw), "sha256": sha(raw), "metadata_and_protocol_verified": True} for name, raw in expected.items()},
        "stdout_equals_worker_observation": True,
        "reported_elapsed_seconds": report["elapsed_seconds"],
        "elapsed_scope": "outer runtime exercise including syntax and semantic subjobs" if report_name == "runtime-joint/result.json" else "one maintenance job and both controller sessions, including launch and original-output reads",
        "process_budget": {key: profile["process"].get(key) for key in ("timeout_seconds", "cpu_quota_percent", "memory_max_bytes")},
        "max_output_bytes": profile["max_output_bytes"],
    }


def audit_campaign(audit, prefix, domain, candidate_hash, runtime_pins, native_image):
    worker = "runtime-joint/" + prefix + "-worker"
    root = worker + "/campaign"
    require(audit.json(worker + "/OBSERVATION.json") == domain, "retained OBSERVATION differs from runtime stdout")
    require(audit.digest(worker + "/OUTER_CANDIDATE.json") == candidate_hash, "outer candidate original differs")
    result, plan = audit.json(root + "/RESULT.json"), audit.json(root + "/PLAN.json")
    result_hash, plan_hash = audit.digest(root + "/RESULT.json"), audit.digest(root + "/PLAN.json")
    require(result_hash == domain["campaign_result_sha256"] and result == domain["campaign_result"] and result["plan_sha256"] == plan_hash, "campaign original/result/plan binding differs")
    pins = {**runtime_pins, "origin_candidate_sha256": candidate_hash}
    require(audit.json(root + "/RUNTIME_PINS.json") == pins == audit.json(worker + "/RUNTIME_PINS.json") == plan["runtime_pins"]["identity"], "campaign runtime or candidate pin differs")
    require(audit.digest(root + "/RUNTIME_PINS.json") == plan["runtime_pins"]["sha256"], "campaign pin file digest differs")
    require(domain["runtime_identity"] == runtime_pins and domain["native_image_sha256"] == native_image == plan["native"]["image_sha256"] == audit.digest(root + "/native/cell_bridge.so"), "campaign native/runtime pin differs")
    rows = [strict(line) for line in audit.raw(root + "/compile.jsonl").splitlines()]
    require(len(rows) == result["compile_calls"], "compile row count differs")
    cells, completed, cold_compiles, cold_children, cold_checks = {}, 0, 0, 0, 0
    for cell, summary in result["cells"].items():
        directory = root + "/" + cell
        decision, evaluation = audit.json(directory + "/DECISION.json"), audit.json(directory + "/EVALUATION.json")
        served, cold = audit.json(directory + "/C_SERVED.json"), audit.json(directory + "/COLD_RESULT.json")
        cold_request, training = audit.json(directory + "/COLD_REQUEST.json"), audit.json(directory + "/TRAINING.json")
        require(decision == summary["decision"] and cold == summary["cold"] and training == summary["training"], "cell original differs from campaign summary")
        counts = {arm: sum(row["outcome"]["success"] for row in values) for arm, values in evaluation["B"].items()}
        require(counts == decision["B_successes"] and sum(row["outcome"]["success"] for row in served) == summary["C_successes"], "independent B or C counts differ")
        require(len(served) == summary["C_denominator"] and all(row["candidate_manifest_sha256"] == decision["selected_candidate_manifest_sha256"] for row in served), "C task served another version")
        require(cold["matches_pre_restart"] is True and cold["receipt"]["output"]["cell"]["logits"] == cold_request["expected_logits"] and cold["candidate_manifest_sha256"] == decision["selected_candidate_manifest_sha256"] and cold["pid"] != plan["parent_pid"], "cold process model/version/logits differ")
        for filename, expected in (("parent.npz", summary["parent_npz_sha256"]), ("candidate.npz", summary["candidate_npz_sha256"]), ("live.npz", cold_request["model_hash"])):
            require(audit.digest(directory + "/" + filename) == expected, "model checkpoint differs")
        db = audit.database(directory + "/owner.sqlite")
        require(db["native_phases"] == domain["native_counts"][cell] and set(db["native_phases"]) == {"completed"} and db["intent_statuses"].get("pending", 0) == 0, "native calls or pending campaign intents differ")
        completed += db["native_phases"]["completed"]
        info = {"decision": decision["decision"], "reason": decision["reason"], "B_successes": counts,
                "B_denominator": decision["denominator"], "A_retention": decision["A_retention"],
                "C_successes": summary["C_successes"], "C_denominator": len(served), "cold_exact": True,
                "native_completed": db["native_phases"]["completed"], "pending": 0,
                "selected_version_sha256": decision["selected_candidate_manifest_sha256"],
                "parent_weights_sha256": decision["parent_weights_sha256"], "candidate_weights_sha256": decision["candidate_weights_sha256"],
                "checkpoint_sha256": {name: audit.digest(directory + "/" + name) for name in ("parent.npz", "candidate.npz", "live.npz")},
                "training": {key: training[key] for key in ("data_sha256", "validated_updates", "requested_updates", "batch_episodes", "events_per_episode", "wall_seconds", "process_cpu_seconds", "measurement_scope")},
                "training_file_sha256": audit.digest(directory + "/A_TRAINING.npz"),
                "cold_wall_ns": cold["wall_ns"]}
        if "new_task" in cold:
            cold_rows = [strict(line) for line in audit.raw(directory + "/cold-compile.jsonl").splitlines()]
            outcome = cold["new_task"]["outcome"]
            require(outcome in cold_rows and cold["cold_compile_calls"] == len(cold_rows), "D-cold task has no matching original evaluation")
            cold_compiles += len(cold_rows)
            cold_semantic = [row["semantic"] for row in cold_rows if "child_pid" in row.get("semantic", {})]
            require(len(cold_semantic) == cold["semantic_subprocesses"], "cold semantic subprocess count differs")
            cold_children += len(cold_semantic)
            cold_checks += sum(len(row["child"].get("checks", [])) for row in cold_semantic)
            info["D_cold"] = {"task_id": outcome["task"], "success": outcome["success"], "compile_success": outcome["compile_success"], "semantic_status": outcome["semantic"]["status"], "compile_calls": len(cold_rows), "semantic_subprocesses": cold["semantic_subprocesses"]}
        cells[cell] = info
    windows = result["cost_observations"]["windows"]
    semantic_rows = [row for row in rows if "semantic" in row]
    semantic_children = [row["semantic"] for row in semantic_rows if "child_pid" in row["semantic"]]
    if "semantic_subprocesses" in result:
        require(len(semantic_children) == result["semantic_subprocesses"], "semantic subprocess count differs")
    return {
        "result_sha256": result_hash, "plan_sha256": plan_hash, "observation_sha256": audit.digest(worker + "/OBSERVATION.json"),
        "runtime_stdout_equals_retained_originals": True, "data_file_sha256": audit.digest(root + "/A_DATA.json"),
        "task_contracts_sha256": sha(canonical(plan.get("task_contracts", plan["panels"]))),
        "task_counts": {key: len(tasks) for key, tasks in plan["panels"].items()} | {"D_cold_per_cell": 1 if "cold_task" in plan else 0},
        "parent_compile_calls": len(rows), "cold_compile_calls": cold_compiles,
        "parent_semantic_child_processes": len(semantic_children), "cold_semantic_child_processes": cold_children,
        "total_semantic_child_processes": len(semantic_children) + cold_children,
        "parent_semantic_check_results": sum(len(row["child"].get("checks", [])) for row in semantic_children),
        "cold_semantic_check_results": cold_checks,
        "native_completed": completed, "cells": cells,
        "adopt": sum(cell["decision"] == "Adopt" for cell in cells.values()),
        "no_update": sum(cell["decision"] == "NoUpdate" for cell in cells.values()),
        "cost": {"wall_seconds": result["wall_seconds"], "parent_cpu_seconds": result["parent_cpu_seconds"], "scope": result["cost_scope"],
                 "window_count": len(windows), "window_stages": dict(Counter(row["stage"] for row in windows)),
                 "task_window_phases": dict(Counter(row.get("phase", "unspecified") for row in windows if row["stage"] == "task")),
                 "task_latency": {name: {key: row[key] for key in ("count", "observed_count", "missing_count", "observed_p95_ms", "observed_p99_ms")} for name, row in result["cost_observations"]["task_latency"].items()},
                 "latency_scope": "inclusive task wall windows; shared A/B diagnostics charged once outside per-arm windows; linear-interpolated observed tails are not population guarantees",
                 "shared_diagnostics": result["cost_observations"]["shared_diagnostics"],
                 "aggregation": result["cost_observations"]["aggregation"], "memory_scope": result["cost_observations"]["memory_scope"],
                 "shared_native_compile_wall_ns": plan["native"]["original_compile_wall_ns"], "compile_scope": plan["native"]["compile_cost_scope"],
                 "energy_joules": result["energy_joules"], "peak_rss_bytes": result["peak_rss_bytes"], "full_system_cost_known": result["cost_observations"]["full_system_cost_known"],
                 "unknown_meters": ["physical energy", "concurrent process-tree peak memory", "queue peak occupancy", "full system training/build/switch/serving cost"]},
        "scope": {key: plan[key] for key in ("fixture_only", "independent_real_sources", "ordinary_daemon_qualification", "fairness", "cold_scope")},
    }


def audit_updates(audit, domain, campaign, native_image):
    root = "runtime-joint/semantic-campaign-worker/updates"
    result, plan = audit.json(root + "/RESULT.json"), audit.json(root + "/PLAN.json")
    require(result == domain["updates"] and audit.digest(root + "/RESULT.json") == domain["updates_result_sha256"] and result["plan_sha256"] == audit.digest(root + "/PLAN.json"), "updates stdout/originals differ")
    require(result["parameters"]["source_result_sha256"] == plan["learning_result_sha256"] == campaign["result_sha256"], "updates borrowed another learning result")
    require(plan["native"]["image_sha256"] == domain["updates_native_image_sha256"] == native_image == audit.digest(root + "/native/cell_bridge.so"), "updates used another native image")
    benchmark = audit.json(root + "/CODE_BENCHMARK.json")
    require(audit.digest(root + "/CODE_BENCHMARK.json") == result["code"]["benchmark_sha256"], "code benchmark differs")
    require(len(benchmark["loop"]) == len(benchmark["builtin"]) == result["code"]["task_pairs"], "code task pairing differs")
    for original, changed in zip(benchmark["loop"], benchmark["builtin"]):
        require(original["receipt"]["output"]["cell"] == changed["receipt"]["output"]["cell"] and original["receipt"]["state_digest"] == changed["receipt"]["state_digest"], "code update changed output or state")
    measured = {name: sum(row["wall_ns"] for row in values) for name, values in benchmark.items()}
    code, state = result["code"], result["state"]
    require(measured == code["measured_wall_ns"] and measured["builtin"] + code["pilot_cost"]["wall_ns"] == code["candidate_plus_pilot_wall_ns"], "code cost sum differs")
    require(code["observed_wall_gain_after_pilot"] is (code["candidate_plus_pilot_wall_ns"] < measured["loop"]), "code observed cost gain differs")
    require(audit.json(root + "/COLD_RESULT.json") == state["cold"] and state["pending_preserved"] is True, "state migration cold/original control differs")
    db = audit.database(root + "/owner.sqlite")
    return {"status": result["status"], "result_sha256": audit.digest(root + "/RESULT.json"), "plan_sha256": result["plan_sha256"],
            "same_runtime_stdout_and_campaign_verified": True, "native_phases": db["native_phases"], "intent_statuses": db["intent_statuses"],
            "code": {key: code[key] for key in ("decision", "reason", "task_pairs", "outputs_and_states_equal", "observed_wall_gain_after_pilot", "measured_wall_ns", "candidate_plus_pilot_wall_ns", "distributions", "full_system_cost_known")},
            "state": {key: state[key] for key in ("status", "same_owner_and_partition", "pending_preserved", "cross_owner_or_effectful_migration", "external_business_effect_counts")},
            "migration_wall_ns": state["migration_cost"]["wall_ns"], "cold_wall_ns": state["cold_cost"]["wall_ns"],
            "cost": result["cost"], "parameter_source_result_sha256": result["parameters"]["source_result_sha256"],
            "parameters_reused_campaign_training": result["parameters"]["new_training_performed_by_this_qualifier"] is False,
            "models_sha256": {str(path.relative_to(audit.root)): file_sha(path) for path in (audit.root / root).glob("*.npz")},
            "pending_scope": "one deliberately injected unsettled pure Cell call; business-effect counts are unavailable"}


def perform(audit, workflow, post_reviews):
    origin, candidate = audit.json("local-joint/candidate.json"), audit.json("runtime-joint/candidate.json")
    candidate_hash, origin_hash = audit.digest("runtime-joint/candidate.json"), audit.digest("local-joint/candidate.json")
    require(candidate["origin_candidate_sha256"] == origin_hash, "runtime candidate origin differs")
    head = audit.raw("format-source.txt").decode().strip()
    require(candidate["source_bases"]["cells"] == workflow["head_sha"] == head, "workflow/format/source candidate head differs")
    require(candidate["files"] == origin["files"] and candidate["models"] == origin["models"] and candidate["source_identity"] == origin["source_identity"], "runtime candidate changed frozen sources/models")
    source_counts = Counter()
    for row in candidate["files"]:
        prefix = "local-joint/" if row["root"] == "artifacts" else "local-joint/executed-source/" + row["root"] + "/"
        require(audit.digest(prefix + row["path"]) == row["sha256"], "retained frozen artifact differs: " + row["path"])
        source_counts[row["root"]] += 1
    for group, identity in candidate["source_identity"].items():
        expected = {row["path"] for row in candidate["files"] if row["root"] == group}
        require(len(identity["files"]) == len(expected) and {row["path"] for row in identity["files"]} == expected, "source identity path scope differs")
        for row in identity["files"]:
            raw = audit.raw("local-joint/executed-source/" + group + "/" + row["path"])
            blob = hashlib.new(identity["object_format"], b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            require(blob == row["git_blob"] and len(raw) == row["bytes"] and sha(raw) == row["sha256"], "retained source blob identity differs")
            if identity["exact_head_source"]:
                require(blob == row["head_blob"] and row["mode"] == row["head_mode"] and not identity["git_status_porcelain"], "clean original HEAD declaration disagrees with its source bytes/mode")
    runtime_pins = candidate["runtime_identity"]
    require(audit.raw("runtime-source.txt").decode().strip() == runtime_pins["source_commit"] == candidate["source_bases"]["runtime"], "runtime source record differs")
    require(audit.raw("runtime-binary.sha256").decode().split()[0] == runtime_pins["binary_sha256"], "runtime binary build digest record differs")
    require(not audit.raw("runtime-source-before.txt").strip() and not audit.raw("runtime-source-after.txt").strip(), "runtime source build was dirty")
    native_image = candidate["native"]["image_sha256"]
    original_request = audit.json("request.json")
    profile = audit.json("runtime-joint/profile.json")
    main, single_domain, single = audit_lane(audit, "runtime-joint/result.json", profile, candidate_hash, runtime_pins, original_request)
    receipt = single_domain["result"]
    require(receipt["status"] == "committed" and receipt["output"]["hia"]["terminal_action"] == "COMPLETE" and receipt["output"]["hia"]["image_sha256"] == native_image and receipt["output"]["hia"]["candidate_sha256"] == candidate_hash, "single Cell receipt lacks exact native completion")
    single["native_complete_receipts"] = 1
    lanes, campaigns = {"single_cell": single}, {}
    for label, prefix, nested in (("syntax", "campaign", "maintenance"), ("semantic_updates", "semantic-campaign", "semantic_updates")):
        report_name = "runtime-joint/" + prefix + "-runtime.json"
        recorded = audit.json(report_name)
        require(main[nested] == recorded, "outer runtime report differs from lane original")
        _, domain, lane = audit_lane(audit, report_name, recorded["profile"], candidate_hash, runtime_pins, recorded["request"])
        campaigns[label] = audit_campaign(audit, prefix, domain, candidate_hash, runtime_pins, native_image)
        lanes[label] = lane
        if label == "semantic_updates":
            updates = audit_updates(audit, domain, campaigns[label], native_image)
    reviews = {}
    for label, name in (("syntax", "campaign-readonly-review.json"), ("semantic_updates", "semantic-readonly-review.json")):
        path = audit.root / "runtime-joint" / name
        reviews[label] = {"status": "NOT_RETAINED"}
        if path.exists():
            record = audit.json("runtime-joint/" + name)
            reviews[label] = {key: record.get(key) for key in ("status", "failure_stage", "error", "original_verifier_expected_sha256", "original_verifier_sha256")}
    post = {}
    for label, path in post_reviews.items():
        if path is not None:
            record = strict(path.read_bytes())
            require(record["status"] == "READ_ONLY_SNAPSHOT_CONSISTENCY_PASS" and record["source_unchanged_verified"] is True and record["snapshot_unchanged_during_review"] is True, "external post-review did not pass unchanged originals")
            require(record["review"]["result_sha256"] == campaigns[label]["result_sha256"], "external post-review names another runtime campaign")
            post[label] = {"path": str(path), "sha256": file_sha(path), "status": record["status"], "result_sha256": record["review"]["result_sha256"], "verifier_sha256": record["original_verifier_sha256"], "scope": "external review of these exact originals; does not change the historical CI conclusion"}
    return {
        "schema": "hepta.retained-runtime-artifact-audit.v1", "audit_status": "PASS",
        "workflow": workflow, "whole_workflow_pass": workflow["conclusion"] == "success",
        "scope": "read-only original-file/protocol/SQLite consistency audit; no task/model/native rerun or new qualification",
        "binding": {"candidate_sha256": candidate_hash, "origin_candidate_sha256": origin_hash,
                    "source_bases": candidate["source_bases"], "runtime_identity": runtime_pins,
                    "source_identity": {group: {key: row[key] for key in ("head", "tree", "symbolic_ref", "exact_head_source", "scope")} for group, row in candidate["source_identity"].items()},
                    "native": candidate["native"], "models": {cell: {"checkpoint_sha256": row["sha256"], "config": row["config"], "base_sha256": row["bundle"]["components"]["base"], "head_sha256": row["bundle"]["components"]["heads"]} for cell, row in candidate["models"].items()},
                    "input_data_sha256": audit.digest("local-joint/inputs.json"), "device": candidate["device"],
                    "verified_frozen_file_counts": dict(source_counts), "runtime_source_clean_before_after_build": True,
                    "artifact_extraction_modes_requalify_original_checkout": False,
                    "runtime_binary_bytes_available_for_rehash": False, "private_runtime_config_bytes_available_for_rehash": False},
        "lanes": lanes, "campaigns": campaigns, "updates": updates,
        "original_ci_reviews": reviews, "external_post_reviews": post,
        "claims": {"learning_benefit_proved": False, "ordinary_daemon_qualified": False, "whole_system_cost_known": False,
                   "new_claim_from_legacy_or_other_head": False, "business_effect_loss_duplication_counts_known": False},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--workflow-metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--post-review-syntax", type=Path)
    parser.add_argument("--post-review-semantic", type=Path)
    args = parser.parse_args()
    root, output = args.artifact_dir.resolve(strict=True), args.output.resolve()
    require(not output.is_relative_to(root), "output must be outside original artifacts")
    require(not output.exists(), "audit output must be new")
    before = inventory(root)
    workflow = strict(args.workflow_metadata.read_bytes())
    audit = Audit(root)
    try:
        report = perform(audit, workflow, {"syntax": args.post_review_syntax, "semantic_updates": args.post_review_semantic})
    except Exception as error:
        report = {"schema": "hepta.retained-runtime-artifact-audit.v1", "audit_status": "FAIL", "workflow": workflow, "whole_workflow_pass": workflow.get("conclusion") == "success", "error": type(error).__name__ + ": " + str(error)}
    after = inventory(root)
    report["original_artifacts_unchanged"] = before == after
    report["original_inventory"] = {"files": len(before), "bytes": sum(row["bytes"] for row in before.values()), "byte_inventory_sha256": sha(canonical({name: {"bytes": row["bytes"], "sha256": row["sha256"]} for name, row in before.items()}))}
    report["auditor_sha256"] = file_sha(Path(__file__))
    report["read_file_count"] = len(audit.reads)
    report["workflow_metadata_sha256"] = file_sha(args.workflow_metadata)
    if before != after:
        report["audit_status"] = "FAIL"
        report["error"] = "original artifact inventory changed during audit"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical(report) + b"\n")
    print(json.dumps({"output": str(output), "sha256": file_sha(output), "audit_status": report["audit_status"], "workflow_conclusion": workflow.get("conclusion"), "original_artifacts_unchanged": before == after, "error": report.get("error")}, sort_keys=True))
    return 0 if report["audit_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
