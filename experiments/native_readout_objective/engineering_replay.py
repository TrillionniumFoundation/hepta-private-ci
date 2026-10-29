"""Selected new heads through durable native owners and complete task restore."""

from dataclasses import asdict

import numpy as np

from experiments.continuous_boundary_flow.integration import (
    _compare_physics,
    _primitive_reward,
    contained,
    durable_json,
    require,
)
from experiments.continuous_boundary_flow.math_model import (
    TaskSpec,
    build_model,
    sample_step,
    solve_dp,
)
from experiments.continuous_boundary_flow.native.adapter import ACTIONS
from experiments.continuous_boundary_policy.features import FeatureMap, native_rows

from .common import CostMeter, canonical, open_bridge, read_json, sha, write_records


def make_context(specification):
    model = build_model(TaskSpec(**specification), n_grid=64, x_max=4.8)
    return {"model": model, "dp": solve_dp(model)}


def restore(path, expected_sha, bindings):
    require(sha(path.read_bytes()) == expected_sha, "Task checkpoint bytes changed")
    packet = read_json(path)
    saved = packet["payload"]
    require(
        sha(canonical(saved)) == packet["payload_sha256"],
        "Task checkpoint payload changed",
    )
    require(
        saved["schema"] == "hepta.native-readout-objective.complete-task.v1",
        "Task checkpoint schema changed",
    )
    require(saved["bindings"] == bindings, "Task checkpoint binding changed")
    elapsed, state, anchor = (
        saved["elapsed_completed"],
        saved["state_idx"],
        saved["native_anchor"],
    )
    require(
        type(elapsed) is int and 1 <= elapsed <= saved["spec"]["horizon"],
        "Invalid restored deadline",
    )
    require(type(state) is int and -1 <= state < 64, "Invalid restored physical state")
    require(
        type(saved["previous_failed"]) is bool
        and type(saved["previous_repair"]) is bool,
        "Invalid restored causal action history",
    )
    require(
        0 <= saved["previous_risk"] <= 1 and np.isfinite(saved["utility_so_far"]),
        "Invalid restored risk/utility",
    )
    require(
        anchor["step"] == elapsed
        and anchor["seed"] == bindings["seed"]
        and anchor["case"] == bindings["case"]
        and anchor["profile_sha256"] == bindings["profile_sha256"],
        "Native/physical frontier mismatch",
    )
    require(
        saved["native_logical_micros"] == elapsed * 10000
        and saved["task_physical_time"] == elapsed * saved["spec"]["dt"],
        "Restored clocks mismatch",
    )
    require(
        sha(canonical(saved["spec"])) == bindings["spec_sha256"],
        "Restored task specification changed",
    )
    return saved


def replay(root, output, record, item, manifest_sha, binary, source=None):
    meter = CostMeter()
    checkpoint_path = contained(root, item["path"])
    require(
        sha(checkpoint_path.read_bytes()) == item["sha256"],
        "Selected checkpoint changed",
    )
    checkpoint = read_json(checkpoint_path)
    profile_path = contained(root, checkpoint["profile_path"])
    require(
        sha(profile_path.read_bytes()) == checkpoint["profile_sha256"],
        "Selected profile changed",
    )
    profile = read_json(profile_path)
    require(
        profile["arm_id"] == "native_sparse"
        and profile["stage"] == "act"
        and profile["tick_micros"] == 10000,
        "Owner profile contract changed",
    )
    seed, arm = record["train_seed"], record["arm"]
    require(
        checkpoint["seed"] == seed
        and checkpoint["arm"] == arm
        and record["checkpoint_sha256"] == item["sha256"],
        "Record/checkpoint identity changed",
    )
    reference_steps = record["steps"]
    require(bool(reference_steps), "Cannot restore an empty episode")
    case = f"owner.{record['episode_id']}.{arm}"
    directory = output / "cases" / case
    directory.mkdir(parents=True, exist_ok=False)
    bindings = {
        "case": case,
        "episode_id": record["episode_id"],
        "arm": arm,
        "seed": seed,
        "scientific_manifest_sha256": manifest_sha,
        "reference_record_sha256": sha(canonical(record)),
        "selected_checkpoint_sha256": item["sha256"],
        "profile_sha256": checkpoint["profile_sha256"],
        "binary_sha256": sha(binary.read_bytes()),
        "spec_sha256": sha(canonical(record["spec"])),
    }
    durable_json(directory / "REFERENCE.json", record)
    (directory / "SELECTED_CHECKPOINT.json").write_bytes(checkpoint_path.read_bytes())
    (directory / "PROFILE.json").write_bytes(profile_path.read_bytes())
    context = make_context(record["spec"])
    model = context["model"]
    mapping = FeatureMap(context, "native_sparse", checkpoint["candidate"])
    state, pf, pr, pa, utility = (
        int(reference_steps[0]["state_idx"]),
        False,
        0.0,
        False,
        0.0,
    )
    cut = min(3, max(1, len(reference_steps) // 2))
    rows, resumes, guards, process_costs = [], [], [], []
    bridge = None
    result = {"schema": "hepta.native-readout-objective.owner-case.v1", **bindings}
    try:
        bridge = open_bridge(binary, directory / "host", source)
        bridge.load_profile(profile_path, checkpoint["profile_sha256"])
        opened = bridge.open(case, seed, checkpoint["profile_sha256"])
        durable_json(directory / "OPEN.json", opened)
        require(opened["status"]["step"] == 0, "Fresh owner has a prior frontier")
        for elapsed, reference in enumerate(reference_steps):
            require(
                reference["elapsed"] == elapsed
                and reference["state_idx"] == state
                and state >= 0
                and elapsed < model.spec.horizon,
                "Physical replay frontier changed",
            )
            values, reset = mapping.step(
                [state], model.spec.horizon - elapsed, [pf], [pr], [pa]
            )
            typed = native_rows(values)[0]
            require(
                np.array_equal(values[0], reference["features"])
                and float(reset[0]) == reference["reset_fraction"]
                and typed == reference["native_features"],
                "New FeatureMap/fast-path feature mismatch",
            )
            causal = {
                "elapsed": elapsed,
                "state_idx": state,
                "previous_failed": pf,
                "previous_risk": pr,
                "previous_repair": pa,
            }
            native = bridge.tick(
                typed, evidence_digest=sha(canonical({"bindings": bindings, **causal}))
            )
            fast = reference["native_row"]
            require(
                native["activation_q24"] == fast["activation_q24"],
                "Durable-owner activation mismatch",
            )
            require(
                native["readout"]["scores_q24"] == fast["readout"]["scores_q24"],
                "Durable-owner native score mismatch",
            )
            require(
                native["effective_action"]
                == native["readout"]["action"]
                == fast["readout"]["action"],
                "Durable owner changed selected action",
            )
            action = ACTIONS.index(native["effective_action"])
            require(
                ("wait", "repair", "stop")[action] == reference["action"],
                "Effective task action mismatch",
            )
            trace = sample_step(
                model,
                [state],
                [action],
                uniforms=np.asarray([reference["uniforms"][1:]]),
            )
            _compare_physics(trace, reference)
            reward = float(_primitive_reward(model.spec, trace))
            require(
                abs(reward - reference["reward"]) < 2e-12
                and abs(reward - trace["reward"][0]) < 2e-12,
                "Primitive task reward changed",
            )
            discounted = model.gamma**elapsed * reward
            require(
                abs(discounted - reference["discounted_reward"]) < 2e-12,
                "Discounted reward changed",
            )
            utility += discounted
            state, pf, pr, pa = (
                int(trace["next_state_idx"][0]),
                bool(trace["failed"][0]),
                float(trace["F_after_action"][0] or 0.0),
                bool(action == 1),
            )
            rows.append(
                {
                    "schema": "hepta.native-readout-objective.owner-step.v1",
                    **causal,
                    "features": values[0].tolist(),
                    "native_features": typed,
                    "native_output": native,
                    "uniforms": reference["uniforms"],
                    "physical": {key: value.tolist() for key, value in trace.items()},
                    "discounted_reward": discounted,
                    "utility_so_far": utility,
                    "native_logical_micros": (elapsed + 1) * 10000,
                    "task_physical_time": (elapsed + 1) * model.spec.dt,
                }
            )
            if elapsed + 1 == cut:
                payload = {
                    "schema": "hepta.native-readout-objective.complete-task.v1",
                    "bindings": bindings,
                    "spec": asdict(model.spec),
                    "elapsed_completed": elapsed + 1,
                    "state_idx": state,
                    "previous_failed": pf,
                    "previous_risk": pr,
                    "previous_repair": pa,
                    "utility_so_far": utility,
                    "native_anchor": dict(bridge.current),
                    "remaining_uniforms": [
                        step["uniforms"] for step in reference_steps[elapsed + 1 :]
                    ],
                    "native_logical_micros": (elapsed + 1) * 10000,
                    "task_physical_time": (elapsed + 1) * model.spec.dt,
                    "feature_map_state": "stateless function of spec, deadline, physical state and saved causal history",
                }
                packet_path = directory / "TASK_CHECKPOINT.json"
                packet_sha = durable_json(
                    packet_path,
                    {"payload": payload, "payload_sha256": sha(canonical(payload))},
                )
                old_pid = bridge.process.pid
                process_costs.append(bridge.close())
                bridge = None
                saved = restore(packet_path, packet_sha, bindings)
                require(
                    saved["remaining_uniforms"]
                    == [step["uniforms"] for step in reference_steps[cut:]],
                    "Restored future innovation slots changed",
                )
                context = make_context(saved["spec"])
                model = context["model"]
                mapping = FeatureMap(context, "native_sparse", checkpoint["candidate"])
                state, pf, pr, pa, utility = (
                    saved[key]
                    for key in [
                        "state_idx",
                        "previous_failed",
                        "previous_risk",
                        "previous_repair",
                        "utility_so_far",
                    ]
                )
                bridge = open_bridge(binary, directory / "host", source)
                bridge.load_profile(profile_path, checkpoint["profile_sha256"])
                resumed = bridge.open(
                    case, seed, checkpoint["profile_sha256"], resume=True
                )
                status, anchor = resumed["status"], saved["native_anchor"]
                require(
                    bridge.process.pid != old_pid, "Native process was not replaced"
                )
                require(
                    status["checkpoint"] == anchor["checkpoint"]
                    and status["step"] == anchor["step"]
                    and status["case"] == case
                    and status["seed"] == seed
                    and status["arm"] == "native_sparse"
                    and status["terminal"] == (state < 0),
                    "Restored owner frontier/identity mismatch",
                )
                resumes.append(
                    {
                        "checkpoint_sha256": packet_sha,
                        "closed_pid": old_pid,
                        "new_pid": bridge.process.pid,
                        "restored": resumed,
                        "continued_steps": len(reference_steps) - cut,
                    }
                )
            if state < 0:
                before = bridge.rpc({"command": "Status"})
                request = {
                    "command": "Tick",
                    "observation": {
                        "event_id": f"{case}.forbidden-after-stop",
                        "step": bridge.current["step"] + 1,
                        "checkpoint": bridge.current["checkpoint"],
                        "features": typed,
                        "evidence_digest": sha(
                            canonical({"case": case, "probe": "forbidden-after-stop"})
                        ),
                    },
                }
                rejection = bridge.rpc(request, allow_error=True)
                after = bridge.rpc({"command": "Status"})
                require(
                    not rejection.get("ok", True)
                    and "Terminal episode" in rejection["error"]
                    and before == after,
                    "Post-STOP unique tick was not rejected atomically",
                )
                guards.append(
                    {
                        "request": request,
                        "before": before,
                        "rejection": rejection,
                        "after": after,
                    }
                )
        require(
            state < 0 or len(rows) == model.spec.horizon,
            "Replay ended without STOP/deadline",
        )
        net = utility - 1e-6 * 160 * len(rows)
        require(
            abs(utility - record["reported_utility"]) < 2e-10
            and abs(net - record["reported_net_utility"]) < 2e-10,
            "Replayed task utility changed",
        )
        result.update(passed=True, utility=utility, net_utility=net)
    except Exception as error:
        result.update(passed=False, error=f"{type(error).__name__}: {error}")
    finally:
        if bridge is not None:
            process_costs.append(bridge.close())
        durable_json(directory / "PROCESS_COSTS.json", process_costs)
        durable_json(directory / "COLD_RESUME.json", resumes)
        durable_json(directory / "STOP_GUARDS.json", guards)
        shard = write_records(directory / "TASK_TRACE.jsonl.gz", rows)
    counts = {
        key: sum(cost["counters"][key] for cost in process_costs)
        for key in ["owner_ticks", "actual_kernel_calls", "actual_ndu_calls"]
    }
    if any(value != len(rows) for value in counts.values()):
        result.update(
            passed=False, error="Native owner/kernel/NDU execution counter mismatch"
        )
    result.update(
        steps=len(rows),
        native_decision_counts=counts,
        cold_resumes=len(resumes),
        continued_after_resume=max(0, len(rows) - cut),
        terminal_checkpoint_only=len(reference_steps) == cut,
        stop_guards=len(guards),
        cost=meter.finish(),
        native_process_costs=process_costs,
        trace={
            **shard,
            "path": str((directory / "TASK_TRACE.jsonl.gz").relative_to(output)),
        },
        independent_efficacy_samples=0,
        scope_dependent_hash_parity_claimed=False,
    )
    durable_json(directory / "RESULT.json", result)
    return result
