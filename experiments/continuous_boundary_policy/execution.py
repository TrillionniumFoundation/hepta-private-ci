"""Closed-loop confirmation with actual native NDU decisions and raw evidence."""

from dataclasses import asdict

import numpy as np

from experiments.continuous_boundary_flow.math_model import sample_step
from experiments.continuous_boundary_flow.scenarios import episode_streams
from experiments.continuous_boundary_flow.native.adapter import ACTIONS, Q
from . import cells
from .common import OBJECTIVE, canonical, kind_for, sha
from .features import FeatureMap, native_rows


def run_context(
    context,
    *,
    seed,
    phase,
    paths,
    arm,
    checkpoint_sha256,
    checkpoint=None,
    bridge=None,
    retain=True,
):
    model, dp = context["model"], context["dp"]
    states, slots, eval_seed = episode_streams(seed, phase, context, paths)
    ids = [f"{seed}.{phase}.c{context['index']}.p{i}" for i in range(paths)]
    records = [
        {
            "schema": "hepta.continuous-boundary-policy.episode.v1",
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
        for case in ids
    ]
    previous_failed, previous_risk, previous_repair = [
        np.zeros(paths) for _ in range(3)
    ]
    hidden = np.zeros((paths, 6))
    total, total_bytes = np.zeros(paths), np.zeros(paths, dtype=int)
    mapping = None
    params = None
    if checkpoint is not None:
        mapping = FeatureMap(
            context, arm, checkpoint["candidate"], checkpoint.get("boundary_weights")
        )
        if arm == "native_sparse":
            bridge.kernel_reset(checkpoint["profile_sha256"], ids)
        else:
            params, kind = cells.deserialize(checkpoint["model"])
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
        if not len(alive):
            break
        remaining, before_states = model.spec.horizon - elapsed, states.copy()
        emitted, host_rows, values = None, None, None
        h_before = hidden[alive].copy()
        scores = quantized = resets = None
        wire_in = wire_out = 0
        if mapping is not None:
            full_values, full_reset = mapping.step(
                states, remaining, previous_failed, previous_risk, previous_repair
            )
            values, resets = full_values[alive], full_reset[alive]
            before = bridge.counters.copy()
            if arm == "native_sparse":
                emitted = native_rows(values)
                response = bridge.kernel_advance(
                    checkpoint["profile_sha256"],
                    [
                        {"case_id": ids[i], "features": f}
                        for i, f in zip(alive, emitted)
                    ],
                )
                host_rows = response["rows"]
                if [r["case_id"] for r in host_rows] != [ids[i] for i in alive]:
                    raise ValueError("Native sparse row order changed")
                action = np.array(
                    [ACTIONS.index(r["readout"]["action"]) for r in host_rows]
                )
                counts["actual_kernel_calls"] += response["actual_kernel_calls"]
            else:
                scores, h_after = cells.step(values, resets, h_before, params, kind)
                hidden[alive] = h_after
                quantized = np.rint(scores * Q).astype(np.int64)
                rows = []
                for j, i in enumerate(alive):
                    rows.append(
                        {
                            "row_id": f"{ids[i]}.t{elapsed}",
                            "model_sha256": checkpoint_sha256,
                            "objective_sha256": OBJECTIVE,
                            "observation_sha256": sha(
                                canonical(
                                    {
                                        "features": values[j].tolist(),
                                        "reset_fraction": float(resets[j]),
                                    }
                                )
                            ),
                            "state_sha256": sha(
                                canonical(
                                    {
                                        "before": h_before[j].tolist(),
                                        "after": h_after[j].tolist(),
                                    }
                                )
                            ),
                            "scores_q24": quantized[j].tolist(),
                        }
                    )
                response = bridge.decide_batch(rows)
                host_rows = response["rows"]
                if [r["row_id"] for r in host_rows] != [r["row_id"] for r in rows]:
                    raise ValueError("Native NDU row order changed")
                if response["actual_kernel_calls"] != 0:
                    raise ValueError(
                        "Continuous baseline unexpectedly executed sparse kernel"
                    )
                action = np.array([ACTIONS.index(r["action"]) for r in host_rows])
            counts["actual_ndu_calls"] += response["actual_ndu_calls"]
            counts["model_state_updates"] += len(alive)
            wire_in = bridge.counters["request_bytes"] - before["request_bytes"]
            wire_out = bridge.counters["response_bytes"] - before["response_bytes"]
            counts["wire_request_bytes"] += wire_in
            counts["wire_response_bytes"] += wire_out
        elif arm == "dp":
            action = 2 - np.argmax(dp["q"][remaining - 1, states[alive], ::-1], axis=-1)
        else:
            action = np.full(
                len(alive),
                {"always_keep": 0, "always_repair": 1, "always_stop": 2}[arm],
            )
        trace = sample_step(
            model, states[alive], action, uniforms=slots[elapsed, alive, 1:]
        )
        reward = model.gamma**elapsed * trace["reward"]
        total[alive] += reward
        message_bytes = 0 if mapping is None else 160 if arm == "native_sparse" else 24
        total_bytes[alive] += message_bytes
        counts["semantic_message_bytes"] += len(alive) * message_bytes
        counts["physical_environment_windows"] += len(alive)
        for j, i in enumerate(alive):
            target_q = dp["q"][remaining - 1, before_states[i]]
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
                "reward": float(trace["reward"][j]),
                "discounted_reward": float(reward[j]),
                "teacher_q": target_q.tolist(),
                "action_regret": float(np.max(target_q) - target_q[action[j]]),
                "source_kernel_calls": int(arm == "native_sparse"),
                "native_ndu_calls": int(mapping is not None),
                "semantic_message_bytes": message_bytes,
                "wire_request_bytes": wire_in // len(alive)
                + int(j < wire_in % len(alive)),
                "wire_response_bytes": wire_out // len(alive)
                + int(j < wire_out % len(alive)),
            }
            if mapping is not None:
                record.update(
                    features=values[j].tolist(), reset_fraction=float(resets[j])
                )
                if arm == "native_sparse":
                    record.update(native_features=emitted[j], native_row=host_rows[j])
                else:
                    record.update(
                        hidden_before=h_before[j].tolist(),
                        hidden_after=hidden[i].tolist(),
                        scores_float=scores[j].tolist(),
                        scores_q24=quantized[j].tolist(),
                        native_receipt=host_rows[j],
                    )
            if retain:
                records[i]["steps"].append(record)
        states[alive] = trace["next_state_idx"]
        previous_failed[:] = previous_risk[:] = previous_repair[:] = 0
        previous_failed[alive] = trace["failed"]
        previous_risk[alive] = [
            0.0 if f is None else f for f in trace["F_after_action"]
        ]
        previous_repair[alive] = (action == 1).astype(float)
    for i, record in enumerate(records):
        record["reported_utility"] = float(total[i])
        record["reported_net_utility"] = float(total[i] - 1e-6 * total_bytes[i])
    return {
        "records": records,
        "utility": total,
        "net_utility": total - 1e-6 * total_bytes,
        "counts": counts,
    }
