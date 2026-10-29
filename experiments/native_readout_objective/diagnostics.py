"""A held-out common ID state panel, with actual native decisions for every head."""

from pathlib import Path

import numpy as np

from experiments.continuous_boundary_flow.common import named_seed
from experiments.continuous_boundary_flow.execution import behavior_data
from experiments.continuous_boundary_flow.native.adapter import ACTIONS, Q, save_profile
from experiments.continuous_boundary_flow.scenarios import load_contexts
from experiments.continuous_boundary_policy.features import native_rows, training_arrays
from experiments.continuous_boundary_policy.training import native_profile

from .common import (
    ARMS,
    CANDIDATES,
    CostMeter,
    append_cost,
    context_file,
    open_bridge,
    read_json,
    save_json,
    sha,
    write_records,
)
from .head import actions


def same_state_panel(
    output, binary, seed, selected, source=None, *, context_count=4, paths=8
):
    output = Path(output)
    target = output / "diagnostics" / str(seed)
    target.mkdir(parents=True, exist_ok=False)
    setup = CostMeter()
    contexts = load_contexts(seed, "diagnostic", context_count)
    history_seed = named_seed(seed, "native-readout-objective:diagnostic-history.v1")
    histories = [behavior_data(context, history_seed, paths) for context in contexts]
    x, resets, q = training_arrays(contexts, histories, "native_sparse", CANDIDATES[1])
    if np.any(resets != 0):
        raise ValueError("Unexpected native reset in common diagnostic panel")
    context_file(output, seed, "diagnostic", contexts)
    arrays = {
        f"context_{i}_{name}": np.asarray([row[name] for row in history])
        for i, history in enumerate(histories)
        for name in history[0]
    }
    arrays.update(features=x, physical_q=q)
    array_path = target / "panel.npz"
    with array_path.open("xb") as stream:
        np.savez_compressed(stream, **arrays)
    setup_receipt = {
        "schema": "hepta.native-readout-objective.diagnostic-input.v1",
        "seed": seed,
        "history_seed": history_seed,
        "history_namespace": "native-readout-objective:diagnostic-history.v1",
        "context_count": context_count,
        "paths_per_context": paths,
        "domain": "ID",
        "path": str(array_path.relative_to(output)),
        "sha256": sha(array_path.read_bytes()),
        "features_sha256": sha(x.tobytes()),
        "physical_q_sha256": sha(q.tobytes()),
        "not_used_for_selection": True,
    }
    save_json(target / "INPUT.json", setup_receipt)
    append_cost(
        output, {"phase": "diagnostic_setup", "seed": seed, "cost": setup.finish()}
    )
    ids = [
        f"{seed}.diagnostic.c{c}.p{p}"
        for c in range(context_count)
        for p in range(paths)
    ]
    expected_activation, summaries = None, []
    for arm in ARMS:
        item = selected[seed, arm]
        checkpoint = read_json(output / item["path"])
        if sha((output / item["path"]).read_bytes()) != item["sha256"]:
            raise ValueError("Diagnostic selected checkpoint changed")
        coefficients = np.asarray(checkpoint["head_coefficients"])
        head, bias = np.zeros((3, 20)), np.zeros(3)
        head[:2], bias[:2] = coefficients[:-1].T, coefficients[-1]
        meter = CostMeter()
        profile_path, profile_sha = save_profile(
            target / "profiles",
            native_profile(
                seed, checkpoint["candidate"], head, bias, stage="transform"
            ),
        )
        bridge = open_bridge(binary, target / arm / "host", source)
        records, activations = [], []
        try:
            bridge.load_profile(profile_path, profile_sha)
            bridge.kernel_reset(profile_sha, ids)
            for elapsed, values in enumerate(x):
                emitted = native_rows(values)
                response = bridge.kernel_advance(
                    profile_sha,
                    [
                        {"case_id": case, "features": row}
                        for case, row in zip(ids, emitted)
                    ],
                )
                if (
                    [r["case_id"] for r in response["rows"]] != ids
                    or response["actual_kernel_calls"] != len(ids)
                    or response["actual_ndu_calls"] != len(ids)
                ):
                    raise ValueError("Common-panel original native execution changed")
                activation = np.asarray(
                    [r["activation_q24"] for r in response["rows"]], dtype=np.int64
                )
                activations.append(activation)
                float_scores = np.column_stack(
                    (
                        np.column_stack((activation / Q, np.ones(len(ids))))
                        @ coefficients,
                        np.zeros(len(ids)),
                    )
                )
                float_actions, teacher_actions = (
                    actions(float_scores),
                    actions(q[elapsed]),
                )
                for index, native in enumerate(response["rows"]):
                    chosen, float_chosen = (
                        ACTIONS.index(native["readout"]["action"]),
                        int(float_actions[index]),
                    )
                    teacher = q[elapsed, index]
                    native_regret, float_regret = (
                        float(teacher.max() - teacher[chosen]),
                        float(teacher.max() - teacher[float_chosen]),
                    )
                    records.append(
                        {
                            "schema": "hepta.native-readout-objective.diagnostic-row.v1",
                            "seed": seed,
                            "arm": arm,
                            "checkpoint_sha256": item["sha256"],
                            "profile_sha256": profile_sha,
                            "context_index": index // paths,
                            "path_index": index % paths,
                            "elapsed": elapsed,
                            "features": values[index].tolist(),
                            "native_features": emitted[index],
                            "native_row": native,
                            "physical_q": teacher.tolist(),
                            "teacher_action": int(teacher_actions[index]),
                            "scores_float": float_scores[index].tolist(),
                            "float_action": float_chosen,
                            "native_action": chosen,
                            "native_regret": native_regret,
                            "float_regret": float_regret,
                            "signed_quantization_regret": native_regret - float_regret,
                        }
                    )
        finally:
            native_cost = bridge.close()
        actual = np.asarray(activations)
        if expected_activation is None:
            expected_activation = actual
        elif not np.array_equal(expected_activation, actual):
            raise ValueError(
                "Native activations differ across supposedly identical state panels"
            )
        path = target / f"{arm}.jsonl.gz"
        shard = write_records(path, records)
        shard["path"] = str(path.relative_to(output))
        groups = {}
        for index, name in enumerate(["keep", "repair", "stop"]):
            rows = [r for r in records if r["teacher_action"] == index]
            groups[name] = {
                "count": len(rows),
                "mean_native_regret": None
                if not rows
                else float(np.mean([r["native_regret"] for r in rows])),
            }
        summary = {
            "arm": arm,
            "rows": len(records),
            "shard": shard,
            "profile_path": str(profile_path.relative_to(output)),
            "profile_sha256": profile_sha,
            "activation_q24_sha256": sha(actual.tobytes()),
            "teacher_conditioned_regret": groups,
            "action_disagreements": sum(
                r["native_action"] != r["float_action"] for r in records
            ),
            "mean_signed_quantization_regret": float(
                np.mean([r["signed_quantization_regret"] for r in records])
            ),
            "maximum_abs_score_error": max(
                abs(
                    r["scores_float"][a]
                    - r["native_row"]["readout"]["scores_q24"][a] / Q
                )
                for r in records
                for a in range(3)
            ),
            "actual_kernel_calls": native_cost["counters"]["actual_kernel_calls"],
            "actual_ndu_calls": native_cost["counters"]["actual_ndu_calls"],
            "semantic_message_bytes": 160 * len(records),
        }
        save_json(target / f"{arm}.SUMMARY.json", summary)
        summaries.append(summary)
        append_cost(
            output,
            {
                "phase": "diagnostic_panel",
                "seed": seed,
                "arm": arm,
                "cost": meter.finish(),
                "native_process_cost": native_cost,
            },
        )
    summary = {
        "schema": "hepta.native-readout-objective.common-panel.v1",
        "seed": seed,
        "scope": "descriptive ID-domain diagnostic; not confirmation episodes or model selection",
        "input": setup_receipt,
        "all_arms_activation_identical": True,
        "arms": summaries,
    }
    path = target / "SUMMARY.json"
    identity = save_json(path, summary)
    return {"seed": seed, "path": str(path.relative_to(output)), "sha256": identity}
