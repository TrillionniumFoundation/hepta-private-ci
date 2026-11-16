"""Separate arithmetic and provenance audit; does not open final labels."""

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np

from cell_field_action_io import deny_withheld_labels, load_inputs, project, split_arrays
from cell_field_closure_data import write
from cell_field_features import file_hash
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead, normalize_features


def verify_seal(root, name, *, exact=False):
    manifest = json.loads((root / name).read_bytes())
    if manifest["schema"] != "hepta.cell-closure-seal.v4":
        raise ValueError("unknown evidence seal")
    for path, identity in manifest["files"].items():
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise ValueError("seal path escapes evidence root")
        item = root / path
        if item.is_symlink() or not item.is_file() or item.stat().st_size != identity["bytes"] or file_hash(item) != identity["sha256"]:
            raise ValueError("sealed file differs: " + path)
    if exact and set(manifest["files"]) != {
            str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and p != root / name}:
        raise ValueError("unsealed extra file in completed run")
    return manifest


def verify_candidate_members(manifest, candidates, plan):
    required = {"source-freeze.json", "projection.npz", "new-projected-features.npz",
                "protocol.json", "inputs.json", "candidates.json"}
    for warm in candidates["warmups"]:
        required.update({warm["path"], warm["id"] + "-warm-receipts.json"})
    for anchor in candidates["anchors"]:
        names = {"checkpoint/state.npz", "checkpoint/manifest.json", "reference.npz",
                 "actions.npz", "forecast.json"}
        names.update(arm + "-forecast.npz" for arm in plan["arms"])
        required.update(anchor["id"] + "/" + name for name in names)
    if set(manifest["files"]) != required:
        raise ValueError("candidate seal omitted a required prediction/input or contains a post-execution file")


def verify_run(root):
    verify_seal(root, "run-seal.json", exact=True)
    candidate_manifest = verify_seal(root, "candidate-seal.json")
    plan = json.loads((root / "protocol.json").read_bytes())
    run = json.loads((root / "runs.json").read_bytes())
    candidates = json.loads((root / "candidates.json").read_bytes())
    verify_candidate_members(candidate_manifest, candidates, plan)
    frozen = json.loads((root / "source-freeze.json").read_bytes())
    identities = {(x["head"], x["seed"], x["anchor_offset"]) for x in run["anchors"]}
    expected = {(head, seed, offset) for head in plan["head_modes"] for seed in plan["seeds"]
                for offset in plan["anchor_offsets"]}
    if (len(run["records"]) != 306 or len(run["anchors"]) != 18 or identities != expected
            or len({x["id"] for x in run["anchors"]}) != 18
            or run["registered"] != 306 or run["completed"] != 306
            or any(x["status"] != "completed" for x in run["records"])
            or candidates["anchors"] != run["anchors"] or candidates["warmups"] != run["warmups"]
            or candidates["registered_branches"] != 306 or run["final_labels_opened"] is not False
            or run["candidate_seal_sha256"] != file_hash(root / "candidate-seal.json")
            or run["source_commit"] != frozen["git_commit"]):
        raise ValueError("complete registered run or pre-execution candidate binding differs")
    if {(x["anchor"], x["action"]) for x in run["records"]} != {
            (a["id"], i) for a in run["anchors"] for i in range(17)}:
        raise ValueError("duplicate or missing registered branch")
    if {(x["head"], x["seed"]) for x in run["warmups"]} != {
            (head, seed) for head in plan["head_modes"] for seed in plan["seeds"]} or len(run["warmups"]) != 6:
        raise ValueError("warmup census differs")
    return plan, run


def predictions_from_state(vector, mode, features):
    head, offset = NumpyCellHead(8, 4, mode), 0
    for name in sorted(head.params):
        template = head.params[name]
        head.params[name] = vector[offset:offset + template.size].reshape(template.shape).copy()
        offset += template.size
    return head.predict_proba(features)


def direct_cost(fields, action, reference, old_anchor, plan):
    weights = np.r_[np.full(plan["horizon"], plan["h"]), 1.0]
    excess = np.maximum(reference[:, 1] + fields[:, 1] - old_anchor, 0.0)
    return float(plan["direct_coefficient"] * np.dot(weights, fields[:, 0])
                 + 0.5 * np.dot(weights, excess * excess)
                 + 0.5 * plan["h"] * plan["effort_price"] * np.dot(action, action))


def replay_branch(initial, train, probes, states, observations, receipts, action, dt):
    replay = initial.clone()
    normalized = [(normalize_features(x), y) for x, y in probes]
    if len(receipts) != 8:
        raise ValueError("registered branch receipt count differs")
    for k in range(9):
        np.testing.assert_array_equal(replay.vector(), states[k])
        calculated = [replay.head.loss_gradients(x, y, 0.0)[0] for x, y in normalized]
        np.testing.assert_allclose(calculated, observations[k], atol=1e-14, rtol=1e-13)
        if k < 8:
            receipt = replay.advance(*train, intervention=dt * action if k == 0 else np.zeros(len(action)))
            if receipt != receipts[k]:
                raise ValueError("replayed Adam context, step, action, sampler or state receipt differs")
    return 8


def concordance(predicted, actual, tolerance):
    c = d = predicted_ties = actual_ties = both = 0
    for i in range(len(actual)):
        for j in range(i):
            dx, dy = float(predicted[i] - predicted[j]), float(actual[i] - actual[j])
            sx = 0 if abs(dx) <= tolerance else int(np.sign(dx))
            sy = 0 if abs(dy) <= tolerance else int(np.sign(dy))
            if sx == 0 and sy == 0:
                both += 1
            elif sx == 0:
                predicted_ties += 1
            elif sy == 0:
                actual_ties += 1
            elif sx == sy:
                c += 1
            else:
                d += 1
    denominator = np.sqrt((c + d + predicted_ties) * (c + d + actual_ties))
    return {"concordant": c, "discordant": d, "predicted_only_ties": predicted_ties,
            "actual_only_ties": actual_ties, "both_ties": both,
            "tau_b": float((c - d) / denominator) if denominator else None}


def audit(runs, v3_data, v3_features, v3_protocol, output):
    sys.addaudithook(deny_withheld_labels)
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    root = Path(runs)
    plan, run = verify_run(root)
    original = load_inputs(v3_data, v3_features, v3_protocol)
    inputs = json.loads((root / "inputs.json").read_bytes())
    if original["input_hashes"] != inputs["v3_input_hashes"]:
        raise ValueError("replay training inputs differ from the pre-execution commitment")
    projected, q = project(original["features"], original["plan"])
    split = split_arrays(projected, original["labels"])
    with np.load(root / "projection.npz", allow_pickle=False) as z:
        np.testing.assert_array_equal(q, z["q"])
    contexts = {name: dataset_digest(*split[name]) for name in ("old_train", "current_train")}
    frozen = json.loads((root / "source-freeze.json").read_bytes())
    with np.load(root / "new-projected-features.npz", allow_pickle=False) as z:
        new_features = z["features"]
    if new_features.shape != (96, 8) or not np.isfinite(new_features).all():
        raise ValueError("new projected source features differ")
    records = {(x["anchor"], x["action"]): x for x in run["records"]}
    if len(records) != 306:
        raise ValueError("duplicate branch")
    ranking, max_error, max_forecast_error, comparisons, replayed_steps = [], 0.0, 0.0, 0, 0
    rebuilt, warm_old_losses, anchor_training_steps = {}, {}, 0
    for warm in run["warmups"]:
        bindings = {"protocol_sha256": frozen["protocol_sha256"], "seed": warm["seed"], "mode": warm["head"],
                    "source_commit": run["source_commit"], "v3_features_sha256": plan["v3_features_sha256"]}
        state = CellTrainingState(NumpyCellHead(8, 4, warm["head"], seed=warm["seed"]),
            bindings=bindings, protocol=plan["optimizer"], seed=warm["seed"],
            contexts=contexts, active_context="old_train")
        receipts = json.loads((root / (warm["id"] + "-warm-receipts.json")).read_bytes())
        if len(receipts) != plan["warmup_steps"]:
            raise ValueError("registered warmup receipt count differs")
        for receipt in receipts:
            if state.advance(*split["old_train"]) != receipt:
                raise ValueError("reconstructed warmup differs from its receipt")
            anchor_training_steps += 1
        state.select_context("current_train")
        with np.load(root / warm["path"], allow_pickle=False) as z:
            np.testing.assert_array_equal(z["state"], state.vector())
            np.testing.assert_allclose(z["predictions"], predictions_from_state(z["state"], warm["head"], new_features),
                                       atol=1e-14, rtol=1e-13)
        warm_old_losses[warm["id"]] = state.head.loss_gradients(
            normalize_features(split["old_probe"][0]), split["old_probe"][1], 0.0)[0]
        offset = 0
        for target in plan["anchor_offsets"]:
            while offset < target:
                state.advance(*split["current_train"])
                offset += 1
                anchor_training_steps += 1
            rebuilt[f"{warm['id']}-step{target}"] = state.digest()
    for anchor in run["anchors"]:
        directory = root / anchor["id"]
        bindings = {"protocol_sha256": frozen["protocol_sha256"], "seed": anchor["seed"], "mode": anchor["head"],
                    "source_commit": run["source_commit"], "v3_features_sha256": plan["v3_features_sha256"]}
        initial = CellTrainingState.load(directory / "checkpoint", bindings, plan["optimizer"], contexts)
        if initial.active_context != "current_train" or initial.step_count != 64 + anchor["anchor_offset"]:
            raise ValueError("checkpoint is outside the registered current trajectory")
        warm_id = f"seed{anchor['seed']}-{anchor['head']}"
        if initial.digest() != rebuilt[anchor["id"]] or anchor["old_anchor"] != warm_old_losses[warm_id]:
            raise ValueError("anchor differs from the reconstructed common fitted trajectory")
        with np.load(directory / "reference.npz", allow_pickle=False) as z:
            reference = {k: z[k] for k in z.files}
        with np.load(directory / "actions.npz", allow_pickle=False) as z:
            actions = z["actions"]
        p = anchor["parameter_count"]
        if (actions.shape != (17, p) or np.max(np.abs(actions)) > 1 / np.sqrt(p)
                or not np.allclose(np.linalg.norm(actions[1:], axis=1), 0.1, atol=1e-14, rtol=0)):
            raise ValueError("action census or effort mismatch")
        actual_costs, actual_fields = [], []
        for i, action in enumerate(actions):
            row = records[(anchor["id"], i)]
            with np.load(root / row["path"], allow_pickle=False) as z:
                states, observed, fields, predictions = (z[k] for k in ("states", "observations", "fields", "predictions"))
            receipts = json.loads((directory / f"action-{i:02d}-receipts.json").read_bytes())
            replayed_steps += replay_branch(initial, split["current_train"],
                (split["current_probe"], split["old_probe"]), states, observed, receipts, action, plan["h"])
            if (states.shape != (9, 3 * p) or np.any(states[:, 2 * p:] < 0)
                    or not all(np.isfinite(x).all() for x in (states, observed, fields, predictions))
                    or not np.array_equal(states[0], reference["reference_states"][0])
                    or not np.allclose(predictions.sum(axis=1), 1.0, atol=1e-13, rtol=0)):
                raise ValueError("invalid real state or predictions")
            first = reference["reference_states"][1].copy()
            first[:p] += plan["h"] * action
            if not np.array_equal(first, states[1]):
                raise ValueError("first real impulse differs from registered action")
            if i == 0:
                np.testing.assert_array_equal(states, reference["reference_states"])
                np.testing.assert_allclose(observed, reference["reference_observations"][:, :2], atol=1e-14, rtol=1e-13)
            np.testing.assert_array_equal(fields, observed - reference["reference_observations"][:, :2])
            np.testing.assert_allclose(predictions, predictions_from_state(states[-1], anchor["head"], new_features),
                                       atol=1e-14, rtol=1e-13)
            cost = direct_cost(fields, action, reference["reference_observations"], anchor["old_anchor"], plan)
            error = abs(cost - row["actual"]["direct_soft_total"])
            max_error = max(max_error, error)
            if error > 1e-13:
                raise ValueError("actual common cost arithmetic mismatch")
            actual_costs.append(cost)
            actual_fields.append(fields)
            comparisons += 1
        actual_costs, actual_fields = np.asarray(actual_costs), np.asarray(actual_fields)
        forecast = json.loads((directory / "forecast.json").read_bytes())
        full = np.zeros((9, 3 * p, p))
        full[1, :p] = plan["h"] * np.eye(p) / reference["state_scales"][:p, None]
        for k in range(1, 8):
            full[k + 1] = reference["A"][k] @ full[k]
        full_losses = np.einsum("kij,kjl->kil", reference["C_extended"][:, :2], full)
        for arm in plan["arms"]:
            with np.load(directory / (arm + "-forecast.npz"), allow_pickle=False) as z:
                maps, fields = z["maps"], z["fields"]
            np.testing.assert_allclose(fields, np.einsum("kij,aj->aki", maps, actions), atol=1e-14, rtol=1e-12)
            if arm == "full":
                np.testing.assert_allclose(maps, full_losses, atol=1e-13, rtol=1e-11)
            costs = np.asarray([x["direct_soft_total"] for x in forecast["arms"][arm]["scores"]])
            recomputed = np.array([direct_cost(response, action, reference["reference_observations"],
                                   anchor["old_anchor"], plan) for response, action in zip(fields, actions)])
            forecast_error = float(np.max(np.abs(costs - recomputed)))
            max_forecast_error = max(max_forecast_error, forecast_error)
            if forecast_error > 1e-13:
                raise ValueError("forecast common cost arithmetic mismatch")
            chosen = int(np.argmin(costs))
            if chosen != forecast["selected"][arm] or chosen != anchor["selected"][arm]:
                raise ValueError("frozen action selection differs")
            ranking.append({"anchor": anchor["id"], "arm": arm,
                "equal_radius_ranking": concordance(costs[1:], actual_costs[1:], plan["ranking_tie_tolerance"]),
                "same_action_cost_mae": float(np.abs(costs[1:] - actual_costs[1:]).mean()),
                "per_step_loss_mae": np.abs(fields[1:] - actual_fields[1:]).mean(axis=0).tolist(),
                "chosen_action": chosen, "actual_regret": float(actual_costs[chosen] - actual_costs.min())})
            comparisons += 1
    result = {"schema": "hepta.cell-closure-audit.v4", "status": "passed", "run_seal_sha256": file_hash(root / "run-seal.json"),
              "registered_branches": 306, "replayed_optimizer_steps": replayed_steps,
              "replayed_anchor_training_steps": anchor_training_steps,
              "ranking_rows": ranking, "arithmetic_comparisons": comparisons,
              "max_actual_cost_error": max_error, "max_forecast_cost_error": max_forecast_error, "final_labels_opened": False,
              "scope": "separate cost arithmetic plus checkpoint replay of every declared Adam step, receipt and probe observation; same existing optimizer implementation; not independent third-party attestation",
              "wall_ns": time.perf_counter_ns() - began, "cpu_ns": time.process_time_ns() - cpu,
              "authority": "DENY_ALL", "production_authority": False}
    write(Path(output), result)
    return {k: result[k] for k in ("registered_branches", "replayed_optimizer_steps", "arithmetic_comparisons", "max_actual_cost_error", "final_labels_opened")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("runs", "v3-data", "v3-features", "v3-protocol", "output"):
        parser.add_argument("--" + name, required=True)
    print(json.dumps(audit(**vars(parser.parse_args())), sort_keys=True))
