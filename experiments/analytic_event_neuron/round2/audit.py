"""Independent evidence accounting and offline replay; never evaluates a policy.

This module does not import experiment, transport, runner, or statistics. It
reopens every retained artifact and independently decodes the numeric PNGs.
The already numerically validated analytic law and frozen model inference are
reused; loss aggregation, chronology, costs, and decisions are recomputed here.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import struct
import time

import numpy as np
from PIL import Image

from ..analytic import event_log_probs
from . import predictors as learners

FIELDS = ("obs", "times", "mask", "occupied", "obs_var")
FIXED = ("always_stop", "always_repair", "always_wait", "always_wait_repair")
LOWER, UPPER, WAIT_COST, REPAIR_COST = -0.6, 0.6, 0.07, 0.12


def _sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _json(path):
    return json.loads(Path(path).read_text())


def _jsonl(path):
    with Path(path).open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _under(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Evidence path escapes its declared root")
    return path


class _Audit:
    def __init__(self):
        self.counts = Counter()
        self.maximum_absolute_error = 0.0

    def require(self, condition, group, detail):
        self.counts[group] += 1
        if not condition:
            raise AssertionError(f"{group}: {detail}")

    def close(self, actual, expected, group, detail, exact=False):
        a, b = np.asarray(actual), np.asarray(expected)
        finite = np.isfinite(a).all() and np.isfinite(b).all()
        ok = a.shape == b.shape and finite
        if ok:
            difference = float(np.max(np.abs(a.astype(float) - b.astype(float)), initial=0.0))
            self.maximum_absolute_error = max(self.maximum_absolute_error, difference)
            ok = np.array_equal(a, b) if exact else np.allclose(a, b, rtol=2e-10, atol=2e-11)
        self.require(ok, group, detail)


def _png_value(path):
    """Independent integer bit accumulator, including all redundant pixels."""
    with Image.open(path) as image:
        if (image.format, image.mode, image.size) != ("PNG", "L", (256, 32)):
            raise ValueError("Invalid PNG transport schema")
        pixels = np.array(image, copy=True)
    integer = 0
    for column in range(64):
        block = pixels[:, 4 * column:4 * column + 4]
        value = int(block[0, 0])
        if value not in (0, 255) or np.any(block[:16] != value) or np.any(block[16:] != 255 - value):
            raise ValueError("PNG bit block or complement is corrupted")
        integer = (integer << 1) | (value == 255)
    number = struct.unpack(">d", int(integer).to_bytes(8, "big"))[0]
    if not np.isfinite(number):
        raise ValueError("Nonfinite PNG prediction")
    return number


def audit_freeze(run_dir, projectroot):
    audit, run_dir, projectroot = _Audit(), Path(run_dir), Path(projectroot)
    result = {"schema": "hepta.analytic-event.round2.freeze-audit.v1"}
    try:
        frozen = _json(run_dir / "FREEZE.json")
        for key, root in (("sources_sha256", projectroot), ("artifacts_sha256", run_dir)):
            audit.require(bool(frozen[key]), "freeze", f"Empty {key}")
            for relative, expected in frozen[key].items():
                audit.require(_sha(_under(root, relative)) == expected, "freeze", relative)
        result.update(passed=True, source_commit=frozen["source_commit"])
    except (AssertionError, ValueError, KeyError, OSError, TypeError) as error:
        result.update(passed=False, error=str(error))
    result["checks"] = dict(audit.counts)
    return result


def _load_data(scope, audit):
    metadata = _json(scope / "DATASET.json")
    audit.require(_sha(scope / "DATA.npz") == metadata["npz_sha256"], "dataset", "NPZ bytes")
    with np.load(scope / "DATA.npz", allow_pickle=False) as loaded:
        data = {key: loaded[key].item() if loaded[key].ndim == 0 else loaded[key].copy() for key in loaded.files}
    digest = hashlib.sha256()
    for key in sorted(data):
        value = data[key]
        digest.update(key.encode())
        digest.update(value.tobytes() if isinstance(value, np.ndarray) else str(value).encode())
    audit.require(digest.hexdigest() == metadata["dataset_digest"], "dataset", "Logical dataset bytes")
    audit.require(len(set(data["ids"])) == len(data["ids"]), "dataset", "Unique trajectory identities")
    if "data_seed" in metadata:
        audit.require(metadata["data_seed"] == data["seed"], "dataset", "Declared data seed")
    return data


def _histories(data):
    n = len(data["ids"])
    initial = {"obs": np.zeros((n, 8)), "times": np.zeros((n, 8)),
               "mask": np.zeros((n, 8), bool), "occupied": np.zeros((n, 8), bool),
               "obs_var": np.ones((n, 8)), "ids": data["ids"].copy()}
    for key in ("obs", "times", "mask", "obs_var"):
        initial[key][:, :6] = data[key]
    initial["occupied"][:, :6] = True
    stages = {"initial": initial}
    for stage in ("repair", "wait", "wait_repair"):
        h = {key: value.copy() for key, value in initial.items()}
        names = ("repair",) if stage == "repair" else ("wait", "wait_repair") if stage == "wait_repair" else ("wait",)
        for column, name in enumerate(names, 6):
            h["obs"][:, column] = data[name + "_observation"]
            h["times"][:, column] = data["times"][:, -1] + (name != "repair")
            h["mask"][:, column] = h["occupied"][:, column] = True
            h["obs_var"][:, column] = 0.64 if name == "wait" else 0.04
            suffix = "wait" if name == "wait" else "repair"
            h["ids"] = np.array([f"{identity}/{suffix}" for identity in h["ids"]])
        stages[stage] = h
    return stages


def _public_equal(audit, actual, h, row, label):
    audit.require(set(actual) == set(FIELDS), "public_history", label + " fields")
    for field in FIELDS:
        audit.close(actual[field], h[field][row], "public_history", label + "/" + field, exact=True)


def _model(model, data):
    return {**model, "parameters": [data["drift"], 0.18, 1.0]} if model.get("known_law_reference_only") else model


def _scores(model, mean, variance, j, multiplier):
    p, terminal = variance[0], variance[j]
    repair_noise = 0.04 * model["planning_noise_scale"]
    result = {"stop": terminal,
              "repair": max(0.0, terminal - p * p / (p + repair_noise)) + REPAIR_COST * multiplier}
    if j == 3:
        propagated = p + model["planning_q"]
        sensor = 0.64 * model["planning_noise_scale"]
        posterior = 1.0 / (1.0 / propagated + 1.0 / sensor)
        terminal_after = max(0.0, terminal - (propagated - posterior))
        repair_after = max(0.0, terminal_after - posterior**2 / (posterior + repair_noise))
        result["wait"] = WAIT_COST * multiplier + min(terminal_after, repair_after + REPAIR_COST * multiplier)
    return result


def _receipts(scope, audit):
    root, index = scope / "transport", {}
    expected_files = {"TRANSPORT_RECEIPTS.jsonl"}
    for row in _jsonl(root / "TRANSPORT_RECEIPTS.jsonl"):
        key = (row["case"], row["arm"], row["kind"], row["stage"])
        audit.require(key not in index, "receipt", f"Duplicate {key}")
        audit.require(row["private_target_supplied"] is False, "receipt", f"Private target flag {key}")
        audit.require(0 < row["began_ns"] <= row["written_ns"] <= row["readback_ns"], "chronology", str(key))
        if row["kind"] == "observation":
            expected_files.add(row["path"])
            path = _under(root, row["path"])
            audit.require(_sha(path) == row["sha256"], "artifact_hash", str(key))
            payload = _json(path)
            audit.require(payload["schema"] == "hepta.analytic-event.public-observation.v1", "receipt", str(key))
            value = payload["value"]
        else:
            audit.require(row["kind"] == "delivery", "receipt", str(key))
            text_path, png_path = _under(root, row["text_path"]), _under(root, row["image_path"])
            expected_files.update((row["text_path"], row["image_path"]))
            audit.require(_sha(text_path) == row["text_sha256"] and _sha(png_path) == row["image_sha256"], "artifact_hash", str(key))
            value = _png_value(png_path)
            audit.require(struct.pack(">d", float(text_path.read_text())) == struct.pack(">d", value)
                          == struct.pack(">d", row["prediction"]), "png_bit_replay", str(key))
        index[key] = (row, value)
    actual_files = {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}
    audit.require(actual_files == expected_files, "coverage", "Every transport file has an audited receipt")
    return index


def _prediction_audit(rows, models, data, replay, summary, audit):
    positions = {str(identity): i for i, identity in enumerate(data["ids"])}
    seen, groups = set(), defaultdict(list)
    for row in rows:
        name, case = row["arm"], row["case"]
        key, i = (name, case), positions[case]
        audit.require(key not in seen and name in models, "prediction", str(key))
        seen.add(key)
        target = data["future"][i, [1, 2, 4]]
        labels = np.where(target <= LOWER, 0, np.where(target > UPPER, 2, 1))
        means, variances = replay[(name, "initial")]
        audit.close(row["mean"], means[i, 1:], "model_replay", str(key) + " mean")
        audit.close(row["variance"], variances[i, 1:], "model_replay", str(key) + " variance")
        audit.close(row["targets"], target, "prediction", str(key) + " target", exact=True)
        audit.close(row["labels"], labels, "prediction", str(key) + " labels", exact=True)
        logp = event_log_probs(row["mean"], row["variance"], LOWER, UPPER)
        probability = np.exp(logp)
        nll = -logp[np.arange(3), labels]
        brier = np.sum((probability - np.eye(3)[labels])**2, axis=1)
        for field, expected in (("probabilities", probability), ("nll", nll), ("brier", brier)):
            audit.close(row[field], expected, "prediction_loss", str(key) + "/" + field)
        audit.require(row["law"] == data["law"], "prediction", str(key) + " law")
        groups[name].append([nll.mean(), brier.mean(), np.mean(probability.argmax(1) == labels),
                             np.mean((np.asarray(row["mean"]) - target)**2)])
    audit.require(len(seen) == len(models) * len(positions), "coverage", "All prediction rows")
    for name, values in groups.items():
        for field, expected in zip(("event_nll", "brier", "accuracy", "mse"), np.mean(values, axis=0)):
            audit.close(summary[name][field], expected, "summary", name + "/" + field)
        audit.require(summary[name]["trajectories"] == len(positions) and summary[name]["horizons"] == 3,
                      "summary", name + " sampling unit")


def _control_audit(rows, models, data, histories, replay, receipts, summary, audit):
    positions = {str(identity): i for i, identity in enumerate(data["ids"])}
    seen, used, groups = set(), set(), defaultdict(list)
    allowed = {( "stop",): ("initial", []), ("repair",): ("repair", ["repair"]),
               ("wait", "stop"): ("wait", ["wait"]),
               ("wait", "repair"): ("wait_repair", ["wait", "wait_repair"])}
    for row in rows:
        arm, case = row["arm"], row["case"]
        i, key = positions[case], (arm, case)
        audit.require(key not in seen, "control", f"Duplicate {key}")
        seen.add(key)
        name = "analytic" if arm in FIXED else arm
        model = _model(models[name], data)
        audit.require(row["model_sha256"] == hashlib.sha256(json.dumps(model, sort_keys=True).encode()).hexdigest(), "model_hash", str(key))
        audit.require(row["actual_transport"] is True and row["law"] == data["law"], "control", str(key))

        def receipt(kind, stage):
            identity = (case, arm, kind, stage)
            used.add(identity)
            return receipts[identity]

        initial_receipt, initial_value = receipt("observation", "initial")
        _public_equal(audit, initial_value, histories["initial"], i, str(key) + " initial file")
        _public_equal(audit, row["initial_public_history"], histories["initial"], i, str(key) + " initial")
        terms_receipt, multiplier = receipt("observation", "terms")
        audit.close(multiplier, data["cost_multiplier"][i], "cost", str(key) + " terms", exact=True)
        audit.close([row["public_terms"][field] for field in ("cost_multiplier", "base_wait_cost", "base_repair_cost")],
                    [multiplier, WAIT_COST, REPAIR_COST], "cost", str(key) + " public terms")
        preview_receipt, preview_value = receipt("delivery", "initial")
        final_receipt, delivered = receipt("delivery", "final")
        audit.close(row["initial_prediction"], preview_value, "delivery", str(key) + " preview", exact=True)
        audit.close(row["delivered_prediction"], delivered, "delivery", str(key) + " final", exact=True)
        timeline = [initial_receipt["readback_ns"], row["initial_observation_ns"], terms_receipt["began_ns"],
                    terms_receipt["readback_ns"], row["terms_readback_ns"], preview_receipt["began_ns"],
                    preview_receipt["readback_ns"], row["preview_readback_ns"], row["stages"][0]["decision_ns"]]
        audit.require(all(a <= b for a, b in zip(timeline, timeline[1:])), "chronology", str(key) + " initial")
        actions = tuple(row["actions"])
        audit.require(actions in allowed, "control", str(key) + " legal path")
        policy_mode = arm if arm in FIXED else "variance_voi"
        audit.require(row["policy_mode"] == policy_mode, "decision", str(key) + " policy mode")
        final_stage, acquired = allowed[actions]
        audit.require([r["stage"] for r in row["observations"]] == acquired, "control", str(key) + " acquired observations")
        audit.require(len(row["stages"]) == len(actions), "control", str(key) + " decision count")
        for j, decision in enumerate(row["stages"]):
            stage, horizon_index = ("initial", 3) if j == 0 else ("wait", 2)
            audit.require(decision["stage"] == stage and decision["horizon"] == (2.0 if j == 0 else 1.0), "control", str(key) + " horizon")
            _public_equal(audit, decision["public_history"], histories[stage], i, str(key) + "/" + stage)
            means, variances = replay[(name, stage)]
            scores = _scores(model, means[i], variances[i], horizon_index, multiplier)
            diagnostics = {"current_mean": means[i, 0], "terminal_mean": means[i, horizon_index],
                           "current_variance": variances[i, 0], "terminal_variance": variances[i, horizon_index],
                           "planning_q": model["planning_q"], "planning_noise_scale": model["planning_noise_scale"],
                           "cost_multiplier": multiplier}
            audit.require(decision["policy_mode"] == policy_mode, "decision", str(key) + " stage mode")
            for field, expected in diagnostics.items():
                audit.close(decision["diagnostics"][field], expected, "decision", str(key) + "/" + field)
            audit.require(set(scores) == set(decision["expected_squared_error_plus_cost"]), "decision", str(key) + " score keys")
            for action, expected in scores.items():
                audit.close(decision["expected_squared_error_plus_cost"][action], expected, "decision", str(key) + "/" + action)
            expected = min(scores, key=scores.get)
            if arm in FIXED:
                expected = ({"always_stop": "stop", "always_repair": "repair", "always_wait": "wait",
                             "always_wait_repair": "wait"}[arm] if j == 0 else "repair" if arm == "always_wait_repair" else "stop")
            audit.require(decision["selected"] == actions[j] == expected, "decision", str(key) + " chosen")
            audit.close(decision["predicted_mean"], means[i, horizon_index], "model_replay", str(key) + " decision mean")
        for observation in row["observations"]:
            name_observed = observation["stage"]
            observed_receipt, value = receipt("observation", name_observed)
            audit.close(value, data[name_observed + "_observation"][i], "feedback", str(key) + name_observed, exact=True)
            audit.close(observation["value"], value, "feedback", str(key) + " recorded observation", exact=True)
            decision_index = 1 if name_observed == "wait_repair" else 0
            decision_ns = row["stages"][decision_index]["decision_ns"]
            next_ns = row["stages"][1]["decision_ns"] if name_observed == "wait" else final_receipt["began_ns"]
            audit.require(decision_ns <= observed_receipt["began_ns"] <= observed_receipt["readback_ns"]
                          <= observation["readback_ns"] <= next_ns, "chronology", str(key) + name_observed)
        _public_equal(audit, row["final_public_history"], histories[final_stage], i, str(key) + " final history")
        expected_mean = replay[(name, final_stage)][0][i, 2 if actions[0] == "wait" else 3]
        audit.close(row["proposed_final_prediction"], expected_mean, "model_replay", str(key) + " final mean")
        audit.close(delivered, row["proposed_final_prediction"], "delivery", str(key) + " final bits", exact=True)
        audit.close(preview_value, replay[(name, "initial")][0][i, 3], "model_replay", str(key) + " preview mean")
        cost = multiplier * (WAIT_COST * ("wait" in actions) + REPAIR_COST * ("repair" in actions))
        charged = [a for a in actions if a != "stop"]
        audit.require([x["action"] for x in row["cost_items"]] == charged, "cost", str(key) + " ledger")
        for item in row["cost_items"]:
            base = WAIT_COST if item["action"] == "wait" else REPAIR_COST
            audit.close([item["base_cost"], item["multiplier"], item["paid_cost"]], [base, multiplier, base * multiplier], "cost", str(key) + " line")
        audit.close(row["paid_cost"], cost, "cost", str(key) + " total")
        target = data["future"][i, 4]
        square, utility = (delivered - target)**2, 1 - (delivered - target)**2 - cost
        for field, expected in (("terminal_target", target), ("squared_error", square), ("utility", utility)):
            audit.close(row[field], expected, "score", str(key) + "/" + field)
        audit.require(row["severe_loss"] == bool(utility < -2), "score", str(key) + " severe loss")
        audit.require(row["stages"][-1]["decision_ns"] <= final_receipt["began_ns"]
                      <= final_receipt["readback_ns"] <= row["final_readback_ns"] <= row["score_started_ns"], "chronology", str(key) + " target boundary")
        audit.require(final_receipt["action"] == "/".join(actions) and preview_receipt["action"] == "preview", "delivery", str(key) + " action")
        groups[arm].append(row)
    audit.require(len(seen) == (len(models) + len(FIXED)) * len(positions), "coverage", "All control rows")
    audit.require(used == set(receipts), "coverage", "All and only referenced transport receipts")
    for arm, values in groups.items():
        expected = {"mean_utility": np.mean([r["utility"] for r in values]),
                    "mean_squared_error": np.mean([r["squared_error"] for r in values]),
                    "mean_action_cost": np.mean([r["paid_cost"] for r in values]),
                    "severe_loss_fraction": np.mean([r["severe_loss"] for r in values]),
                    "wait_count": sum("wait" in r["actions"] for r in values),
                    "repair_count": sum("repair" in r["actions"] for r in values),
                    "wall_ns": sum(r["elapsed_ns"] for r in values), "cpu_ns": sum(r["cpu_ns"] for r in values)}
        for field, value in expected.items():
            audit.close(summary[arm][field], value, "summary", arm + "/" + field)


def audit_scope(scope_dir, native=None):
    """Audit one uncompressed scope; return fail-closed machine-readable evidence."""
    started, audit, scope = time.perf_counter_ns(), _Audit(), Path(scope_dir)
    result = {"schema": "hepta.analytic-event.scope-audit.v1", "scope": str(scope),
              "audit_source_sha256": _sha(__file__), "offline_replay": True,
              "chronology_scope": "Retained files, timestamps, and frozen source; not process-memory isolation proof"}
    try:
        data, models, summary = _load_data(scope, audit), _json(scope / "MODELS.json"), _json(scope / "SUMMARY.json")
        model_hash = _sha(scope / "MODELS.json")
        frozen_paths = [parent / "FREEZE.json" for parent in scope.parents if (parent / "FREEZE.json").is_file()]
        result["frozen_model_binding"] = bool(frozen_paths)
        if frozen_paths:
            frozen = _json(frozen_paths[0])
            audit.require(model_hash in frozen["artifacts_sha256"].values(), "model_hash", "Scope model bytes match preconfirmation freeze")
        result.update(dataset_seed=data["seed"], dataset_split=data["split"], law=data["law"], model_sha256=model_hash)
        histories, replay = _histories(data), {}
        for name, model in models.items():
            audit.require(model.get("feature") != "sparse" or native is not None, "model_replay", "Original native bridge required")
            for stage, h in histories.items():
                replay[(name, stage)] = learners.predict(_model(model, data), h, native)
        predictions, controls = _jsonl(scope / "PREDICTION.jsonl"), _jsonl(scope / "CONTROL.jsonl")
        receipts = _receipts(scope, audit)
        _prediction_audit(predictions, models, data, replay, summary["prediction"], audit)
        _control_audit(controls, models, data, histories, replay, receipts, summary["control"], audit)
        result.update(passed=True, trajectories=len(data["ids"]), models=len(models),
                      prediction_rows=len(predictions), control_rows=len(controls), transport_receipts=len(receipts),
                      evidence_sha256={name: _sha(scope / name) for name in ("MODELS.json", "DATA.npz", "DATASET.json",
                          "PREDICTION.jsonl", "CONTROL.jsonl", "SUMMARY.json", "transport/TRANSPORT_RECEIPTS.jsonl")})
    except (AssertionError, ValueError, KeyError, OSError, TypeError, IndexError) as error:
        result.update(passed=False, error=f"{type(error).__name__}: {error}")
    result.update(checks=dict(audit.counts), maximum_absolute_numeric_error=audit.maximum_absolute_error,
                  audit_elapsed_ns=time.perf_counter_ns() - started)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scope")
    parser.add_argument("--output")
    arguments = parser.parse_args()
    result = audit_scope(arguments.scope)
    payload = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if arguments.output:
        Path(arguments.output).write_text(payload)
    else:
        print(payload, end="")
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
