"""Audit archived original-owner/NDU executions without rerunning the native binary."""

import json

from online_audit_common import canonical, check, close
from online_state_audit import audit_stream_snapshot, digest, read_native_archive


Q = 1 << 24
NATIVE_IDENTITY = {
    "schema": "hepta.continuous-boundary.native-identity.v1",
    "binary_sha256": "1dc702aea6a448ad84407aeb71dc8f23066205fab79fe7c6859fc02c55e6f7a5",
    "source_commit": "5898cd8b0f724c3152b6cc52856721f72e5e08be",
    "source_manifest_digest": "6addea031fa9ba2ca403137d8d10da6088c255474c681b106d9a2706c645dd09",
    "owner_authority": "DENY_ALL",
}


def verify_profile(profile, contract):
    args = contract["client_arguments"]
    expected = {
        "feature_names": [args["score_kind"]],
        "encoder_weights_q24": [
            [Q, 0, 0, 0],
            [-Q, 0, 0, 0],
            [0, Q // 2, 0, 0],
            [0, 0, Q, 0],
            [0, 0, 0, Q],
        ],
        "encoder_bias_q24": [0, 0, -4 * Q, -Q, -Q],
        "head_weights_q24": [[Q, -Q, 0, 0, 0], [0] * 5, [0] * 5],
        "head_bias_q24": [0, -8 * Q, 0],
        "maximum_ticks": args["maximum_ticks"],
        "objective_digest": args["objective_sha256"],
        "arm_id": args["arm_id"],
        "use_flow": True,
        "use_risk": True,
        "use_margin": True,
        "source_model_digest": canonical(
            {
                "neural_model_sha256": args["model_sha256"],
                "policy_sha256": args["policy_sha256"],
            },
            compact=True,
        ),
    }
    check(
        {key: profile[key] for key in expected} == expected,
        "original sparse head compilation/profile binding",
    )
    kernel = profile["kernel"]
    check(
        kernel["width"] == 5 and kernel["top_k"] == 1, "original activity-cap contract"
    )
    check(
        all(
            value == 0 for key, value in kernel.items() if key not in {"width", "top_k"}
        ),
        "stateless native compilation parameters",
    )


def verify_tick(tick, contract, event, previous_checkpoint, profile_sha):
    native, decision = tick["native"], tick["decision"]
    raw, packet = native["raw"], native["signal_packet"]
    margin = tick["natural_margin_mean"]
    semantics = {
        "continue_score": decision["continue_score"],
        "score_kind": decision["score_kind"],
        "natural_margin": margin / (1 + abs(margin)),
        "task_risk": decision["predicted_error_probability"],
        "activity": tick["event_activity_mean"],
        "continuation_value": decision["continuation_value"],
        "stopping_value": decision["stopping_value"],
        "forced_terminal": decision["forced_terminal"],
    }
    check(
        packet["semantics"] == semantics, "typed value/risk/margin/activity semantics"
    )
    score = round(semantics["continue_score"] * Q)
    features = {
        "raw_q24": [score],
        "continuous": {
            "margin_q24": round(semantics["natural_margin"] * Q),
            "risk_q24": round(semantics["task_risk"] * Q),
            "flow_q24": round(semantics["activity"] * Q),
        },
    }
    check(packet["features"] == features, "actual Q24 input arithmetic")
    causal = canonical(
        {
            "episode_id": contract["episode_id"],
            "step": tick["step"],
            "task_binding": contract["task_binding"],
            "decision": decision,
            "natural_margin_raw": margin,
            "interval_event_probability": tick["event_activity_mean"],
        },
        compact=True,
    )
    bound = canonical({"causal_source": causal, "signal_packet": packet}, compact=True)
    check(
        native["causal_source_digest"] == causal
        and native["bound_native_evidence_digest"] == bound,
        "neural/task/native evidence binding",
    )
    observation = {
        "event_id": f"{contract['case_id']}.event.{tick['step']}",
        "step": tick["step"],
        "checkpoint": previous_checkpoint,
        "features": features,
        "evidence_digest": bound,
    }
    check(
        event == {"observation": observation, "output": raw},
        "original durable event equals consumed native receipt",
    )
    for key, value in {
        "step": tick["step"],
        "case": contract["case_id"],
        "arm": "hcsn." + contract["policy_id"],
        "seed": contract["seed"],
        "checkpoint_before": previous_checkpoint,
        "profile_sha256": profile_sha,
        "actual_model_calls": 1,
        "actual_ndu_calls": 1,
        "native_transition_executed": True,
        "owner_authority": "DENY_ALL",
        "duplicate_event_ignored": False,
    }.items():
        check(raw[key] == value, "actual original kernel/NDU invocation identity")
    action = "keep" if score > 0 else "stop"
    check(
        raw["activation_q24"] == [max(score, 0), max(-score, 0), 0, 0, 0],
        "sparse signed-coordinate output",
    )
    check(raw["readout"]["scores_q24"] == [score, -8 * Q, 0], "native head arithmetic")
    check(raw["readout"]["tie"] == (score == 0), "quantized tie detection")
    check(
        raw["effective_action"]
        == raw["readout"]["action"]
        == native["action"]
        == action,
        "consumed original NDU decision",
    )
    check(
        native["stop"] == tick["actual_stop"] == raw["terminal"] == (action == "stop"),
        "actual STOP authority",
    )
    check(
        native["policy_disagreement"] == (native["stop"] != decision["stop"]),
        "Q24 discrepancy retained",
    )
    check(native["natural_margin_raw"] == margin, "raw natural margin retained")
    check(len(raw["readout"]["native_ndu_digest"]) == 64, "original NDU digest")
    probe = native["post_stop_probe"]
    if action == "stop":
        check(probe["before"] == probe["after"], "native post-STOP frontier unchanged")
        check(
            probe["before"]["step"] == tick["step"] and probe["before"]["terminal"],
            "terminal native frontier",
        )
        check(
            not probe["rejection"]["ok"]
            and "Terminal episode" in probe["rejection"]["error"],
            "actual post-STOP native RPC rejected",
        )
    else:
        check(probe is None, "no premature post-STOP probe")
    return raw["checkpoint_after"]


def verify_recovery(files, recovery, contract, first_tick):
    check(
        recovery["status"] == "new_native_process_and_serialized_neural_state_restored",
        "native recovery status",
    )
    check(
        recovery["old_pid"] != recovery["new_pid"]
        and not recovery["python_process_restarted"],
        "fresh native process; same Python process",
    )
    check(recovery["restored_cursor"] == 1, "preselected continuing prefix cursor")
    task_raw = files["recovery_00/TASK.json"]
    task = json.loads(task_raw)
    check(digest(task_raw) == recovery["task_sha256"], "complete native task hash")
    args = contract["client_arguments"]
    expected = {
        "episode_id": contract["episode_id"],
        "cursor": 1,
        "model_sha256": args["model_sha256"],
        "policy_id": contract["policy_id"],
        "seed": contract["seed"],
        "task_binding": contract["task_binding"],
    }
    check(
        {key: task[key] for key in expected} == expected,
        "native recovery complete task binding",
    )
    state = audit_stream_snapshot(
        files["recovery_00/stream/manifest.json"],
        files["recovery_00/stream/state.npz"],
        args["model_sha256"],
        1,
    )
    check(recovery["stream"] == state, "cold neural snapshot byte accounting")
    check(
        task["stream_manifest_sha256"] == state["manifest_sha256"]
        and task["stream_payload_sha256"] == state["payload_sha256"],
        "task-bound neural payload",
    )
    binding = task["native_binding"]
    for key in ("model_sha256", "objective_sha256", "policy_sha256", "score_kind"):
        check(binding[key] == args[key], "cold native/model/policy binding")
    check(
        binding["binary_sha256"] == NATIVE_IDENTITY["binary_sha256"],
        "cold binary binding",
    )
    check(
        binding["profile_sha256"] == first_tick["raw"]["profile_sha256"],
        "cold profile binding",
    )
    status = binding["status"]
    check(
        status["step"] == 1
        and status["durable_event_count"] == 1
        and not status["terminal"],
        "continuing durable frontier",
    )
    check(
        status["checkpoint"] == first_tick["raw"]["checkpoint_after"],
        "neural/native checkpoint alignment",
    )
    check(
        recovery["native_resume"]["status"] == status,
        "fresh native owner resumes exact frontier",
    )
    for name in (
        "original_journal_replay_steps",
        "event_validation_kernel_steps",
        "event_validation_ndu_calls",
    ):
        check(
            recovery["native_resume"][name] == 1,
            "actual original native recovery replay work",
        )


def audit_native_record(directory, record, x, dt, result):
    costs = record["native_cost"]
    files = read_native_archive(directory, costs["archive"])
    contract = json.loads(files["CONTRACT.json"])
    binding = {
        "input_sha256": digest(x.tobytes() + dt.tobytes()),
        "policy_sha256": result["policy_sha256"],
        "snr": float(x[0, 1]),
        "cost": float(x[0, 2]),
        "horizon": len(x),
    }
    check(
        contract["episode_id"] == record["episode_id"]
        and contract["policy_id"] == record["mode"],
        "native episode/policy identity",
    )
    row_index = int(record["episode_id"].rsplit(".", 1)[1])
    check(
        contract["task_binding"] == binding
        and contract["seed"] == result["seed"] + row_index,
        "native input/context/seed identity",
    )
    check(
        contract["case_id"]
        == "hcsn."
        + canonical(
            {"episode": record["episode_id"], "policy": record["mode"]}, compact=True
        ),
        "durable owner case identity",
    )
    check(
        contract["native_identity"] == NATIVE_IDENTITY,
        "pinned original native binary/source",
    )
    args = contract["client_arguments"]
    check(
        args["model_sha256"] == result["actor_model_sha256"]
        and args["objective_sha256"] == result["objective_sha256"],
        "shared actor/objective native binding",
    )
    check(
        args["policy_sha256"] == result["policy_sha256"]
        and args["maximum_ticks"] == len(x),
        "policy/deadline native binding",
    )
    root = "owner/" + contract["case_id"] + "/"
    identity = json.loads(files[root + "IDENTITY.json"])
    profile_sha = identity["profile_sha256"]
    profile_raw = files["owner/profiles/" + profile_sha + ".json"]
    check(digest(profile_raw) == profile_sha, "native profile byte digest")
    verify_profile(json.loads(profile_raw), contract)
    events = [json.loads(line) for line in files[root + "events.jsonl"].splitlines()]
    check(len(events) == record["observations"], "one durable event per paid read")
    previous = "0" * 64
    for tick, event in zip(record["trace"], events, strict=True):
        check(
            json.loads(files[f"TICK_{tick['step']:03d}.json"]) == tick["native"],
            "consumed and archived native output equal",
        )
        previous = verify_tick(tick, contract, event, previous, profile_sha)
    archived_costs = json.loads(files["RECEIPT.json"])
    check(
        all(costs[key] == value for key, value in archived_costs.items()),
        "native lifetime receipt retained",
    )
    recoveries = costs["recoveries"]
    check(
        recoveries
        == ([] if record["native_recovery"] is None else [record["native_recovery"]]),
        "native recovery evidence inventory",
    )
    if recoveries:
        check(
            json.loads(files["recovery_00/RECEIPT.json"]) == recoveries[0],
            "native restored receipt retained",
        )
        verify_recovery(files, recoveries[0], contract, record["trace"][0]["native"])
    processes = costs["native_processes"]
    check(len(processes) == 1 + len(recoveries), "actual fresh native process count")
    total = {}
    for process in processes:
        check(
            process["identity"] == NATIVE_IDENTITY and process["exit_code"] == 0,
            "native process identity/exit",
        )
        check(
            process["cpu_scope"] == "this exact native child PID from wait4"
            and not process["hardware_energy_measured"],
            "per-child CPU, no energy claim",
        )
        counters = process["counters"]
        check(
            all(type(v) is int and v >= 0 for v in counters.values()),
            "native integer counters",
        )
        check(
            counters["total_native_kernel_calls"]
            == counters["actual_kernel_calls"]
            + counters["original_journal_replay_steps"]
            + counters["event_validation_kernel_steps"],
            "original kernel call accounting",
        )
        check(
            counters["total_native_ndu_calls"]
            == counters["actual_ndu_calls"] + counters["event_validation_ndu_calls"],
            "original NDU call accounting",
        )
        for key, value in counters.items():
            total[key] = total.get(key, 0) + value
    for key in ("owner_ticks", "actual_kernel_calls", "actual_ndu_calls"):
        check(
            total[key] == record["observations"],
            "native execution count matches paid reads",
        )
    check(
        total["native_errors"] == 1 and total["batch_ticks"] == 0,
        "one intentional post-STOP error and no hidden batch ticks",
    )
    for key in (
        "original_journal_replay_steps",
        "event_validation_kernel_steps",
        "event_validation_ndu_calls",
    ):
        check(total[key] == len(recoveries), "recovery work charged separately")
    close(
        costs["native_child_cpu_seconds"],
        sum(p["child_cpu_seconds"] for p in processes),
        "exact-child CPU sum",
    )
    disagreements = sum(
        tick["native"]["policy_disagreement"] for tick in record["trace"]
    )
    check(costs["policy_disagreements"] == disagreements, "Q24 disagreement count")
    check(
        costs["post_stop_native_rejected"]
        and costs["terminal"]
        and costs["steps"] == record["observations"],
        "final native paid-read stop receipt",
    )
    return {
        "observations": record["observations"],
        "processes": len(processes),
        "cold_recoveries": len(recoveries),
        "policy_disagreements": disagreements,
        "same_stop_as_python": record["same_stop_as_python"],
        "counters": total,
        "native_child_cpu_seconds": costs["native_child_cpu_seconds"],
        "parent_lifetime_cpu_seconds": costs["parent_lifetime_cpu_seconds"],
        "parent_lifetime_wall_seconds": costs["parent_lifetime_wall_seconds"],
        "archive_cpu_seconds": costs["archive_cpu_seconds"],
        "archive_wall_seconds": costs["archive_wall_seconds"],
        "quantized_disagreements": [
            {
                "step": tick["step"],
                "continue_score": tick["decision"]["continue_score"],
                "score_q24": tick["native"]["signal_packet"]["features"]["raw_q24"][0],
                "python_stop": tick["decision"]["stop"],
                "native_action": tick["native"]["action"],
            }
            for tick in record["trace"]
            if tick["native"]["policy_disagreement"]
        ],
        "archive_bytes": costs["archive"]["bytes"],
        "archive_uncompressed_bytes": costs["archive"]["uncompressed_file_bytes"],
    }
