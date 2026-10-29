"""Independent public trajectory, teacher-unit and optimizer reconstruction."""

import gzip

import numpy as np

from experiments.continuous_boundary_policy.audit_math import verify_physics

from .audit_core import (
    Q,
    checked_file,
    close,
    expected_features,
    expected_specs,
    read,
    require,
    sha,
    streams,
    strict_json,
    prior_profile,
)


def training_arrays(root, seed, refs, contexts=12, paths=8):
    meta = read(root, f"datasets/{seed}/training.json")
    require(
        meta["phase"] == "training"
        and meta["seed"] == seed
        and meta["contexts"] == expected_specs(seed, "training", contexts),
        "Public training data belongs to another phase",
    )
    source = checked_file(root, meta["path"], meta["sha256"])
    with np.load(source, allow_pickle=False) as data:
        return replay_histories(data, seed, "training", refs, contexts, paths)


def replay_histories(
    data, seed, phase, refs, contexts, paths, history_seed=None, extra_fields=()
):
    features, targets = [], []
    fields = (
        "states",
        "remaining",
        "previous_failed",
        "previous_risk",
        "target_q",
        "actions",
        "next_states",
        "uniforms",
        "active_time",
        "failed",
    )
    require(
        set(data.files)
        == {f"context_{i}_{name}" for i in range(contexts) for name in fields}
        | set(extra_fields),
        "Public training array roster changed",
    )
    for index in range(contexts):
        ref = refs[seed, phase, index]
        model, spec = ref["model"], vars(ref["model"].spec)
        # Original behavior_data always uses its training stream label; the
        # common diagnostic panel supplies a separately namespaced root seed.
        initial, slots, _ = streams(
            seed if history_seed is None else history_seed,
            "training",
            index,
            paths,
            ref,
        )
        values = {name: data[f"context_{index}_{name}"] for name in fields}
        states = values["states"]
        require(
            states.shape == (12, paths)
            and values["remaining"].tolist() == list(range(12, 0, -1))
            and np.array_equal(states[0], initial)
            and np.array_equal(values["uniforms"], slots),
            "Training state/deadline/random roster changed",
        )
        require(
            np.array_equal(values["actions"], slots[:, :, 0] < 0.2)
            and np.array_equal(states[1:], values["next_states"][:-1]),
            "Training behavior or physical chain changed",
        )
        x, q = np.zeros((12, paths, 18)), np.zeros((12, paths, 3))
        previous_failed, previous_risk, previous_repair = np.zeros((3, paths))
        for elapsed in range(12):
            close(
                values["previous_failed"][elapsed],
                previous_failed,
                "training previous failure",
            )
            close(
                values["previous_risk"][elapsed],
                previous_risk,
                "training previous risk",
            )
            require(
                np.all((states[elapsed] >= 0) & (states[elapsed] < 64)),
                "Invalid training state",
            )
            q[elapsed] = ref["q"][11 - elapsed, states[elapsed]]
            close(
                values["target_q"][elapsed] * 8,
                q[elapsed, :, :2],
                "physical teacher units (exactly one division by eight)",
                atol=2e-12,
            )
            for path_index in range(paths):
                state = int(states[elapsed, path_index])
                u = slots[elapsed, path_index]
                repair = bool(values["actions"][elapsed, path_index])
                failed = bool(values["failed"][elapsed, path_index])
                duration = float(values["active_time"][elapsed, path_index])
                after = (
                    int(
                        np.searchsorted(
                            np.cumsum(model.maintenance_distribution),
                            u[1],
                            side="right",
                        )
                    )
                    if repair
                    else state
                )
                rate = spec["discount"]
                reward = spec["production_rate"] * (
                    -np.expm1(-rate * duration) / rate if rate else duration
                )
                reward -= failed * spec["failure_cost"] * np.exp(-rate * duration)
                reward -= repair * spec["maintenance_cost"]
                step = {
                    "elapsed": elapsed,
                    "state_idx": state,
                    "x": float(model.x[state]),
                    "action": "repair" if repair else "wait",
                    "uniforms": u.tolist(),
                    "x_after_action": float(model.x[after]),
                    "failed": failed,
                    "active_time": duration,
                    "tau_hit": duration if failed else None,
                    "predicted_risk": float(model.F[after]),
                    "next_state_idx": int(values["next_states"][elapsed, path_index]),
                    "reward": float(reward),
                    "discounted_reward": float(reward * model.gamma**elapsed),
                }
                verify_physics(step, ref)
                x[elapsed, path_index], reset = expected_features(
                    ref,
                    {"arm": "native_sparse"},
                    state,
                    12 - elapsed,
                    previous_failed[path_index],
                    previous_risk[path_index],
                    previous_repair[path_index],
                )
                require(reset == 0, "Training sparse state was spuriously reset")
                (
                    previous_failed[path_index],
                    previous_risk[path_index],
                    previous_repair[path_index],
                ) = failed, model.F[after], repair
        features.append(x)
        targets.append(q)
    return np.concatenate(features, axis=1), np.concatenate(targets, axis=1)


def load_shard(root, item):
    compressed = checked_file(root, item["path"], item["sha256"]).read_bytes()
    raw = gzip.decompress(compressed)
    require(
        sha(raw) == item["uncompressed_sha256"]
        and len(raw) == item["uncompressed_bytes"],
        "Uncompressed evidence identity mismatch",
    )
    rows = [strict_json(line) for line in raw.splitlines()]
    require(len(rows) == item["count"], "Evidence row count changed")
    return rows


def verify_export(root, seed, expected_x, expected_q, contexts=12, paths=8):
    receipt = read(root, f"datasets/{seed}/FEATURE_EXPORT.json")
    require(
        receipt["seed"] == seed
        and receipt["phase"] == "training"
        and receipt["shared_by_all_arms_and_candidates"] is True,
        "Feature export identity/shared scope changed",
    )
    path = checked_file(root, receipt["path"], receipt["sha256"])
    with np.load(path, allow_pickle=False) as data:
        require(
            set(data.files)
            == {
                "activation_q24",
                "physical_q",
                "features",
                "sequence_context",
                "sequence_path",
            },
            "Native activation export array roster changed",
        )
        require(
            np.array_equal(
                data["sequence_context"], np.repeat(np.arange(contexts), paths)
            )
            and np.array_equal(
                data["sequence_path"], np.tile(np.arange(paths), contexts)
            ),
            "Native sequence ordering changed",
        )
        close(
            data["features"],
            expected_x,
            "common information/causal training features",
            atol=2e-12,
        )
        physical = expected_q.transpose(1, 0, 2).reshape(-1, 3)
        close(
            data["physical_q"], physical, "exported physical teacher units", atol=2e-12
        )
        activation = data["activation_q24"].copy()
        require(
            activation.shape == (12 * contexts * paths, 20)
            and np.issubdtype(activation.dtype, np.integer)
            and np.all((activation >= 0) & (activation <= 8 * Q)),
            "Native activation domain changed",
        )
        for name, array in (
            ("activation_q24", activation),
            ("physical_q", data["physical_q"]),
            ("features", data["features"]),
        ):
            require(
                receipt[name + "_sha256"] == sha(array.tobytes()),
                "Common input array hash mismatch",
            )
        physical = data["physical_q"].copy()
    require(
        receipt["actual_kernel_calls"] == receipt["rows"] == len(activation)
        and receipt["sequence_count"] == contexts * paths
        and receipt["actual_ndu_calls"] == 0,
        "Feature export native work count mismatch",
    )
    profile = strict_json(
        checked_file(
            root, receipt["profile_path"], receipt["profile_sha256"]
        ).read_bytes()
    )
    require(
        profile["stage"] == "transform"
        and profile["head_weights_q24"] == [[0] * 20] * 3
        and profile["head_bias_q24"] == [0, 0, 0],
        "Training export used a policy head",
    )
    prior_profile(dict(profile, stage="act"), seed)
    batches = load_shard(root, receipt["native_export"])
    require(len(batches) == 1, "Unexpected native export batch count")
    batch, rows = batches[0], []
    require(
        len(batch["request_sequences"]) == contexts * paths,
        "Missing native export sequences",
    )
    for b, sequence in enumerate(batch["request_sequences"]):
        require(len(sequence) == 12, "Truncated native export sequence")
        for elapsed, typed in enumerate(sequence):
            x = expected_x[elapsed, b]
            expected = {
                "raw_q24": [round(float(v) * Q) for v in np.r_[x[:15], x[16:]]],
                "continuous": {
                    "margin_q24": round(float(x[11]) * Q),
                    "risk_q24": round(float(x[14]) * Q),
                    "flow_q24": round(float(x[15]) * Q),
                },
            }
            require(
                typed == expected, "Native export request changed common information"
            )
    response = batch["response"]
    require(
        response["schema"] == "hepta.continuous-boundary.kernel-batch.v1"
        and response["profile_sha256"] == receipt["profile_sha256"]
        and response["owner_authority"] == "DENY_ALL"
        and response["durable_owner_execution"] is False
        and response["actual_kernel_calls"] == len(activation)
        and len(response["sequences"]) == contexts * paths,
        "Invalid original native batch response",
    )
    for sequence in response["sequences"]:
        require(len(sequence) == 12, "Truncated original native output")
        for row in sequence:
            rows.append(row["activation_q24"])
            require(
                len(row["threshold_q24"]) == len(row["eligibility_q24"]) == 20,
                "Native internal state width changed",
            )
            require(
                all(type(v) is int and 0 <= v <= Q // 2 for v in row["threshold_q24"]),
                "Native homeostatic threshold bound violated",
            )
            for field in ("checkpoint", "temporal_digest"):
                require(
                    isinstance(row[field], str)
                    and len(row[field]) == 64
                    and all(c in "0123456789abcdef" for c in row[field]),
                    "Malformed native export digest",
                )
    require(
        np.array_equal(np.asarray(rows), activation),
        "Training arrays differ from actual native export",
    )
    return activation / Q, physical, receipt


def independent_loss(design, teacher, weights, objective, penalty=1e-4):
    """Separate gradient arithmetic; no import of head.loss_and_grad or fit."""
    scores = np.c_[design @ weights, np.zeros(len(design))]
    if objective == "q_mse":
        error = scores[:, :2] - teacher[:, :2] / 8
        loss = np.sum(error * error) / (2 * len(design))
        derivative = error / len(design)
    else:
        maximum = np.max(scores, axis=1)
        exponents = np.exp(scores - maximum[:, None])
        denominator = np.sum(exponents, axis=1)
        probability = exponents / denominator[:, None]
        label = 2 - np.argmax(teacher[:, ::-1], axis=1)
        regret = np.max(teacher, axis=1)[:, None] - teacher
        regret /= (1 + np.max(regret, axis=1))[:, None]
        average = np.einsum("ij,ij->i", probability, regret)
        ce = maximum + np.log(denominator) - scores[np.arange(len(scores)), label]
        loss = np.mean(ce + average)
        derivative = probability * (1 + regret - average[:, None])
        derivative[np.arange(len(scores)), label] -= 1
        derivative = derivative[:, :2] / len(design)
    gradient = design.T @ derivative
    gradient[:-1] += penalty * weights[:-1] / 20
    loss += penalty * np.sum(weights[:-1] * weights[:-1]) / 40
    return float(loss), gradient


def replay_optimizer(
    activation, teacher, objective, learning_rate, epochs=120, diagnostics=False
):
    design = np.c_[activation, np.ones(len(activation))]
    weights = np.zeros((21, 2))
    first, second = np.zeros_like(weights), np.zeros_like(weights)
    losses, seen, clipped, projected = [], np.zeros((21, 2), dtype=bool), 0, 0
    for iteration in range(1, epochs + 1):
        loss, gradient = independent_loss(design, teacher, weights, objective)
        losses.append(loss)
        seen |= gradient != 0
        factor = min(1, 5 / max(float(np.sqrt(np.sum(gradient * gradient))), 1e-30))
        clipped += int(factor < 1)
        gradient *= factor
        first = 0.9 * first + 0.1 * gradient
        second = 0.999 * second + 0.001 * gradient * gradient
        corrected = (first / (1 - 0.9**iteration)) / (
            np.sqrt(second / (1 - 0.999**iteration)) + 1e-8
        )
        raw = weights - learning_rate * corrected
        weights = np.maximum(-7.5, np.minimum(7.5, raw))
        projected += int(np.count_nonzero(raw != weights))
    final, _ = independent_loss(design, teacher, weights, objective)
    result = weights, losses, final
    if diagnostics:
        return (
            *result,
            {
                "coordinates_with_nonzero_gradient": int(seen.sum()),
                "gradient_clipped_steps": clipped,
                "projected_coordinate_updates": projected,
            },
        )
    return result


def replay_ridge(activation, teacher, penalty):
    design = np.c_[activation, np.ones(len(activation))]
    scale = np.maximum(np.std(design, axis=0), 0.15)
    scale[-1] = 1
    scaled = design / scale
    regularizer = penalty * len(design) * np.eye(21)
    regularizer[-1, -1] = 1e-10
    weights = (
        np.linalg.solve(
            scaled.T @ scaled + regularizer, scaled.T @ (teacher[:, :2] / 8)
        )
        / scale[:, None]
    )
    return weights / max(1, float(np.max(np.abs(weights))) / 7.5)


def verify_fit(item, checkpoint, activation, physical_q, epochs=120):
    index, arm = checkpoint["candidate_index"], checkpoint["arm"]
    weights = np.asarray(checkpoint["head_coefficients"], dtype=float)
    fit = item["fit"]
    if arm == "ridge_reference":
        require(fit["head_scalars"] == 42, "Ridge readout budget changed")
        expected = replay_ridge(activation, physical_q, [0.001, 0.01, 0.1][index])
    else:
        objective = "q_mse" if arm == "iterative_q_mse" else "policy_regret"
        required = {
            "objective": objective,
            "epochs": epochs,
            "gradient_evaluations": epochs + 2,
            "optimizer": "full-batch Adam",
            "q_mse_teacher_scale": 8.0,
            "policy_temperature": 1.0,
            "learning_rate": [0.005, 0.02, 0.05][index],
            "adam_beta1": 0.9,
            "adam_beta2": 0.999,
            "adam_epsilon": 1e-8,
            "gradient_norm_bound": 5,
            "coefficient_bound": 7.5,
            "regularization": 1e-4,
            "trainable_scalars": 42,
            "initialization": "exact zero, 42 coefficients",
            "training_rows": len(activation),
            "native_kernel_executed": False,
            "native_ndu_executed": False,
        }
        require(
            all(fit.get(k) == value for k, value in required.items()),
            "Unmatched optimizer contract",
        )
        require(
            fit["activation_sha256"]
            == sha(np.asarray(activation, dtype="<f8").tobytes())
            and fit["physical_teacher_sha256"]
            == sha(np.asarray(physical_q, dtype="<f8").tobytes()),
            "Optimizer used a different common activation or teacher",
        )
        expected, losses, final, diagnostics = replay_optimizer(
            activation,
            physical_q,
            objective,
            [0.005, 0.02, 0.05][index],
            epochs,
            diagnostics=True,
        )
        require(
            all(fit[k] == value for k, value in diagnostics.items()),
            "Optimizer coverage/projection counters changed",
        )
        close(
            fit["coefficient_change_l2"],
            np.linalg.norm(expected),
            "optimizer coefficient movement",
        )
        close(
            fit["epoch_loss"],
            losses,
            "independently reconstructed optimizer trajectory",
            atol=2e-10,
        )
        close(fit["initial_loss"], losses[0], "optimizer initial loss", atol=2e-10)
        close(fit["final_loss"], final, "optimizer final loss", atol=2e-10)
    close(weights, expected, "independently retrained readout coefficients", atol=2e-9)
