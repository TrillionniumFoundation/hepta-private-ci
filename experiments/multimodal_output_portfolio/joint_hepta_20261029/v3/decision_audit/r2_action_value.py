"""Development-only one-step value learning from retained actual actions.

This predicts a labelled utility increment less declared action costs. It is
neither the gamma-2 CE estimand nor a trained generator, planner or promotion
authority. Input commitments authenticate bytes, not independent label custody.
"""

import argparse
from dataclasses import asdict, is_dataclass
import hashlib
import json
import math
from pathlib import Path
import platform
import re
import signal
import time

import numpy as np

from .dual_runtime import ACTIONS
from .transition_capture import canonical, file_identity, write_new
from .transition_capture_read import read_capture, require


TEXT_FIELDS = ("instruction", "plan", "text", "critique")
VIEW_FIELDS = set(TEXT_FIELDS) | {"plan_version", "image_path", "history",
                                "remaining_decisions", "remaining_seconds"}
FEATURE_SCHEMA = "public-view-signed-sha256-4x32-numeric8-history7-v1"
WIDTH = 8 + len(ACTIONS) + 32 * len(TEXT_FIELDS)
FAILURES = {"failed", "timeout", "cancelled"}


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def finite(value, name):
    require(type(value) in (int, float) and math.isfinite(value), f"Nonfinite {name}")
    return float(value)


def features(view):
    """Encode only the public before-view; never read paths or evaluator data."""
    if is_dataclass(view):
        view = asdict(view)
    require(isinstance(view, dict) and set(view) == VIEW_FIELDS, "Hidden or missing View fields")
    version, remaining = view["plan_version"], view["remaining_decisions"]
    require(type(version) is int and 0 <= version <= 32, "Invalid plan version")
    require(type(remaining) is int and 0 <= remaining <= 32, "Invalid remaining decisions")
    seconds = finite(view["remaining_seconds"], "remaining seconds")
    require(seconds > 0, "Expired controller view")
    require(view["image_path"] is None or isinstance(view["image_path"], str), "Invalid image flag")
    history = view["history"]
    require(isinstance(history, (list, tuple)) and len(history) <= 32, "Invalid history")
    result = np.zeros(WIDTH, dtype=np.float64)
    result[:8] = (1, version / 32, remaining / 32, min(seconds, 600) / 600,
                  view["text"] is not None, view["image_path"] is not None,
                  bool(view["critique"]), len(history) / 32)
    for entry in history:
        require(isinstance(entry, (list, tuple)) and len(entry) == 2
                and entry[0] in ACTIONS and entry[1] == "ok", "Invalid public action history")
        result[8 + ACTIONS.index(entry[0])] += 1 / 32
    for field_index, field in enumerate(TEXT_FIELDS):
        value = view[field]
        require(isinstance(value, str) or (field == "text" and value is None), "Invalid public text")
        value = value or ""
        require(len(value) <= (4096 if field == "instruction" else 8192), "Oversized public text")
        start = 8 + len(ACTIONS) + field_index * 32
        for token in re.findall(r"\w+", value.lower()):
            raw = hashlib.sha256(token.encode("utf-8")).digest()
            result[start + raw[0] % 32] += 1 if raw[1] & 1 else -1
        norm = np.linalg.norm(result[start:start + 32])
        if norm:
            result[start:start + 32] /= norm
    return result


def source_pins():
    return {name: file_identity(Path(__file__).with_name(name))["sha256"] for name in
            ("r2_action_value.py", "dual_runtime.py", "transition_capture.py", "transition_capture_read.py")}


def parameter_hash(value):
    return hashlib.sha256(np.asarray(value, dtype="<f8").tobytes(order="C")).hexdigest()


def collect(bundle, base_directory, expected_sources, *, retained=None):
    """Use the existing capture reader; require a label for every observed action.

    An intent without an original action return/failure remains unlabelled and
    explicitly retained. Preflight, finalization and observer outer costs remain
    in the capture ledger, not silently assigned to an arbitrary training row.
    """
    require(bundle["purpose"] in ("development", "synthetic_control"), "Only development input allowed")
    roster = bundle["roster"]
    require(isinstance(roster, list) and 1 <= len(roster) <= 128, "Bounded capture roster required")
    manifest = bundle["label_manifest"]
    require(manifest["schema"] == "hepta.development-action-labels.v1", "Label schema")
    require(digest(manifest) == bundle["labels_sha256"], "Independent label bytes changed")
    require(isinstance(manifest["evaluator_id"], str) and manifest["evaluator_id"], "Missing evaluator identity")
    for name in ("evaluator_source_sha256", "rubric_sha256"):
        require(re.fullmatch("[0-9a-f]{64}", manifest[name]) is not None, "Missing evaluator/rubric pin")
    labels = {}
    for row in manifest["rows"]:
        key = (row["capture_id"], row["step"])
        require(key not in labels, "Duplicate action label")
        labels[key] = row
    retained = [] if retained is None else retained
    samples, eligible, identifiers, capture_hashes, split_owners = [], set(), set(), set(), {}
    for entry in roster:
        cid, split = entry["capture_id"], entry["split"]
        require(isinstance(cid, str) and cid and cid not in identifiers, "Duplicate capture identity")
        require(split in ("train", "development"), "Test/validation input is not training data")
        identifiers.add(cid)
        directory = Path(base_directory) / entry["directory"]
        actual = file_identity(directory / "transition_capture/SUMMARY.json")["sha256"]
        require(actual == entry["summary_sha256"] and actual not in capture_hashes, "Changed/reused capture")
        capture_hashes.add(actual)
        capture = read_capture(directory)
        require(file_identity(directory / "transition_capture/SUMMARY.json")["sha256"] == actual,
                "Capture changed while reading")
        start = capture["journal"][0]["payload"]
        require(start["settings"].get("observer_admission") == "fresh-after-capture-v1"
                and start["runtime_source"]["sha256"] == expected_sources["dual_runtime.py"]
                and start["recorder_source"]["sha256"] == expected_sources["transition_capture.py"],
                "Capture was not produced by the pinned actual-view runtime")
        source = start["declared_source"]
        require(source == entry["declared_source"] and source["split"] == split, "Source roster mismatch")
        cluster = entry["source_cluster_id"]
        require(isinstance(cluster, str) and cluster, "Missing source cluster")
        for key in (("cluster", cluster), ("source", source["source_id"]), ("image", source["image_sha256"])):
            require(split_owners.get(key, split) == split, "Train/development source overlap")
            split_owners[key] = split
        if bundle["purpose"] == "development" and (directory / "backend.json").is_file():
            require(not json.loads((directory / "backend.json").read_bytes()).get("synthetic_control_backend"),
                    "Synthetic backend cannot become real development evidence")
        by_step, step = {}, None
        for row in capture["journal"][1:-1]:
            if row["phase"] == "before_controller":
                step = row["payload"]["detail"]["step"]
            if step is not None and row["phase"] != "before_controller":
                by_step.setdefault(step, []).extend(row["payload"]["new_original_events"])
        omitted = []
        retained.append({"capture_id": cid, "summary_sha256": actual,
                         "status": capture["report"]["status"], "unlabelled_intents": omitted,
                         "original_cost": capture["summary"]["result"]["original_cost"],
                         "observer_costs": capture["summary"]["observation_costs"],
                         "observer_unknown_costs": capture["summary"]["unknown_costs"]})
        for transition in capture["transitions"]:
            action, step = transition.get("choice"), transition["step"]
            events = by_step.get(step, [])
            action_events = [e for e in events if e["action"] == action and action in ACTIONS]
            require(len(action_events) <= 1, "Repeated action terminal in one decision")
            if transition["before_view"] is None or not action_events:
                omitted.append({"step": step, "reason": "no_observed_action_terminal", "transition": transition})
                continue
            terminal = action_events[0]["status"]
            require(terminal in {"ok"} | FAILURES, "Unknown action terminal")
            outcome = terminal
            if transition is capture["transitions"][-1] and capture["report"]["status"] in FAILURES:
                # A returned action is not accepted delivery when the original
                # deadline or final identity/inventory check subsequently fails.
                outcome = capture["report"]["status"]
            key = (cid, step)
            eligible.add(key)
            require(key in labels, "Missing label for observed action, including failures")
            label = labels[key]
            require(label["transition_sha256"] == digest(transition), "Label bound to other actual transition")
            before, after = (finite(label[k], k) for k in ("utility_before", "utility_after"))
            require(-1 <= before <= 1 and -1 <= after <= 1, "Utility outside fixed scale")
            if outcome in FAILURES:
                require(after == bundle["config"]["failure_utility"], "Failure utility changed")
            elif transition.get("actual_after_state", {}).get("episode_status_so_far") == "abstained":
                require(after == 0, "Development abstention utility must be zero")
            measured = [e for e in events if e["action"] in ("controller", action)]
            cpu, wall = (math.fsum(e[k] for e in measured) for k in ("cpu_seconds", "wall_seconds"))
            cost = (bundle["config"]["cpu_tariff"] * cpu + bundle["config"]["wall_tariff"] * wall
                    + bundle["config"]["service_tariffs"][action])
            target = finite(after - before - finite(cost, "declared action cost"), "training target")
            samples.append({"key": key, "split": split, "features": features(transition["before_view"]),
                            "action": ACTIONS.index(action), "target": target,
                            "action_status": terminal, "outcome_status": outcome,
                            "observed_event_ids": [e["event_id"] for e in measured], "declared_cost": cost})
    require(set(labels) == eligible, "Label for an unobserved/unregistered action")
    require(any(s["split"] == "train" for s in samples), "No observed train action")
    return samples, retained


def validate_config(config):
    require(set(config) == {"seed", "updates", "learning_rate", "momentum", "l2", "maximum_cpu_seconds",
                           "maximum_wall_seconds", "cpu_tariff", "wall_tariff", "service_tariffs", "failure_utility"},
            "Unknown or missing training configuration")
    require(type(config["seed"]) is int and 0 <= config["seed"] < 2**63, "Invalid fit seed")
    require(type(config["updates"]) is int and 1 <= config["updates"] <= 10000, "Invalid update budget")
    for name in ("learning_rate", "maximum_cpu_seconds", "maximum_wall_seconds"):
        require(finite(config[name], name) > 0, "Nonpositive learning rate/budget")
    require(0 <= finite(config["momentum"], "momentum") < 1 and finite(config["l2"], "l2") >= 0,
            "Invalid optimizer")
    require(config["cpu_tariff"] == 0.02 and config["wall_tariff"] == 0.001, "Inherited CPU/wall tariff changed")
    require(config["failure_utility"] == -1.0, "Development failure utility must be declared -1")
    require(set(config["service_tariffs"]) == set(ACTIONS), "Missing real-action service mapping")
    for value in config["service_tariffs"].values():
        require(finite(value, "service tariff") >= 0, "Negative service tariff")


def fit(bundle, output, *, bundle_sha256, base_directory="."):
    """Run bounded full-batch SGD; every attempt gets a separate output directory."""
    started = time.process_time(), time.perf_counter()
    out = Path(output)
    out.mkdir(parents=True, exist_ok=False)
    report = {"schema": "hepta.r2.action-value-fit.v1", "status": "failed", "updates_completed": 0,
              "bundle_sha256": bundle_sha256, "custody_authenticated": False,
              "production_qualified": False, "no_update": True, "whole_cost_known": False,
              "retained_captures": [], "input_capture_costs_complete": False}
    weights = velocity = initial = None
    try:
        write_new(out / "INPUT.json", bundle)
        require(bundle["schema"] == "hepta.r2.action-value-training.v1", "Training bundle schema")
        require(digest(bundle) == bundle_sha256, "Predeclared bundle changed")
        config = bundle["config"]
        validate_config(config)
        pins = source_pins()
        report["source_pins"] = pins
        samples, retained = collect(bundle, base_directory, pins, retained=report["retained_captures"])
        report["input_capture_costs_complete"] = True
        write_new(out / "INPUT_RECEIPT.json", {"captures": retained, "source_pins": pins})
        training_rows = write_new(out / "TRAINING_ROWS.json", [
            {**sample, "features": sample["features"].tolist()} for sample in samples])
        train = [s for s in samples if s["split"] == "train"]
        x, a, y = np.stack([s["features"] for s in train]), np.array([s["action"] for s in train]), np.array([s["target"] for s in train])
        observed = np.unique(a)
        weights = np.zeros((len(ACTIONS), WIDTH), dtype=np.float64)
        weights[observed] = np.random.Generator(np.random.PCG64(config["seed"])).normal(0, 0.001, (len(observed), WIDTH))
        velocity = np.zeros_like(weights)
        initial = parameter_hash(weights)
        losses = []
        for update in range(config["updates"]):
            if (time.process_time() - started[0] >= config["maximum_cpu_seconds"]
                    or time.perf_counter() - started[1] >= config["maximum_wall_seconds"]):
                raise TimeoutError("Development fit budget reached; no automatic retry")
            with np.errstate(over="raise", invalid="raise", divide="raise"):
                residual = (weights[a] * x).sum(axis=1) - y
                losses.append(finite(float(np.mean(residual**2)), "training loss"))
                gradient = np.zeros_like(weights)
                np.add.at(gradient, a, 2 * residual[:, None] * x / len(train))
                gradient[observed] += config["l2"] * weights[observed]
                next_velocity = config["momentum"] * velocity + gradient
                next_weights = weights - config["learning_rate"] * next_velocity
                require(np.isfinite(next_weights).all() and np.isfinite(next_velocity).all(), "Nonfinite optimizer result")
                weights, velocity = next_weights, next_velocity
            report["updates_completed"] = update + 1
        report["loss_before_updates"] = losses
        development = [s for s in samples if s["split"] == "development"]
        unsupported = sorted({ACTIONS[s["action"]] for s in development if s["action"] not in observed})
        report["development_unsupported_actions"] = unsupported
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            report["train_mse_after"] = finite(float(np.mean(((weights[a] * x).sum(axis=1) - y)**2)), "training MSE")
            report["development_mse"] = (finite(float(np.mean([(weights[s["action"]] @ s["features"] - s["target"])**2
                                                             for s in development])), "development MSE")
                                         if development and not unsupported else None)
        require(source_pins() == pins, "Training source changed during execution")
        checkpoint = {"schema": "hepta.r2.action-value-checkpoint.v1", "feature_schema": FEATURE_SCHEMA,
                      "bundle_sha256": bundle_sha256, "purpose": bundle["purpose"], "config": config,
                      "training_rows": training_rows,
                      "source_pins": pins, "numpy_version": np.__version__, "python_version": platform.python_version(),
                      "actions": list(ACTIONS), "trained_actions": [ACTIONS[i] for i in observed],
                      "parameters": weights.tolist(), "initial_parameter_sha256": initial,
                      "parameter_sha256": parameter_hash(weights),
                      "optimizer": {"kind": "full_batch_sgd_momentum", "updates": config["updates"], "velocity": velocity.tolist()},
                      "custody_authenticated": False, "production_qualified": False, "no_update": True}
        identity = write_new(out / "checkpoint.json", checkpoint)
        report["checkpoint"] = identity
        if (time.process_time() - started[0] >= config["maximum_cpu_seconds"]
                or time.perf_counter() - started[1] >= config["maximum_wall_seconds"]):
            raise TimeoutError("Budget exceeded through checkpoint write; candidate retained, not qualified")
        report["status"] = "completed"
    except (Exception, KeyboardInterrupt) as error:
        report["status"] = "cancelled" if isinstance(error, KeyboardInterrupt) else "timeout" if isinstance(error, TimeoutError) else "failed"
        report["error"] = {"type": type(error).__name__, "message": str(error)}
        if weights is not None and np.isfinite(weights).all():
            try:
                report["partial_state"] = write_new(out / "partial_state.json", {
                    "initial_parameter_sha256": initial, "parameter_sha256": parameter_hash(weights),
                    "parameters": weights.tolist(), "velocity": velocity.tolist(),
                    "updates_completed": report["updates_completed"], "not_a_qualified_checkpoint": True})
            except (Exception, KeyboardInterrupt) as save_error:
                report["partial_state_write_error"] = {"type": type(save_error).__name__, "message": str(save_error)}
                if isinstance(save_error, KeyboardInterrupt):
                    report["status"] = "cancelled"
    report["metering"] = {"cpu_seconds": time.process_time() - started[0], "wall_seconds": time.perf_counter() - started[1],
                          "scope": "inclusive current-process fit through checkpoint write; do not add inner input receipts",
                          "unknown": ["energy_joules", "child_process_cpu", "this_final_report_write", "orchestration_and_imports"],
                          "hard_deadline_guarantee": False}
    try:
        identity = write_new(out / "FIT.json", report)
        return {**report, "fit_receipt": identity}
    except (Exception, KeyboardInterrupt) as error:
        return {**report, "status": "cancelled" if isinstance(error, KeyboardInterrupt) else "failed", "fit_receipt": None,
                "receipt_write_error": {"type": type(error).__name__, "message": str(error)}}


class ActionValue:
    """Pinned development predictor with no evaluator or generator access."""

    def __init__(self, path, expected_sha256, expected_fit_sha256):
        raw = Path(path).read_bytes()
        require(hashlib.sha256(raw).hexdigest() == expected_sha256, "Checkpoint bytes changed")
        receipt_bytes = Path(path).with_name("FIT.json").read_bytes()
        require(hashlib.sha256(receipt_bytes).hexdigest() == expected_fit_sha256, "Fit receipt bytes changed")
        receipt = json.loads(receipt_bytes)
        require(receipt["schema"] == "hepta.r2.action-value-fit.v1" and receipt["status"] == "completed"
                and receipt["checkpoint"] == {"bytes": len(raw), "sha256": expected_sha256},
                "Fit did not complete within its declared budget")
        model = json.loads(raw)
        require(model["schema"] == "hepta.r2.action-value-checkpoint.v1" and model["feature_schema"] == FEATURE_SCHEMA,
                "Checkpoint feature schema mismatch")
        require(model["purpose"] in ("development", "synthetic_control"), "Checkpoint is not development scoped")
        for value in (model, receipt):
            require(value["custody_authenticated"] is False and value["production_qualified"] is False
                    and value["no_update"] is True, "Development qualification was rewritten")
        require(model["source_pins"] == source_pins(), "Checkpoint belongs to different execution source")
        require(model["actions"] == list(ACTIONS) and model["numpy_version"] == np.__version__
                and model["python_version"] == platform.python_version(), "Numeric/action identity mismatch")
        validate_config(model["config"])
        require(model["optimizer"]["kind"] == "full_batch_sgd_momentum"
                and model["optimizer"]["updates"] == model["config"]["updates"] == receipt["updates_completed"],
                "Optimizer identity mismatch")
        require(receipt["bundle_sha256"] == model["bundle_sha256"]
                and receipt["source_pins"] == model["source_pins"], "Fit/checkpoint lineage mismatch")
        self.trained_actions = tuple(model["trained_actions"])
        require(self.trained_actions and len(set(self.trained_actions)) == len(self.trained_actions)
                and set(self.trained_actions) <= set(ACTIONS), "Invalid trained-action roster")
        self.weights = np.asarray(model["parameters"], dtype=np.float64)
        require(self.weights.shape == (len(ACTIONS), WIDTH) and np.isfinite(self.weights).all(), "Invalid parameters")
        require(parameter_hash(self.weights) == model["parameter_sha256"], "Parameter identity mismatch")
        velocity = np.asarray(model["optimizer"]["velocity"], dtype=np.float64)
        require(velocity.shape == self.weights.shape and np.isfinite(velocity).all(), "Missing optimizer state")
        self.weights.setflags(write=False)

    def predict(self, view, action):
        require(action in self.trained_actions, "No training observation for this action")
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            return finite(float(self.weights[ACTIONS.index(action)] @ features(view)), "prediction")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    trainer = sub.add_parser("fit")
    trainer.add_argument("--bundle", type=Path, required=True)
    trainer.add_argument("--bundle-sha256", required=True)
    trainer.add_argument("--output", type=Path, required=True)
    predictor = sub.add_parser("predict")
    predictor.add_argument("--checkpoint", type=Path, required=True)
    predictor.add_argument("--checkpoint-sha256", required=True)
    predictor.add_argument("--fit-sha256", required=True)
    predictor.add_argument("--query", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "fit":
        report = fit(json.loads(args.bundle.read_bytes()), args.output, bundle_sha256=args.bundle_sha256,
                     base_directory=args.bundle.parent)
        print(json.dumps(report, allow_nan=False))
        return 0 if report["status"] == "completed" else 1
    query = json.loads(args.query.read_bytes())
    require(set(query) == {"view", "action"}, "Prediction accepts only public View and action")
    model = ActionValue(args.checkpoint, args.checkpoint_sha256, args.fit_sha256)
    print(json.dumps({"predicted_one_step_net_gain": model.predict(query["view"], query["action"]),
                      "independent_observation": False, "no_update": True}, allow_nan=False))
    return 0


if __name__ == "__main__":
    def interrupt(signum, frame):
        raise KeyboardInterrupt(f"Signal {signum}")
    signal.signal(signal.SIGTERM, interrupt)
    raise SystemExit(main())
