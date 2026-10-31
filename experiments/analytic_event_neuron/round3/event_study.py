"""Development-only codec selection and actual post-action confirmation.

The immutable Round 2 baseline evaluator is reused for prior model kinds.
New event models execute a persistent packet receiver throughout each episode.
"""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .. import learners, task
from ..analytic import event_log_probs, event_probs
from ..round2 import evaluation as prior_evaluation
from ..round2.pulse import fit_event_models
from . import event_codec as codec


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


class PacketChannel:
    """Append, close, reopen and read the exact bytes accepted by the receiver."""

    def __init__(self, root, case, arm):
        self.root = Path(root)
        key = hashlib.sha256(json.dumps([case, arm], separators=(",", ":")).encode()).hexdigest()
        self.path = self.root / "event_packets" / (key + ".jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("xb"):
            pass
        self.offset = 0
        self.operations = []

    def __call__(self, payload):
        began = time.perf_counter_ns()
        with self.path.open("ab") as stream:
            stream.write(payload)
        written = time.perf_counter_ns()
        with self.path.open("rb") as stream:
            stream.seek(self.offset)
            readback = stream.read(len(payload))
            if stream.read(1):
                raise ValueError("Unexpected trailing event bytes")
        self.operations.append({"offset": self.offset, "bytes": len(payload),
                                "began_ns": began, "written_ns": written,
                                "readback_ns": time.perf_counter_ns(),
                                "sha256": hashlib.sha256(readback).hexdigest()})
        self.offset += len(payload)
        return readback

    def receipt(self):
        return {"path": str(self.path.relative_to(self.root)), "bytes": self.offset,
                "sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(),
                "operations": self.operations}


def _new_control(models, data, transport=None):
    observe = transport.observer if transport is not None else lambda case, arm, stage, value: value
    deliver = transport.deliver if transport is not None else lambda case, arm, stage, value, action: value
    public = task.history(data)
    rows, summary = [], {}
    for name, model in models.items():
        arm_rows = []
        for i, identity in enumerate(data["ids"]):
            identity = str(identity)
            started, cpu = time.perf_counter_ns(), time.process_time_ns()
            h = task.subset(public, i)
            initial_time = float(task.latest_time(h)[0])
            payload = prior_evaluation._public_payload(h)
            h = prior_evaluation._read_initial(h, observe(identity, name, "initial", payload))
            read_public = prior_evaluation._public_payload(h)
            initial_observation_ns = time.perf_counter_ns()
            multiplier = float(observe(identity, name, "terms", float(data["cost_multiplier"][i])))
            if not np.isfinite(multiplier) or multiplier <= 0:
                raise ValueError("Invalid public cost terms")
            terms_ns = time.perf_counter_ns()
            channel = PacketChannel(transport.root, identity, name) if transport is not None else None
            session = codec.Session(model, channel)
            session.sync(h)
            preview = float(deliver(identity, name, "initial", session.forecast(2.0)[0], "preview"))
            preview_ns = time.perf_counter_ns()
            stages, observations, cost_items, actions = [], [], [], []
            costs = 0.0

            def choose(horizon, stage):
                decision = session.decide(horizon, multiplier)
                prediction = session.forecast(horizon)[0]
                stages.append({"stage": stage, "horizon": horizon,
                    "decision_ns": time.perf_counter_ns(), "selected": decision["selected"],
                    "policy_mode": "decoded_variance_voi", "predicted_mean": prediction,
                    "expected_squared_error_plus_cost": decision["scores"],
                    "event_certificate": decision, "public_history": prior_evaluation._public_payload(h)})
                return decision["selected"], prediction

            def acquire(stage, value, timestamp, variance, suffix, cost):
                nonlocal h, costs
                costs += cost * multiplier
                cost_items.append({"action": suffix, "base_cost": cost, "multiplier": multiplier,
                                   "paid_cost": cost * multiplier})
                reopened = float(observe(identity, name, stage, float(value)))
                observations.append({"stage": stage, "value": reopened, "readback_ns": time.perf_counter_ns()})
                h = task.append_observation(h, reopened, timestamp, variance, suffix)
                session.sync(h)

            action, prediction = choose(2.0, "initial")
            actions.append(action)
            if action == "wait":
                acquire("wait", data["wait_observation"][i], initial_time + 1.0,
                        task.OBSERVATION_VARIANCE, "wait", task.WAIT_COST)
                action, prediction = choose(1.0, "wait")
                actions.append(action)
                if action == "repair":
                    acquire("wait_repair", data["wait_repair_observation"][i], initial_time + 1.0,
                            task.REPAIR_VARIANCE, "repair", task.REPAIR_COST)
                    prediction = session.forecast(1.0)[0]
            elif action == "repair":
                acquire("repair", data["repair_observation"][i], initial_time,
                        task.REPAIR_VARIANCE, "repair", task.REPAIR_COST)
                prediction = session.forecast(2.0)[0]
            submitted = float(deliver(identity, name, "final", prediction, "/".join(actions)))
            final_ns = time.perf_counter_ns()
            if not np.isfinite(submitted):
                raise ValueError("Nonfinite delivered prediction")
            score_ns = time.perf_counter_ns()
            # First terminal target read follows final text/PNG delivery/readback.
            target = float(data["future"][i, 4])
            square = (submitted - target) ** 2
            item = {"case": identity, "arm": name, "law": data["law"],
                "model_sha256": codec.digest(model), "initial_public_history": read_public,
                "initial_prediction": preview, "public_terms": {"cost_multiplier": multiplier,
                    "base_wait_cost": task.WAIT_COST, "base_repair_cost": task.REPAIR_COST},
                "initial_observation_ns": initial_observation_ns, "terms_readback_ns": terms_ns,
                "preview_readback_ns": preview_ns, "stages": stages, "observations": observations,
                "actions": actions, "paid_cost": costs, "cost_items": cost_items,
                "final_public_history": prior_evaluation._public_payload(h),
                "proposed_final_prediction": prediction, "delivered_prediction": submitted,
                "final_readback_ns": final_ns, "score_started_ns": score_ns,
                "terminal_target": target, "squared_error": square, "utility": 1.0 - square - costs,
                "severe_loss": bool(1.0 - square - costs < -2.0),
                "elapsed_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
                "actual_transport": transport is not None, "policy_mode": "decoded_variance_voi",
                "event_accounting": session.accounting(), "event_packets": session.encoder.packets,
                "packet_transport": channel.receipt() if channel is not None else None}
            arm_rows.append(item)
        rows.extend(arm_rows)
        summary[name] = _control_summary(arm_rows)
    return {"rows": rows, "summary": summary, "actual_transport": transport is not None,
            "private_target_first_read_after_final_delivery": True}


def _control_summary(rows):
    return {"mean_utility": float(np.mean([r["utility"] for r in rows])),
            "mean_squared_error": float(np.mean([r["squared_error"] for r in rows])),
            "mean_action_cost": float(np.mean([r["paid_cost"] for r in rows])),
            "severe_loss_fraction": float(np.mean([r["severe_loss"] for r in rows])),
            "action_sequences": {s: sum("/".join(r["actions"]) == s for r in rows)
                                 for s in sorted({"/".join(r["actions"]) for r in rows})},
            "wall_ns": sum(r["elapsed_ns"] for r in rows), "cpu_ns": sum(r["cpu_ns"] for r in rows),
            "event_packet_bytes": sum(r["event_accounting"]["packet_bytes"] for r in rows),
            "event_packets": sum(r["event_accounting"]["packets"] for r in rows),
            "logical_unit_events": sum(r["event_accounting"]["logical_unit_events"] for r in rows),
            "uncertified_decisions": sum(not s["event_certificate"]["certified"] for r in rows for s in r["stages"])}


def evaluate_prediction(models, data, native=None):
    history = task.history(data)
    targets = task.targets(data)[:, 1:]
    labels = task.event_labels(targets)
    rows, summary = [], {}
    for name, raw_model in models.items():
        model = prior_evaluation._model_for_law(raw_model, data)
        began = time.perf_counter_ns()
        mean, variance = codec.predict(model, history, native)
        mean, variance = mean[:, 1:], variance[:, 1:]
        probs = event_probs(mean, variance, task.LOWER, task.UPPER)
        logp = event_log_probs(mean, variance, task.LOWER, task.UPPER)
        nll = -np.take_along_axis(logp, labels[..., None], axis=-1)[..., 0]
        brier = np.sum((probs - np.eye(3)[labels]) ** 2, axis=-1)
        summary[name] = {"event_nll": float(nll.mean()), "brier": float(brier.mean()),
                         "mse": float(np.mean((mean - targets) ** 2)),
                         "evaluation_ns": time.perf_counter_ns() - began,
                         "trajectories": len(targets), "horizons": 3,
                         "scope": "initial history, before action-specific precision refinement"}
        for i, identity in enumerate(data["ids"]):
            rows.append({"case": str(identity), "arm": name, "law": data["law"],
                         "mean": mean[i].tolist(), "variance": variance[i].tolist(),
                         "probabilities": probs[i].tolist(), "targets": targets[i].tolist(),
                         "labels": labels[i].tolist(), "nll": nll[i].tolist(), "brier": brier[i].tolist()})
    return {"rows": rows, "summary": summary}


def confirm(models, data, native=None, transport=None):
    """No fitting; physical transport is mandatory for confirmation-labelled data."""
    if data["split"] == "confirmation" and transport is None:
        raise ValueError("Confirmation requires actual delivery/readback transport")
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    prediction = evaluate_prediction(models, data, native)
    new = {name: model for name, model in models.items() if model.get("kind") == codec.KIND}
    old = {name: model for name, model in models.items() if model.get("kind") != codec.KIND}
    prior = prior_evaluation.evaluate_control(old, data, native,
        observer=transport.observer if transport is not None else None,
        deliver=transport.deliver if transport is not None else None)
    current = _new_control(new, data, transport)
    control = {"rows": prior["rows"] + current["rows"],
               "summary": {**prior["summary"], **current["summary"]},
               "actual_transport": transport is not None,
               "private_target_first_read_after_final_delivery": True}
    return {"prediction": prediction, "control": control,
            "accounting": {"wall_ns": time.perf_counter_ns() - began,
                           "parent_cpu_ns": time.process_time_ns() - cpu,
                           "unique_trajectories": len(data["ids"]),
                           "control_rows": len(control["rows"]),
                           "prediction_rows": len(prediction["rows"]),
                           "cost_scope": "paid wait/repair task costs; packet bytes separate, no monetary or energy conversion"}}


def prepare(base_models, development, output_path, driver_receipt=None):
    """Select codec using realized development utility, NLL and physical bytes.

    Event choices qualify only with utility deficit <= .001, Gaussian NLL
    deficit <= .001, and (for adaptive) every development decision certified.
    Among qualifiers select minimum serialized bytes, then maximum utility.
    No qualifying candidate means explicit best-utility fallback, retained.
    """
    if development["split"] != "development":
        raise ValueError("Codec selection accepts development data only")
    driver = base_models["analytic"]
    if driver["kind"] != "filter":
        raise ValueError("Codec requires an actually fitted Gaussian driver")
    if driver_receipt is not None and driver_receipt["fitted_filter_parameters"] != driver["parameters"]:
        raise ValueError("Driver training receipt mismatch")
    baseline = prior_evaluation.evaluate_control({"analytic": driver}, development, include_fixed_policies=False)
    base_rows = baseline["rows"]
    base_utility = baseline["summary"]["analytic"]["mean_utility"]
    h, y = task.combine_training(development)
    base_nll = learners.nll(y, *learners.predict(driver, h))
    candidates, evaluated = [], []
    for adaptive in (True, False):
        for mean_bits in (6, 8, 10):
            for variance_bits in ((4, 6) if adaptive else (4, 6, 8, 10, 12)):
                config = codec.Config(mean_bits, variance_bits, 24 if adaptive else variance_bits, adaptive)
                model = {**driver, "kind": codec.KIND, "event_config": asdict(config),
                         "driver_sha256": codec.digest(driver), "training_scope": "fitted driver, finite development codec selection"}
                measured = _new_control({"candidate": model}, development)
                rows, metrics = measured["rows"], measured["summary"]["candidate"]
                nll = learners.nll(y, *codec.predict(model, h))
                utility = metrics["mean_utility"]
                disagreement = sum(a["actions"] != b["actions"] for a, b in zip(rows, base_rows))
                eligible = (utility >= base_utility - .001 and nll <= base_nll + .001
                            and (not adaptive or metrics["uncertified_decisions"] == 0))
                candidates.append({"config": asdict(config), "utility": utility,
                    "utility_deficit": base_utility - utility, "gaussian_nll": nll,
                    "nll_deficit": nll - base_nll, "eligible": eligible,
                    "action_disagreements_vs_continuous": disagreement, **metrics})
                evaluated.append(model)
    selected = {}
    for adaptive, name in ((True, "event_adaptive"), (False, "event_fixed")):
        indices = [i for i, x in enumerate(candidates) if x["config"]["adaptive"] == adaptive]
        eligible = [i for i in indices if candidates[i]["eligible"]]
        if eligible:
            index = min(eligible, key=lambda i: (candidates[i]["event_packet_bytes"], -candidates[i]["utility"], i))
        else:
            index = min(indices, key=lambda i: (-candidates[i]["utility"], candidates[i]["event_packet_bytes"], i))
        selected[name] = {"index": index, "eligible": bool(eligible)}
    keep = ("analytic", "equivalent_gaussian", "history", "native", "pulse", "oracle")
    models = {name: base_models[name] for name in keep if name in base_models}
    for name, choice in selected.items():
        models[name] = evaluated[choice["index"]]
    for name, mode in (("event_direct", "direct_quantization"), ("event_no_residual", "increment_only")):
        models[name] = {**models["event_adaptive"],
                        "event_config": {**models["event_adaptive"]["event_config"], "mode": mode}}
    old_models, old_selection = fit_event_models(base_models, development, driver_training_receipt=driver_receipt)
    models["event_round2"] = old_models["event_feedback"]
    receipt = {"schema": "hepta.decision-event.selection.v1", "selected": selected,
               "development_dataset_sha256": task.dataset_digest(development),
               "development_trajectories": len(development["ids"]),
               "baseline_utility": base_utility, "baseline_gaussian_nll": base_nll,
               "maximum_utility_deficit": .001, "maximum_gaussian_nll_deficit": .001,
               "candidate_count": len(candidates), "candidates": candidates,
               "selection_rule": "eligible minimum serialized packet bytes; utility then grid index tie breaks; explicit fallback",
               "driver_parameters": driver["parameters"],
               "driver_receipt_sha256": codec.digest(driver_receipt) if driver_receipt is not None else None,
               "driver_parameter_l2_change": driver_receipt.get("filter_parameter_l2_change") if driver_receipt else None,
               "optimizer_success": driver_receipt.get("optimizer_success") if driver_receipt else None,
               "round2_selection": old_selection, "model_sha256": codec.digest(models),
               "gradient_through_discrete_events_claimed": False}
    output_path = Path(output_path)
    _write(output_path / "MODELS.json", models)
    _write(output_path / "EVENT_SELECTION.json", receipt)
    return models, receipt
