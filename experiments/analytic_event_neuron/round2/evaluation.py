"""Frozen-model prediction and action evaluation, with explicit artifact hooks."""

import hashlib
import json
import time

import numpy as np

from .. import task
from . import predictors as learners
from ..analytic import event_log_probs, event_probs


def _model_for_law(model, data):
    if model.get("known_law_reference_only"):
        return {**model, "parameters": [data["drift"], task.PROCESS_VARIANCE, 1.0]}
    return model


def evaluate_prediction(models, data, native=None):
    public = task.history(data)
    target = task.targets(data)[:, 1:]
    labels = task.event_labels(target)
    one_hot = np.eye(3)[labels]
    rows, summary = [], {}
    for name, raw_model in models.items():
        model = _model_for_law(raw_model, data)
        started = time.perf_counter_ns()
        means, variances = learners.predict(model, public, native)
        means, variances = means[:, 1:], variances[:, 1:]
        probability = event_probs(means, variances, task.LOWER, task.UPPER)
        log_probability = event_log_probs(means, variances, task.LOWER, task.UPPER)
        losses = -np.take_along_axis(log_probability, labels[..., None], axis=-1)[..., 0]
        brier = np.sum((probability - one_hot) ** 2, axis=-1)
        accuracy = (probability.argmax(-1) == labels)
        elapsed = time.perf_counter_ns() - started
        summary[name] = {"event_nll": float(losses.mean()), "brier": float(brier.mean()),
                         "accuracy": float(accuracy.mean()), "mse": float(((means - target) ** 2).mean()),
                         "evaluation_ns": elapsed, "trajectories": len(target), "horizons": 3}
        for i, identity in enumerate(data["ids"]):
            rows.append({"case": str(identity), "arm": name, "law": data["law"],
                         "mean": means[i].tolist(), "variance": variances[i].tolist(),
                         "probabilities": probability[i].tolist(), "targets": target[i].tolist(),
                         "labels": labels[i].tolist(), "nll": losses[i].tolist(), "brier": brier[i].tolist()})
    return {"rows": rows, "summary": summary}


def _public_payload(h):
    return {key: h[key][0].tolist() for key in ("obs", "times", "mask", "occupied", "obs_var")}


def _read_initial(h, payload):
    result = {key: np.array(value, copy=True) for key, value in h.items()}
    for key in ("obs", "times", "mask", "occupied", "obs_var"):
        supplied = np.asarray(payload[key], dtype=h[key].dtype)
        if supplied.shape != (8,):
            raise ValueError("Readback changed the public history schema")
        result[key][0] = supplied
    return result


def evaluate_control(models, data, native=None, observer=None, deliver=None, include_fixed_policies=True):
    """Each policy sees only acquired readbacks. The target is read after delivery.

    observer(case, arm, stage, value) returns actual reopened observation.
    deliver(case, arm, stage, prediction, action) returns reopened prediction.
    Identity hooks are allowed for development and are explicitly reported.
    """
    using_transport = observer is not None and deliver is not None
    observe = observer if observer is not None else lambda case, arm, stage, value: value
    output = deliver if deliver is not None else lambda case, arm, stage, prediction, action: prediction
    base = task.history(data)
    rows, summary = [], {}
    arms = [(name, model, None) for name, model in models.items()]
    if include_fixed_policies and "analytic" in models:
        arms.extend((name, models["analytic"], name) for name in
                    ("always_stop", "always_repair", "always_wait", "always_wait_repair"))
    for name, raw_model, fixed_policy in arms:
        model = _model_for_law(raw_model, data)
        model_digest = hashlib.sha256(json.dumps(model, sort_keys=True).encode()).hexdigest()
        arm_rows = []
        for i, identity in enumerate(data["ids"]):
            identity = str(identity)
            started = time.perf_counter_ns()
            cpu_started = time.process_time_ns()
            h = task.subset(base, i)
            initial_time = float(task.latest_time(h)[0])
            raw_public = _public_payload(h)
            read_public = observe(identity, name, "initial", raw_public)
            h = _read_initial(h, read_public)
            read_public = _public_payload(h)
            initial_observation_ns = time.perf_counter_ns()
            cost_multiplier = float(observe(identity, name, "terms", float(data["cost_multiplier"][i])))
            if not np.isfinite(cost_multiplier) or cost_multiplier <= 0:
                raise ValueError("Invalid public action-cost terms")
            terms_readback_ns = time.perf_counter_ns()
            initial_mean, _ = learners.forecast(model, h, 2.0, native)
            preview = float(output(identity, name, "initial", float(initial_mean[0]), "preview"))
            preview_readback_ns = time.perf_counter_ns()
            actions, stage_records, observations = [], [], []
            cost_items = []
            costs = 0.0

            def choose(current, horizon, stage):
                mean, scores, diagnostics = learners.value_scores(model, current, horizon, native, cost_multiplier)
                legal = ("stop", "repair", "wait") if horizon > 1.5 else ("stop", "repair")
                selected = min(legal, key=lambda action: (float(scores[action][0]), legal.index(action)))
                if fixed_policy:
                    if stage == "initial":
                        selected = {"always_stop": "stop", "always_repair": "repair",
                                    "always_wait": "wait", "always_wait_repair": "wait"}[fixed_policy]
                    else:
                        selected = "repair" if fixed_policy == "always_wait_repair" else "stop"
                stage_records.append({"stage": stage, "horizon": horizon,
                    "decision_ns": time.perf_counter_ns(), "selected": selected,
                    "policy_mode": fixed_policy or "variance_voi",
                    "predicted_mean": float(mean[0]),
                    "expected_squared_error_plus_cost": {key: float(value[0]) for key, value in scores.items()},
                    "diagnostics": {key: float(value[0]) if isinstance(value, np.ndarray) else float(value)
                                    for key, value in diagnostics.items()},
                    "public_history": _public_payload(current)})
                return selected, float(mean[0])

            action, prediction = choose(h, 2.0, "initial")
            actions.append(action)
            if action == "wait":
                costs += task.WAIT_COST * cost_multiplier
                cost_items.append({"action": "wait", "base_cost": task.WAIT_COST,
                                   "multiplier": cost_multiplier, "paid_cost": task.WAIT_COST * cost_multiplier})
                value = float(observe(identity, name, "wait", float(data["wait_observation"][i])))
                observations.append({"stage": "wait", "value": value, "readback_ns": time.perf_counter_ns()})
                h = task.append_observation(h, value, initial_time + 1.0, task.OBSERVATION_VARIANCE, "wait")
                action, prediction = choose(h, 1.0, "wait")
                actions.append(action)
                if action == "repair":
                    costs += task.REPAIR_COST * cost_multiplier
                    cost_items.append({"action": "repair", "base_cost": task.REPAIR_COST,
                                       "multiplier": cost_multiplier, "paid_cost": task.REPAIR_COST * cost_multiplier})
                    value = float(observe(identity, name, "wait_repair", float(data["wait_repair_observation"][i])))
                    observations.append({"stage": "wait_repair", "value": value, "readback_ns": time.perf_counter_ns()})
                    h = task.append_observation(h, value, initial_time + 1.0, task.REPAIR_VARIANCE, "repair")
                    prediction = float(learners.forecast(model, h, 1.0, native)[0][0])
            elif action == "repair":
                costs += task.REPAIR_COST * cost_multiplier
                cost_items.append({"action": "repair", "base_cost": task.REPAIR_COST,
                                   "multiplier": cost_multiplier, "paid_cost": task.REPAIR_COST * cost_multiplier})
                value = float(observe(identity, name, "repair", float(data["repair_observation"][i])))
                observations.append({"stage": "repair", "value": value, "readback_ns": time.perf_counter_ns()})
                h = task.append_observation(h, value, initial_time, task.REPAIR_VARIANCE, "repair")
                prediction = float(learners.forecast(model, h, 2.0, native)[0][0])
            submitted = float(output(identity, name, "final", prediction, "/".join(actions)))
            final_readback_ns = time.perf_counter_ns()
            if not np.isfinite(submitted):
                raise ValueError("Nonfinite delivered prediction")
            # This is the first latent terminal-target read in this episode.
            score_started_ns = time.perf_counter_ns()
            target = float(data["future"][i, 4])
            square = (submitted - target) ** 2
            record = {"case": identity, "arm": name, "law": data["law"], "model_sha256": model_digest,
                "initial_public_history": read_public, "initial_prediction": preview,
                "public_terms": {"cost_multiplier": cost_multiplier, "base_wait_cost": task.WAIT_COST,
                                 "base_repair_cost": task.REPAIR_COST}, "terms_readback_ns": terms_readback_ns,
                "policy_mode": fixed_policy or "variance_voi",
                "initial_observation_ns": initial_observation_ns, "preview_readback_ns": preview_readback_ns,
                "stages": stage_records, "observations": observations, "actions": actions,
                "paid_cost": costs, "cost_items": cost_items, "final_public_history": _public_payload(h),
                "proposed_final_prediction": prediction, "delivered_prediction": submitted,
                "final_readback_ns": final_readback_ns, "score_started_ns": score_started_ns,
                "terminal_target": target, "squared_error": square, "utility": 1.0 - square - costs,
                "severe_loss": bool(1.0 - square - costs < -2.0),
                "elapsed_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu_started,
                "actual_transport": using_transport,
                "randomness": {"seed": model.get("seed"), "trajectory": identity, "counter": "physical_history_tick"},
                "oracle_scope": "known-parameter linear filter; not a nonlinear Student-t Bayes oracle" if name == "oracle" else None}
            arm_rows.append(record)
        rows.extend(arm_rows)
        summary[name] = {"mean_utility": float(np.mean([r["utility"] for r in arm_rows])),
            "mean_squared_error": float(np.mean([r["squared_error"] for r in arm_rows])),
            "mean_action_cost": float(np.mean([r["paid_cost"] for r in arm_rows])),
            "severe_loss_fraction": float(np.mean([r["severe_loss"] for r in arm_rows])),
            "wait_count": sum("wait" in r["actions"] for r in arm_rows),
            "repair_count": sum("repair" in r["actions"] for r in arm_rows),
            "action_sequences": {sequence: sum("/".join(r["actions"]) == sequence for r in arm_rows)
                                 for sequence in sorted({"/".join(r["actions"]) for r in arm_rows})},
            "utility_quantiles_05_50_95": np.quantile([r["utility"] for r in arm_rows], [0.05, 0.5, 0.95]).tolist(),
            "wall_ns": sum(r["elapsed_ns"] for r in arm_rows), "cpu_ns": sum(r["cpu_ns"] for r in arm_rows)}
    return {"rows": rows, "summary": summary,
            "actual_transport": using_transport, "private_target_first_read_after_final_delivery": True}
