"""Causal closed-loop task execution with actual native sparse/NDU decisions."""

from dataclasses import asdict

import numpy as np

from .common import canonical, sha
from .math_model import sample_step
from .models import ActorAdapter
from .native.adapter import ACTIONS, Q, features
from .scenarios import episode_streams


def feature_rows(values, indices):
    return [
        features(
            values["raw"][i],
            margin=values["margin"][i],
            risk=values["risk"][i],
            flow=values["flow"][i],
        )
        for i in indices
    ]


def run_context(
    context,
    *,
    seed,
    phase,
    paths,
    arm,
    checkpoint_sha256,
    bridge=None,
    profile_sha=None,
    candidate=None,
    boundary_weights=None,
    retain=True,
):
    model, dp = context["model"], context["dp"]
    states, slots, eval_seed = episode_streams(seed, phase, context, paths)
    case_ids = [f"{seed}.{phase}.c{context['index']}.p{i}" for i in range(paths)]
    records = [
        {
            "arm": arm,
            "train_seed": seed,
            "split": phase,
            "episode_id": case,
            "eval_seed": eval_seed,
            "checkpoint_sha256": checkpoint_sha256,
            "spec": asdict(model.spec),
            "steps": [],
            "reported_utility": 0.0,
            "reported_net_utility": 0.0,
            "stability_failure": False,
        }
        for case in case_ids
    ]
    previous_failed = np.zeros(paths)
    previous_risk = np.zeros(paths)
    adapter = None
    if bridge is not None:
        adapter = ActorAdapter(
            model.spec, dp, arm, candidate, seed, boundary_weights=boundary_weights
        )
        bridge.kernel_reset(profile_sha, case_ids)
    total_utility = np.zeros(paths)
    total_bytes = np.zeros(paths, dtype=int)
    counts = {
        "actual_kernel_calls": 0,
        "actual_ndu_calls": 0,
        "semantic_message_bytes": 0,
        "wire_request_bytes": 0,
        "wire_response_bytes": 0,
        "model_state_updates": 0,
        "physical_environment_windows": 0,
    }
    for elapsed in range(model.spec.horizon):
        alive = np.flatnonzero(states >= 0)
        if not alive.size:
            break
        remaining = model.spec.horizon - elapsed
        before_states = states.copy()
        wires_in = wires_out = 0
        native_rows = None
        typed = None
        if adapter is not None:
            values = adapter.step(states, remaining, previous_failed, previous_risk)
            typed = feature_rows(values, alive)
            before = bridge.counters.copy()
            response = bridge.kernel_advance(
                profile_sha,
                [{"case_id": case_ids[i], "features": f} for i, f in zip(alive, typed)],
            )
            native_rows = response["rows"]
            if [row["case_id"] for row in native_rows] != [case_ids[i] for i in alive]:
                raise RuntimeError("Native causal batch identity changed")
            action = np.array(
                [ACTIONS.index(row["readout"]["action"]) for row in native_rows]
            )
            wires_in = bridge.counters["request_bytes"] - before["request_bytes"]
            wires_out = bridge.counters["response_bytes"] - before["response_bytes"]
            counts["actual_kernel_calls"] += response["actual_kernel_calls"]
            counts["actual_ndu_calls"] += response["actual_ndu_calls"]
            counts["wire_request_bytes"] += wires_in
            counts["wire_response_bytes"] += wires_out
            counts["model_state_updates"] += alive.size
        elif arm == "dp":
            action = np.argmax(dp["q"][remaining - 1, states[alive]], axis=-1)
        else:
            action = np.full(
                alive.size,
                {"always_keep": 0, "always_repair": 1, "always_stop": 2}[arm],
            )
        trace = sample_step(
            model, states[alive], action, uniforms=slots[elapsed, alive, 1:]
        )
        total_utility[alive] += model.gamma**elapsed * trace["reward"]
        counts["physical_environment_windows"] += alive.size
        # Equal fixed-width numerical payload. JSON framing is accounted separately.
        message_bytes = 160 if adapter is not None else 0
        total_bytes[alive] += message_bytes
        counts["semantic_message_bytes"] += message_bytes * alive.size
        for j, i in enumerate(alive):
            record = {
                "elapsed": elapsed,
                "action": ("wait", "repair", "stop")[action[j]],
                "state_idx": int(before_states[i]),
                "x": float(model.x[before_states[i]]),
                "x_after_action": trace["x_after_action"][j],
                "active_time": float(trace["active_time"][j]),
                "failed": bool(trace["failed"][j]),
                "tau_hit": trace["tau_hit"][j],
                "predicted_risk": trace["F_after_action"][j],
                "next_state_idx": int(trace["next_state_idx"][j]),
                "uniforms": slots[elapsed, i].tolist(),
                "source_kernel_calls": int(adapter is not None),
                "native_ndu_calls": int(adapter is not None),
                "semantic_message_bytes": message_bytes,
                "wire_request_bytes": wires_in // alive.size
                + int(j < wires_in % alive.size),
                "wire_response_bytes": wires_out // alive.size
                + int(j < wires_out % alive.size),
                "model_state_updates": int(adapter is not None),
                "solver_evals": 0,
            }
            if native_rows is not None:
                row = native_rows[j]
                record.update(
                    {
                        "raw_features": typed[j],
                        "activation_q24": row["activation_q24"],
                        "scores_q24": row["readout"]["scores_q24"],
                        "native_checkpoint_before": row["checkpoint_before"],
                        "native_checkpoint_after": row["checkpoint_after"],
                        "native_ndu_digest": row["readout"]["native_ndu_digest"],
                        "native_projection_count": row["projection_count"],
                        "native_input_feature_digest": row["input_feature_digest"],
                        "native_receipt_digest": row["receipt_digest"],
                    }
                )
            if retain:
                records[i]["steps"].append(record)
        states[alive] = trace["next_state_idx"]
        previous_failed[:] = 0
        previous_risk[:] = 0
        previous_failed[alive] = trace["failed"]
        previous_risk[alive] = np.array(
            [0.0 if x is None else x for x in trace["F_after_action"]]
        )
    for i, record in enumerate(records):
        record["reported_utility"] = float(total_utility[i])
        record["reported_net_utility"] = float(total_utility[i] - 1e-6 * total_bytes[i])
    return {
        "records": records,
        "utility": total_utility,
        "net_utility": total_utility - 1e-6 * total_bytes,
        "counts": counts,
    }


def behavior_data(context, seed, paths):
    """A shared exploratory history, independent of the trained actor/checkpoint."""
    model = context["model"]
    states, slots, _ = episode_streams(seed, "training", context, paths)
    previous_failed, previous_risk = np.zeros(paths), np.zeros(paths)
    data = []
    for elapsed in range(model.spec.horizon):
        remaining = model.spec.horizon - elapsed
        action = (slots[elapsed, :, 0] < 0.2).astype(int)
        trace = sample_step(model, states, action, uniforms=slots[elapsed, :, 1:])
        data.append(
            {
                "states": states.copy(),
                "remaining": remaining,
                "previous_failed": previous_failed.copy(),
                "previous_risk": previous_risk.copy(),
                "target_q": context["dp"]["q"][remaining - 1, states, :2] / 8.0,
                "actions": action,
                "next_states": trace["next_state_idx"].copy(),
                "uniforms": slots[elapsed].copy(),
                "active_time": trace["active_time"].copy(),
                "failed": trace["failed"].copy(),
            }
        )
        states = trace["next_state_idx"]
        previous_failed = trace["failed"].astype(float)
        previous_risk = np.asarray(trace["F_after_action"], dtype=float)
    return data


def training_features(
    contexts, histories, *, seed, arm, candidate, boundary_weights, bridge, profile_sha
):
    all_sequences, all_targets = [], []
    for context, history in zip(contexts, histories):
        adapter = ActorAdapter(
            context["model"].spec,
            context["dp"],
            arm,
            candidate,
            seed,
            boundary_weights=boundary_weights,
        )
        paths = len(history[0]["states"])
        sequences = [[] for _ in range(paths)]
        targets = [[] for _ in range(paths)]
        for row in history:
            values = adapter.step(
                row["states"],
                row["remaining"],
                row["previous_failed"],
                row["previous_risk"],
            )
            typed = feature_rows(values, range(paths))
            for i in range(paths):
                sequences[i].append(typed[i])
                targets[i].append(row["target_q"][i])
        all_sequences.extend(sequences)
        all_targets.extend(targets)
    result = bridge.kernel_batch(profile_sha, all_sequences)
    activations = (
        np.array(
            [r["activation_q24"] for sequence in result["sequences"] for r in sequence]
        )
        / Q
    )
    target = np.array([r for sequence in all_targets for r in sequence])
    return (
        activations,
        target,
        {
            "feature_matrix_sha256": sha(activations.tobytes()),
            "target_matrix_sha256": sha(target.tobytes()),
            "actual_kernel_calls": result["actual_kernel_calls"],
            "rows": len(target),
        },
    )
