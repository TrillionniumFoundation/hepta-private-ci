"""Reopen all main-study files and replay each frozen model and event decoder.

Numerical kernel validation is separate. This audit independently reconstructs
costs, score boundaries, receipt coverage and interval certificates; it also
reuses frozen inference for full replay, including the original sparse binary.
"""

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import struct
import time

import numpy as np

from ..analytic import event_log_probs
from ..round2 import audit as prior
from ..round2 import predictors
from . import event_codec as codec


def receipts(scope, controls, audit):
    root, index = scope / "transport", {}
    expected = {"TRANSPORT_RECEIPTS.jsonl"}
    for row in prior._jsonl(root / "TRANSPORT_RECEIPTS.jsonl"):
        key = (row["case"], row["arm"], row["kind"], row["stage"])
        audit.require(key not in index and row["private_target_supplied"] is False,
                      "receipt", str(key))
        audit.require(0 < row["began_ns"] <= row["written_ns"] <= row["readback_ns"],
                      "chronology", str(key))
        if row["kind"] == "observation":
            expected.add(row["path"])
            path = prior._under(root, row["path"])
            audit.require(prior._sha(path) == row["sha256"], "artifact_hash", str(key))
            payload = prior._json(path)
            audit.require(payload["schema"] == "hepta.analytic-event.public-observation.v1",
                          "receipt", str(key))
            value = payload["value"]
        else:
            audit.require(row["kind"] == "delivery", "receipt", str(key))
            expected.update((row["text_path"], row["image_path"]))
            text, png = prior._under(root, row["text_path"]), prior._under(root, row["image_path"])
            audit.require(prior._sha(text) == row["text_sha256"]
                          and prior._sha(png) == row["image_sha256"], "artifact_hash", str(key))
            value = prior._png_value(png)
            audit.require(struct.pack(">d", float(text.read_text())) == struct.pack(">d", value)
                          == struct.pack(">d", row["prediction"]), "png_bit_replay", str(key))
        index[key] = row, value
    for row in controls:
        packet = row.get("packet_transport")
        if packet is None:
            continue
        audit.require(packet["path"] not in expected, "packet_coverage", row["case"])
        expected.add(packet["path"])
        payload = prior._under(root, packet["path"]).read_bytes()
        audit.require(hashlib.sha256(payload).hexdigest() == packet["sha256"]
                      and len(payload) == packet["bytes"], "packet_hash", row["case"])
        offset = 0
        for operation in packet["operations"]:
            chunk = payload[offset:offset + operation["bytes"]]
            audit.require(operation["offset"] == offset
                          and hashlib.sha256(chunk).hexdigest() == operation["sha256"],
                          "packet_readback", row["case"])
            audit.require(operation["began_ns"] <= operation["written_ns"] <= operation["readback_ns"],
                          "packet_chronology", row["case"])
            offset += operation["bytes"]
        audit.require(offset == len(payload), "packet_coverage", row["case"])
        parsed = [json.loads(line) for line in payload.splitlines()]
        audit.require(parsed == row["event_packets"], "packet_readback", row["case"])
    actual = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
    audit.require(actual == expected, "coverage", "Every observation, delivery and event file is referenced")
    return index


def prediction_audit(rows, models, data, replay, summary, audit):
    positions = {str(case): i for i, case in enumerate(data["ids"])}
    seen, groups = set(), defaultdict(list)
    for row in rows:
        name, identity = row["arm"], row["case"]
        key = name, identity
        audit.require(key not in seen and name in models, "prediction", str(key))
        seen.add(key)
        i = positions[identity]
        target = data["future"][i, [1, 2, 4]]
        labels = np.where(target <= -.6, 0, np.where(target > .6, 2, 1))
        mean, variance = replay[(name, "initial")]
        audit.close(row["mean"], mean[i, 1:], "model_replay", str(key))
        audit.close(row["variance"], variance[i, 1:], "model_replay", str(key))
        audit.close(row["targets"], target, "prediction", str(key), exact=True)
        audit.close(row["labels"], labels, "prediction", str(key), exact=True)
        logp = event_log_probs(row["mean"], row["variance"], -.6, .6)
        p = np.exp(logp)
        loss = -logp[np.arange(3), labels]
        brier = np.sum((p - np.eye(3)[labels]) ** 2, axis=1)
        for field, value in (("probabilities", p), ("nll", loss), ("brier", brier)):
            audit.close(row[field], value, "prediction_loss", str(key))
        groups[name].append([loss.mean(), brier.mean(), np.mean((row["mean"] - target) ** 2)])
    audit.require(len(seen) == len(models) * len(positions), "coverage", "All prediction rows")
    for name, values in groups.items():
        for field, value in zip(("event_nll", "brier", "mse"), np.mean(values, axis=0)):
            audit.close(summary[name][field], value, "summary", name + "/" + field)


def event_control_audit(rows, models, data, histories, replay, all_receipts, summary, audit):
    positions = {str(case): i for i, case in enumerate(data["ids"])}
    seen, used, groups = set(), set(), defaultdict(list)
    allowed = {("stop",): ("initial", []), ("repair",): ("repair", ["repair"]),
               ("wait", "stop"): ("wait", ["wait"]),
               ("wait", "repair"): ("wait_repair", ["wait", "wait_repair"])}
    for row in rows:
        arm, case = row["arm"], row["case"]
        i, model, key = positions[case], models[arm], (arm, case)
        audit.require(key not in seen, "control", str(key))
        seen.add(key)
        audit.require(row["actual_transport"] and row["model_sha256"] == codec.digest(model),
                      "model_hash", str(key))

        def receipt(kind, stage):
            identity = case, arm, kind, stage
            used.add(identity)
            return all_receipts[identity]

        initial, public = receipt("observation", "initial")
        terms, multiplier = receipt("observation", "terms")
        preview, preview_value = receipt("delivery", "initial")
        final, delivered = receipt("delivery", "final")
        for supplied in (public, row["initial_public_history"]):
            prior._public_equal(audit, supplied, histories["initial"], i, str(key))
        audit.close(multiplier, data["cost_multiplier"][i], "cost", str(key), exact=True)
        audit.close([row["public_terms"][field] for field in
                     ("cost_multiplier", "base_wait_cost", "base_repair_cost")],
                    [multiplier, .07, .12], "cost", str(key))
        chronology = [initial["readback_ns"], row["initial_observation_ns"], terms["began_ns"],
                      terms["readback_ns"], row["terms_readback_ns"], preview["began_ns"],
                      preview["readback_ns"], row["preview_readback_ns"], row["stages"][0]["decision_ns"]]
        audit.require(all(a <= b for a, b in zip(chronology, chronology[1:])), "chronology", str(key))
        session = codec.Session(model)
        subset = lambda stage: {k: v[i:i + 1] for k, v in histories[stage].items()}
        session.sync(subset("initial"))
        audit.close([preview_value, row["initial_prediction"]], [session.forecast(2.0)[0]] * 2,
                    "model_replay", str(key))
        actions = tuple(row["actions"])
        audit.require(actions in allowed, "legal_actions", str(key))
        final_stage, acquired = allowed[actions]
        audit.require(len(row["stages"]) == len(actions)
                      and [x["stage"] for x in row["observations"]] == acquired,
                      "control", str(key))
        for number, decision in enumerate(row["stages"]):
            stage, horizon = ("initial", 2.0) if number == 0 else ("wait", 1.0)
            if stage == "wait":
                session.sync(subset(stage))
            prior._public_equal(audit, decision["public_history"], histories[stage], i, str(key))
            expected = session.decide(horizon, multiplier)
            audit.require(decision["event_certificate"] == expected, "certificate_replay", str(key))
            audit.require(decision["stage"] == stage and decision["horizon"] == horizon
                          and decision["selected"] == actions[number] == expected["selected"],
                          "decision", str(key))
            for action, score in expected["scores"].items():
                audit.close(decision["expected_squared_error_plus_cost"][action], score,
                            "decision_scores", str(key))
            audit.close(decision["predicted_mean"], session.forecast(horizon)[0], "model_replay", str(key))
            if expected["cell_contains_driver_claimed"]:
                driver_variance = replay[("analytic", stage)][1][i, 0]
                low, high = expected["variance_interval"]
                audit.require(low <= driver_variance <= high, "driver_in_cell", str(key))
                if expected["certified"]:
                    m, v = replay[("analytic", stage)]
                    scores = prior._scores(model, m[i], v[i], 3 if horizon == 2 else 2, multiplier)
                    audit.require(min(scores, key=scores.get) == expected["selected"],
                                  "certified_continuous_action", str(key))
                    selected_high = expected["score_intervals"][expected["selected"]][1]
                    audit.require(all(bounds[0] > selected_high + expected["numeric_allowance"]
                                      for name, bounds in expected["score_intervals"].items()
                                      if name != expected["selected"]), "interval_separation", str(key))
        if final_stage in ("repair", "wait_repair"):
            session.sync(subset(final_stage))
        expected_final = session.forecast(1.0 if actions[0] == "wait" else 2.0)[0]
        audit.close([delivered, row["delivered_prediction"], row["proposed_final_prediction"]],
                    [expected_final] * 3, "final_replay", str(key))
        audit.require(session.encoder.packets == row["event_packets"], "packet_full_replay", str(key))
        audit.require(session.accounting() == row["event_accounting"], "event_cost_replay", str(key))
        packet_operations = row["packet_transport"]["operations"]
        audit.require(len(packet_operations) == len(row["event_packets"]), "packet_coverage", str(key))
        audit.require(packet_operations[-1]["readback_ns"] <= final["began_ns"],
                      "packet_chronology", str(key))
        prior._public_equal(audit, row["final_public_history"], histories[final_stage], i, str(key))
        for observation in row["observations"]:
            observed, value = receipt("observation", observation["stage"])
            audit.close(value, data[observation["stage"] + "_observation"][i], "feedback", str(key), exact=True)
            audit.close(observation["value"], value, "feedback", str(key), exact=True)
            decision_index = int(observation["stage"] == "wait_repair")
            next_time = row["stages"][1]["decision_ns"] if observation["stage"] == "wait" else final["began_ns"]
            audit.require(row["stages"][decision_index]["decision_ns"] <= observed["began_ns"]
                          <= observed["readback_ns"] <= observation["readback_ns"] <= next_time,
                          "chronology", str(key))
        charged = [action for action in actions if action != "stop"]
        audit.require([x["action"] for x in row["cost_items"]] == charged, "cost", str(key))
        for item in row["cost_items"]:
            base = .07 if item["action"] == "wait" else .12
            audit.close([item["base_cost"], item["multiplier"], item["paid_cost"]],
                        [base, multiplier, base * multiplier], "cost", str(key))
        cost = multiplier * (.07 * ("wait" in actions) + .12 * ("repair" in actions))
        target = data["future"][i, 4]
        square, utility = (delivered - target) ** 2, 1 - (delivered - target) ** 2 - cost
        for field, value in (("paid_cost", cost), ("terminal_target", target),
                             ("squared_error", square), ("utility", utility)):
            audit.close(row[field], value, "score", str(key))
        audit.require(row["severe_loss"] == bool(utility < -2), "score", str(key))
        audit.require(row["stages"][-1]["decision_ns"] <= final["began_ns"] <= final["readback_ns"]
                      <= row["final_readback_ns"] <= row["score_started_ns"], "target_boundary", str(key))
        audit.require(final["action"] == "/".join(actions) and preview["action"] == "preview",
                      "delivery", str(key))
        groups[arm].append(row)
    audit.require(len(seen) == len(models) * len(positions), "coverage", "All new event episodes")
    audit.require(used == set(all_receipts), "coverage", "All new event transport receipts")
    for arm, selected in groups.items():
        for field, source in (("mean_utility", "utility"), ("mean_squared_error", "squared_error"),
                              ("mean_action_cost", "paid_cost")):
            audit.close(summary[arm][field], np.mean([r[source] for r in selected]), "summary", arm)


def audit_scope(scope_dir, native=None):
    began, audit, scope = time.perf_counter_ns(), prior._Audit(), Path(scope_dir)
    result = {"schema": "hepta.analytic-event.round3.scope-audit.v1", "audit_source_sha256": prior._sha(__file__),
              "full_frozen_inference_replay": True, "independent_scores_costs_and_all_pngs": True,
              "process_memory_isolation_proof": False}
    try:
        data, models = prior._load_data(scope, audit), prior._json(scope / "MODELS.json")
        summary = prior._json(scope / "SUMMARY.json")
        found_freeze = False
        for parent in scope.parents:
            if (parent / "FREEZE.json").exists():
                found_freeze = True
                frozen = prior._json(parent / "FREEZE.json")
                audit.require(prior._sha(scope / "MODELS.json") in frozen["artifacts_sha256"].values(),
                              "freeze", "Scope model matches published freeze")
                break
        result["frozen_model_binding"] = found_freeze
        audit.require(data["split"] != "confirmation" or found_freeze,
                      "freeze", "Confirmation audit requires ancestor freeze binding")
        histories, replay = prior._histories(data), {}
        new = {name: model for name, model in models.items() if model.get("kind") == codec.KIND}
        old = {name: model for name, model in models.items() if name not in new}
        for name, raw in models.items():
            model = prior._model(raw, data)
            for stage, history in histories.items():
                if name not in new or stage == "initial":
                    replay[(name, stage)] = codec.predict(model, history, native)
        predictions, controls = prior._jsonl(scope / "PREDICTION.jsonl"), prior._jsonl(scope / "CONTROL.jsonl")
        retained = receipts(scope, controls, audit)
        prediction_audit(predictions, models, data, replay, summary["prediction"], audit)
        prior._control_audit([row for row in controls if row["arm"] not in new], old, data, histories, replay,
                            {k: v for k, v in retained.items() if k[1] not in new}, summary["control"], audit)
        event_control_audit([row for row in controls if row["arm"] in new], new, data, histories, replay,
                            {k: v for k, v in retained.items() if k[1] in new}, summary["control"], audit)
        result.update(passed=True, unique_trajectories=len(data["ids"]), models=len(models),
                      prediction_rows=len(predictions), control_rows=len(controls), transport_receipts=len(retained))
    except (AssertionError, ValueError, KeyError, OSError, TypeError, IndexError) as error:
        result.update(passed=False, error=f"{type(error).__name__}: {error}")
    result.update(checks=dict(audit.counts), maximum_absolute_numeric_error=audit.maximum_absolute_error,
                  wall_ns=time.perf_counter_ns() - began)
    return result
