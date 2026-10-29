"""Independent common-state native execution and signed quantization audit."""

import numpy as np

from experiments.continuous_boundary_policy.audit_cell import hash_text, q24_multiply
from experiments.continuous_boundary_policy.audit_math import rng

from .audit_core import (
    LEARNED,
    Q,
    canonical,
    checked_file,
    close,
    read,
    require,
    sha,
    strict_json,
)
from .audit_training import load_shard, replay_histories


def selected(values):
    return max(range(3), key=lambda index: (values[index], index))


def regret_values(q, native_action, float_action):
    maximum = float(np.max(q))
    native, floating = (
        maximum - float(q[native_action]),
        maximum - float(q[float_action]),
    )
    return native, floating, native - floating


def audit_native_row(record, profile, previous, case_id, elapsed):
    """Check an actual transform-stage row without pretending to emulate sparse_tick."""
    x, row = record["features"], record["native_row"]
    expected = {
        "raw_q24": [round(v * Q) for v in x[:15] + x[16:]],
        "continuous": {
            "margin_q24": round(x[11] * Q),
            "risk_q24": round(x[14] * Q),
            "flow_q24": round(x[15] * Q),
        },
    }
    require(record["native_features"] == expected, "Common-panel native input changed")
    require(
        row["case_id"] == case_id
        and row["step"] == elapsed + 1
        and row["checkpoint_before"] == previous
        and row["terminal"] is False
        and row["profile_masks"] == [True, True, True]
        and row["event_kind"] == "continuous_readout",
        "Diagnostic native state/phase chain changed",
    )
    activation = row["activation_q24"]
    require(
        len(activation) == 20
        and all(type(v) is int and 0 <= v <= 8 * Q for v in activation),
        "Diagnostic native activation bound violated",
    )
    scores = [
        b + sum(q24_multiply(w, a) for w, a in zip(weights, activation))
        for weights, b in zip(profile["head_weights_q24"], profile["head_bias_q24"])
    ]
    action = selected(scores)
    require(
        row["readout"]["scores_q24"] == scores
        and row["readout"]["action"] == ("keep", "repair", "stop")[action],
        "Diagnostic original NDU differs from exact integer readout",
    )
    frontier = [
        name
        for name, value in zip(("keep", "repair", "abstain"), scores)
        if value == max(scores)
    ]
    require(
        sorted(row["readout"]["native_ndu_frontier"]) == sorted(frontier)
        and row["readout"]["tie"] == (len(frontier) > 1),
        "Diagnostic NDU tie/frontier changed",
    )
    for key in ("checkpoint_after", "input_feature_digest", "temporal_digest"):
        hash_text(row[key], key)
    hash_text(row["readout"]["native_ndu_digest"], "diagnostic original NDU")
    require(
        row["receipt_digest"]
        == sha(canonical({k: v for k, v in row.items() if k != "receipt_digest"})),
        "Diagnostic original native receipt hash mismatch",
    )
    return action, scores, row["checkpoint_after"]


def verify_panel(root, item, seed, refs, checkpoints, profiles, contexts=4, paths=8):
    require(
        item["seed"] == seed and item["path"] == f"diagnostics/{seed}/SUMMARY.json",
        "Diagnostic panel identity changed",
    )
    summary = strict_json(checked_file(root, item["path"], item["sha256"]).read_bytes())
    require(
        summary["schema"] == "hepta.native-readout-objective.common-panel.v1"
        and summary["seed"] == seed
        and summary["all_arms_activation_identical"] is True,
        "Diagnostic panel scope changed",
    )
    input_name = f"diagnostics/{seed}/INPUT.json"
    receipt = read(root, input_name)
    history_seed = rng(seed, "native-readout-objective:diagnostic-history.v1")[1]
    require(
        summary["input"] == receipt
        and receipt["schema"] == "hepta.native-readout-objective.diagnostic-input.v1"
        and receipt["seed"] == seed
        and receipt["history_seed"] == history_seed
        and receipt["history_namespace"]
        == "native-readout-objective:diagnostic-history.v1"
        and receipt["context_count"] == contexts
        and receipt["paths_per_context"] == paths
        and receipt["domain"] == "ID"
        and receipt["not_used_for_selection"] is True
        and receipt["path"] == f"diagnostics/{seed}/panel.npz",
        "Common-state panel data phase/independent innovation stream changed",
    )
    with np.load(
        checked_file(root, receipt["path"], receipt["sha256"]), allow_pickle=False
    ) as data:
        expected_x, expected_q = replay_histories(
            data,
            seed,
            "diagnostic",
            refs,
            contexts,
            paths,
            history_seed=history_seed,
            extra_fields=("features", "physical_q"),
        )
        close(data["features"], expected_x, "diagnostic causal features", atol=2e-12)
        close(data["physical_q"], expected_q, "diagnostic physical Q", atol=2e-12)
        require(
            receipt["features_sha256"] == sha(data["features"].tobytes())
            and receipt["physical_q_sha256"] == sha(data["physical_q"].tobytes()),
            "Diagnostic common-input hashes changed",
        )
    files = {item["path"], input_name, receipt["path"]}
    verified, seen, counts, common_activation = {}, set(), {}, None
    for arm_summary in summary["arms"]:
        arm = arm_summary["arm"]
        require(
            arm in LEARNED and arm not in seen,
            "Diagnostic arm duplicated or undeclared",
        )
        seen.add(arm)
        summary_name = f"diagnostics/{seed}/{arm}.SUMMARY.json"
        require(
            read(root, summary_name) == arm_summary, "Diagnostic summary copies differ"
        )
        checkpoint, identity = checkpoints[seed, arm]
        profile = strict_json(
            checked_file(
                root, arm_summary["profile_path"], arm_summary["profile_sha256"]
            ).read_bytes()
        )
        require(
            profile == dict(profiles[seed, arm], stage="transform"),
            "Diagnostic head or frozen encoder differs from selected native model",
        )
        shard = arm_summary["shard"]
        require(
            shard["path"] == f"diagnostics/{seed}/{arm}.jsonl.gz",
            "Diagnostic raw path changed",
        )
        records = load_shard(root, shard)
        require(
            len(records) == contexts * paths * 12 == arm_summary["rows"],
            "Incomplete diagnostic state roster",
        )
        states = ["0" * 64] * (contexts * paths)
        activation, native_regret, float_regret, teachers, flips, score_errors = (
            [],
            [],
            [],
            [],
            [],
            [],
        )
        for order, row in enumerate(records):
            elapsed, sequence = divmod(order, contexts * paths)
            context, path = divmod(sequence, paths)
            require(
                row["schema"] == "hepta.native-readout-objective.diagnostic-row.v1"
                and row["seed"] == seed
                and row["arm"] == arm
                and row["checkpoint_sha256"] == identity
                and row["profile_sha256"] == arm_summary["profile_sha256"]
                and (row["elapsed"], row["context_index"], row["path_index"])
                == (elapsed, context, path),
                "Diagnostic row/selected-model/order mismatch",
            )
            close(
                row["features"],
                expected_x[elapsed, sequence],
                "common diagnostic row features",
                atol=2e-12,
            )
            q = expected_q[elapsed, sequence]
            close(
                row["physical_q"], q, "common diagnostic physical teacher", atol=2e-12
            )
            chosen, integer_scores, states[sequence] = audit_native_row(
                row,
                profile,
                states[sequence],
                f"{seed}.diagnostic.c{context}.p{path}",
                elapsed,
            )
            a = np.asarray(row["native_row"]["activation_q24"], dtype=np.int64)
            weights = np.asarray(checkpoint["head_coefficients"])
            floats = np.r_[np.r_[a / Q, 1.0] @ weights, 0.0]
            expected_float, teacher = selected(floats), selected(q)
            native_loss, float_loss, signed_delta = regret_values(
                q, chosen, expected_float
            )
            require(
                row["native_action"] == chosen
                and row["float_action"] == expected_float
                and row["teacher_action"] == teacher,
                "Diagnostic action/tie mismatch",
            )
            close(
                row["scores_float"],
                floats,
                "diagnostic unclamped float readout",
                atol=2e-12,
            )
            close(
                [
                    row["native_regret"],
                    row["float_regret"],
                    row["signed_quantization_regret"],
                ],
                [native_loss, float_loss, signed_delta],
                "signed diagnostic regret",
                atol=2e-12,
            )
            activation.append(a)
            native_regret.append(native_loss)
            float_regret.append(float_loss)
            teachers.append(teacher)
            flips.append(chosen != expected_float)
            score_errors.append(
                float(np.max(np.abs(floats - np.asarray(integer_scores) / Q)))
            )
        actual = np.asarray(activation).reshape(12, contexts * paths, 20)
        require(
            sha(actual.tobytes()) == arm_summary["activation_q24_sha256"],
            "Diagnostic activation digest changed",
        )
        require(
            common_activation is None or np.array_equal(common_activation, actual),
            "Selected heads did not receive identical native activation sequences",
        )
        common_activation = actual
        groups = {}
        for index, name in enumerate(("keep", "repair", "stop")):
            subset = np.asarray(native_regret)[np.asarray(teachers) == index]
            groups[name] = {
                "count": len(subset),
                "mean_native_regret": float(subset.mean()) if len(subset) else None,
            }
            saved = arm_summary["teacher_conditioned_regret"][name]
            require(
                saved["count"] == len(subset),
                "Teacher-conditioned diagnostic sample count changed",
            )
            if len(subset):
                close(
                    saved["mean_native_regret"],
                    subset.mean(),
                    "teacher-conditioned action regret",
                )
            else:
                require(
                    saved["mean_native_regret"] is None,
                    "Empty teacher class was reported as measured",
                )
        delta = np.asarray(native_regret) - float_regret
        require(
            arm_summary["action_disagreements"] == sum(flips),
            "Diagnostic flip count changed",
        )
        close(
            arm_summary["mean_signed_quantization_regret"],
            delta.mean(),
            "signed quantization regret mean",
        )
        close(
            arm_summary["maximum_abs_score_error"],
            max(score_errors),
            "quantization score error",
        )
        require(
            arm_summary["actual_kernel_calls"]
            == arm_summary["actual_ndu_calls"]
            == len(records)
            and arm_summary["semantic_message_bytes"] == 160 * len(records),
            "Diagnostic native costs changed",
        )
        counts[seed, arm] = {
            "source_kernel_calls": len(records),
            "native_ndu_calls": len(records),
            "semantic_message_bytes": 160 * len(records),
            "wire_request_bytes": 0,
            "wire_response_bytes": 0,
        }
        for elapsed in range(12):
            group = records[
                elapsed * contexts * paths : (elapsed + 1) * contexts * paths
            ]
            request = {
                "command": "KernelAdvance",
                "profile_sha256": arm_summary["profile_sha256"],
                "observations": [
                    {
                        "case_id": r["native_row"]["case_id"],
                        "features": r["native_features"],
                    }
                    for r in group
                ],
            }
            response = {
                "rows": [r["native_row"] for r in group],
                "actual_kernel_calls": len(group),
                "actual_ndu_calls": len(group),
                "durable_owner_execution": False,
                "owner_authority": "DENY_ALL",
                "profile_sha256": arm_summary["profile_sha256"],
            }
            counts[seed, arm]["wire_request_bytes"] += len(canonical(request)) + 1
            counts[seed, arm]["wire_response_bytes"] += len(canonical(response)) + 1
        verified[arm] = {
            "rows": len(records),
            "teacher_conditioned_regret": groups,
            "mean_native_regret": float(np.mean(native_regret)),
            "mean_float_regret": float(np.mean(float_regret)),
            "mean_signed_quantization_regret": float(delta.mean()),
            "quantization_harmed_rows": int(np.sum(delta > 0)),
            "quantization_helped_rows": int(np.sum(delta < 0)),
            "action_disagreements": int(sum(flips)),
            "maximum_abs_score_error": max(score_errors),
        }
        files |= {summary_name, arm_summary["profile_path"], shard["path"]}
    require(seen == set(LEARNED), "Incomplete diagnostic head roster")
    return {"seed": seed, "arms": verified}, counts, files
