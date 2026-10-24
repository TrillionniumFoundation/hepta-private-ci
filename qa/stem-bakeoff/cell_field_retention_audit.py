"""Independent retention control audit using forward paths and adjoint gradients.

No control solver, training-state class or evaluation module is imported.
Final labels are opened only by the separately requested score audit.
"""

import argparse
from collections import defaultdict
import itertools
import json
from pathlib import Path

import numpy as np

from cell_field_audit import (_checkpoint_vector, _load_arrays, _probability_and_gradient,
                              canonical, sha, verify_seal)
from cell_field_retention_score_audit import audit_evaluation


def plan_value_gradient(policy, start, observed, actions, dt, price, *, symmetric=False):
    """Direct rollout plus reverse adjoint; independent of condensed-map algebra."""
    F, D, C, target = (policy[key] for key in ("F", "D", "charged", "target"))
    states = [np.array(observed, dtype=float)]
    for local, action in enumerate(actions):
        k = start + local
        states.append(F[k] @ states[-1] + D[k] @ action)
    fields = np.array([C[start + local] @ value for local, value in enumerate(states)])
    errors = fields - target[start:start + len(fields)]
    if not symmetric:
        errors[:, 1] = np.maximum(errors[:, 1], 0)
    weights = np.r_[np.full(len(actions), dt), 1.0]
    value = 0.5 * float(np.sum(weights[:, None] * errors**2) + dt * price * np.sum(actions**2))
    adjoint = C[start + len(actions)].T @ errors[-1]
    gradient = np.empty_like(actions)
    for local in range(len(actions) - 1, -1, -1):
        k = start + local
        gradient[local] = dt * price * actions[local] + D[k].T @ adjoint
        adjoint = F[k].T @ adjoint + dt * C[k].T @ errors[local]
    return value, gradient, fields


def actual_cost(fields, actions, target, dt, price):
    errors = fields - target
    weights = np.r_[np.full(len(actions), dt), 1.0]
    current = 0.5 * float(weights @ errors[:, 0]**2)
    forgetting = 0.5 * float(weights @ np.maximum(errors[:, 1], 0)**2)
    effort = 0.5 * dt * price * float(np.sum(actions**2))
    symmetric = 0.5 * float(weights @ np.sum(errors**2, axis=1)) + effort
    return {"total": current + forgetting + effort, "current": current, "forgetting": forgetting,
            "tracking": current + forgetting, "effort": effort,
            "maximum_old_excess": float(errors[:, 1].max()),
            "terminal_old_excess": float(errors[-1, 1]),
            "old_violation_steps": int(np.count_nonzero(errors[:, 1] > 1e-12))}, symmetric


def adam_transition(vector, mode, features, labels, completed_steps, protocol):
    """Independent full-batch Adam update with the frozen default moment factors."""
    p, width = len(vector) // 3, features.shape[1]
    theta, momentum, variance = np.split(np.asarray(vector), 3)
    _, _, gradient = _probability_and_gradient(theta, mode, features, labels)
    regularized = width * 4 + (width if mode == "gated" else 0)
    gradient[:regularized] += protocol["l2"] * theta[:regularized]
    gradient *= min(1.0, protocol["gradient_clip"] / max(float(np.linalg.norm(gradient)), 1e-12))
    if protocol["beta1"] != 0.9 or protocol["beta2"] != 0.999:
        raise ValueError("undeclared optimizer coefficients")
    m = 0.9 * momentum + 0.1 * gradient
    v = 0.999 * variance + 0.001 * gradient * gradient
    step = completed_steps + 1
    new_theta = theta - protocol["learning_rate"] * (m / (1 - 0.9**step)) / (
        np.sqrt(v / (1 - 0.999**step)) + protocol["epsilon"])
    return np.concatenate((new_theta, m, v))


def audit_runs(run_dir, protocol_path, data_dir):
    root, data = Path(run_dir), Path(data_dir)
    seal = verify_seal(root)
    plan = json.loads(Path(protocol_path).read_bytes())
    runs = json.loads((root / "runs.json").read_bytes())
    if (sha(Path(protocol_path).read_bytes()) != seal["protocol_sha256"]
            or runs["protocol_sha256"] != seal["protocol_sha256"]
            or sha((data / "data_receipt.json").read_bytes()) != runs["data_receipt_sha256"]
            or plan["retention_tolerance"] != 0 or plan["optimizer"]["sampler"] != "full_batch"):
        raise ValueError("frozen protocol or data identity differs")
    records = runs["records"]
    keys = [(r["seed"], r["head"], r["mask"], r["policy"]) for r in records]
    wanted = list(itertools.product(plan["seeds"], plan["head_modes"], plan["action_masks"], plan["policies"]))
    initials = [(r["seed"], r["head"]) for r in runs["initial_order"]]
    if (len(keys) != len(wanted) or set(keys) != set(wanted) or seal["record_count"] != len(wanted)
            or runs["record_count"] != len(wanted)
            or len(initials) != len(plan["seeds"]) * len(plan["head_modes"])
            or set(initials) != set(itertools.product(plan["seeds"], plan["head_modes"]))
            or any(initials[r["initial_index"]] != (r["seed"], r["head"]) for r in records)):
        raise ValueError("registered condition or initial-state census differs")
    predictions = _load_arrays(root / "predictions.npz")
    features = _load_arrays(root / "projected_features.npz")["features"]
    label_bytes = (data / "train_labels.json").read_bytes()
    receipt = json.loads((data / "data_receipt.json").read_bytes())
    if sha(label_bytes) != receipt["files"]["train_labels.json"]["sha256"]:
        raise ValueError("training labels changed after preparation")
    labels = json.loads(label_bytes)["roles"]
    dt, price, horizon = plan["h"], plan["effort_price"], plan["horizon"]
    maxima, checked, solutions, largest_gap = defaultdict(float), 0, 0, 0.0

    def close(name, actual, expected, tolerance=3e-11):
        nonlocal checked
        a, b = np.asarray(actual), np.asarray(expected)
        if a.shape != b.shape or not np.isfinite(a).all() or not np.isfinite(b).all():
            raise ValueError("nonfinite or shape-mismatched audit field: " + name)
        error = float(np.max(np.abs(a - b))) if a.size else 0.0
        maxima[name] = max(maxima[name], error)
        checked += a.size
        scale = float(np.max(np.abs(b))) if b.size else 0.0
        if error > tolerance * (1 + scale):
            raise ValueError(f"independent {name} differs: {error}")

    def verify_plans(policy, trajectory, observations, solver_rows, mode, phase):
        nonlocal solutions, largest_gap
        if len(solver_rows) != horizon:
            raise ValueError("solver step census incomplete")
        for k, row in enumerate(solver_rows):
            length = 1 if mode == "myopic" else horizon - k
            if int(trajectory["plan_lengths"][k]) != length or row["step"] != k or row["horizon"] != length:
                raise ValueError("plan horizon or time index differs")
            controls = trajectory["planned_actions"][k, :length]
            close(phase + "_plan_padding", trajectory["planned_actions"][k, length:], np.zeros_like(trajectory["planned_actions"][k, length:]), 0)
            value, gradient, fields = plan_value_gradient(policy, k, observations[k], controls, dt, price,
                                                         symmetric=mode == "symmetric_loss2")
            close(phase + "_plan_fields", trajectory["planned_fields"][k, :length + 1], fields)
            close(phase + "_first_action", trajectory["actions"][k], controls[0], 0)
            close(phase + "_plan_value", row["objective"], value)
            squared = float(np.sum(gradient**2))
            close(phase + "_gradient_norm_squared", row["gradient_norm_squared"], squared)
            gap = squared / (2 * dt * price)
            close(phase + "_gap_bound", row["optimality_gap_bound"], gap)
            close(phase + "_strong_convexity", row["strong_convexity"], dt * price, 0)
            if row["objective_kind"] != ("symmetric" if mode == "symmetric_loss2" else "hinge"):
                raise ValueError("solver objective differs from registered policy")
            if mode == "zero":
                close(phase + "_zero_actions", controls, np.zeros_like(controls), 0)
            else:
                if (row["converged"] is not True or row["failure"] is not None
                        or row["iterations"] > plan["solver"]["max_iterations"]
                        or row["maximum_iterations"] != (0 if mode == "symmetric_loss2" else plan["solver"]["max_iterations"])
                        or gap > plan["solver"]["gap_tolerance"] * (1 + 1e-6) + 1e-14):
                    raise ValueError("unqualified numerical plan was deployed")
                solutions += 1
                largest_gap = max(largest_gap, gap)
            if mode == "symmetric_loss2":
                close(phase + "_legacy_feedback", controls[0], -policy["K"][k] @ observations[k] + policy["offset"][k])

    for number, initial in enumerate(runs["initial_order"]):
        if initial["status"] != "completed": continue
        vector, metadata = _checkpoint_vector(root / initial["path"])
        p = len(vector) // 3
        probability = _probability_and_gradient(vector[:p], initial["head"], features)[0]
        close("initial_probability", predictions["initial_probabilities"][number], probability)
        if metadata["step_count"] != plan["warmup_steps"]: raise ValueError("warmup step differs")
    failures, oracle_plans = [], {}
    for number, record in enumerate(records):
        if record["status"] != "completed":
            failures.append({"run_id": record["run_id"], "error": record.get("error")})
            continue
        paths, mode = record["paths"], record["policy"]
        reference = _load_arrays(root / paths["reference"])
        policy = _load_arrays(root / paths["controller"])
        actual, tangent = _load_arrays(root / paths["trajectory"]), _load_arrays(root / paths["tangent"])
        final, metadata = _checkpoint_vector(root / paths["checkpoint"])
        p = len(final) // 3
        close("terminal_checkpoint", actual["states"][-1], final, 0)
        if metadata["state_sha256"] != record["final_state_sha256"] or metadata["step_count"] != plan["warmup_steps"] + horizon:
            raise ValueError("terminal checkpoint metadata differs")
        close("initial_state", actual["states"][0], reference["reference_states"][0], 0)
        probability = _probability_and_gradient(final[:p], record["head"], features)[0]
        close("final_probability", predictions["probabilities"][number], probability)
        width = features.shape[1]
        bias_start = width * 4 + (width if record["head"] == "gated" else 0)
        indices = list(range(p)) if record["mask"] == "all" else list(range(bias_start, bias_start + 4))
        close("declared_mask", policy["B"], np.eye(p)[:, indices], 0)
        close("orthonormal_actions", policy["B"].T @ policy["B"], np.eye(policy["B"].shape[1]), 0)
        physical = np.vstack((dt * policy["B"], np.zeros((2 * p, policy["B"].shape[1]))))
        close("action_map", policy["E"], np.tile(physical / reference["state_scales"][:, None], (horizon, 1, 1)))
        expected_target = np.column_stack((np.full(horizon + 1, plan["current_target_displacement"]),
                                           reference["reference_observations"][0, 1] - reference["reference_observations"][:, 1]))
        close("common_target", policy["target"], expected_target, 0)
        if mode == "full":
            close("full_observation", policy["Cobs"], np.tile(np.eye(3 * p), (horizon + 1, 1, 1)), 0)
            close("full_dynamics", policy["F"], reference["A"], 0)
            close("full_action", policy["D"], policy["E"], 0)
            close("full_charged", policy["charged"], reference["C_extended"][:, :2], 0)
        else:
            q = 4 if mode == "extended" else 2
            close("field_observation", policy["Cobs"], reference["C_extended"][:, :q], 0)
            for k in range(horizon):
                close("projected_dynamics", policy["F"][k], policy["Cobs"][k + 1] @ reference["A"][k]
                      @ np.linalg.pinv(policy["Cobs"][k], rcond=1e-10))
                close("projected_action", policy["D"][k], policy["Cobs"][k + 1] @ policy["E"][k])
            close("field_charged", policy["charged"], np.tile(np.eye(q)[:2], (horizon + 1, 1, 1)), 0)
        for k, state in enumerate(actual["states"]):
            losses, interactions = [], []
            for role in ("current_probe", "old_probe"):
                split = labels[role]
                _, loss, gradient = _probability_and_gradient(state[:p], record["head"], features[split["indices"]], split["labels"])
                losses.append(loss); interactions.append(float(gradient @ state[p:2 * p]))
            close("nonlinear_observations", actual["observations"][k], losses + interactions)
            if k < horizon:
                split = labels["current_train"]
                next_state = adam_transition(state, record["head"], features[split["indices"]], split["labels"],
                                             plan["warmup_steps"] + k, plan["optimizer"])
                next_state[:p] += dt * policy["B"] @ actual["actions"][k]
                close("actual_adam_transition", actual["states"][k + 1], next_state)
        close("nonlinear_fields", actual["fields"], actual["observations"][:, :2] - reference["reference_observations"][:, :2])
        costs, symmetric = actual_cost(actual["fields"], actual["actions"], policy["target"], dt, price)
        for key, value in costs.items(): close("nonlinear_" + key, record["cost"][key], value)
        close("nonlinear_symmetric_cost", record["legacy_symmetric_cost"]["total"], symmetric)
        observed = ((actual["states"] - reference["reference_states"]) / reference["state_scales"]
                    if mode == "full" else actual["observations"][:, :policy["Cobs"].shape[1]]
                    - reference["reference_observations"][:, :policy["Cobs"].shape[1]])
        solver_rows = json.loads((root / paths["solver"]).read_bytes())
        tangent_rows = json.loads((root / paths["tangent_solver"]).read_bytes())
        verify_plans(policy, actual, observed, solver_rows, mode, "nonlinear")
        tangent_observed = np.einsum("kij,kj->ki", policy["Cobs"], tangent["states"])
        verify_plans(policy, tangent, tangent_observed, tangent_rows, mode, "tangent")
        close("tangent_initial", tangent["states"][0], np.zeros(3 * p), 0)
        for k in range(horizon):
            close("tangent_transition", tangent["states"][k + 1], reference["A"][k] @ tangent["states"][k]
                  + policy["E"][k] @ tangent["actions"][k])
            residual = policy["Cobs"][k + 1] @ reference["A"][k] - policy["F"][k] @ policy["Cobs"][k]
            forcing = np.linalg.norm(policy["charged"][k + 1] @ residual @ tangent["states"][k])
            close("charged_closure_forcing", tangent["charged_closure_forcing"][k], forcing)
        fields = np.einsum("kij,kj->ki", reference["C_extended"][:, :2], tangent["states"])
        close("tangent_fields", tangent["fields"], fields)
        if mode == "full":
            value, gradient, _ = plan_value_gradient(policy, 0, np.zeros(3 * p), tangent["planned_actions"][0], dt, price)
            gap = float(np.sum(gradient**2)) / (2 * dt * price)
            oracle_plans[(record["seed"], record["head"], record["mask"])] = (value, gap, policy, tangent["planned_actions"][0])
    nested = []
    for seed, head in itertools.product(plan["seeds"], plan["head_modes"]):
        a, b = oracle_plans.get((seed, head, "all")), oracle_plans.get((seed, head, "bias"))
        if a is None or b is None:
            nested.append({"seed": seed, "head": head, "status": "unavailable_failed_condition"})
            continue
        transform = a[2]["B"].T @ b[2]["B"]
        close("nested_mask_embedding", a[2]["B"] @ transform, b[2]["B"], 0)
        embedded = b[3] @ transform.T
        value = plan_value_gradient(a[2], 0, np.zeros(a[2]["F"].shape[1]), embedded, dt, price)[0]
        close("nested_objective_embedding", value, b[0])
        if a[0] - a[1] > b[0] + 1e-10:
            raise ValueError("nested optimum certificates are inconsistent")
        nested.append({"seed": seed, "head": head, "all_value_interval": [a[0] - a[1], a[0]],
                       "bias_value_interval": [b[0] - b[1], b[0]], "bias_embeds_in_all": True})
    return {"schema": "hepta.cell-retention-independent-run-audit.v2", "registered_records": len(records),
            "completed": len(records) - len(failures), "failures": failures,
            "sealed_files_verified": len(seal["files"]), "scalar_equalities_checked": checked,
            "maximum_absolute_errors": dict(maxima), "qualified_solutions_checked": solutions,
            "largest_recomputed_solver_gap_bound": largest_gap, "nested_oracles": nested,
            "solver_imported": False, "training_state_imported": False, "final_labels_file_opened": False,
            "pre_evaluation_seal_sha256": sha((root / "pre_evaluation_seal.json").read_bytes()),
            "auditor_sha256": sha(Path(__file__).read_bytes())}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("runs", "data", "protocol", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--evaluation")
    args = parser.parse_args()
    result = (audit_evaluation(args.runs, args.data, args.protocol, args.evaluation)
              if args.evaluation else audit_runs(args.runs, args.protocol, args.data))
    Path(args.output).write_bytes(canonical(result) + b"\n")
    print(json.dumps(result, indent=2))
