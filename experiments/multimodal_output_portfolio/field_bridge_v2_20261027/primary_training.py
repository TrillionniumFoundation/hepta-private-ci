"""Qualified H7 closed-loop training; no primary or retention output access."""

import argparse
import json
import os
from pathlib import Path
import time

import numpy as np

from ..field_bridge_20261027.adapters import frozen_base_hash, local_hash
from ..field_bridge_20261027.run import digest, object_hash, write_json
from .field_bank import B, margin_features
from .field_predictor import predict
from .learning import P as PILOT, gradient_corpus, hard_outputs, make_model, new_optimizer
from .learning import observe_field, optimizer_hash, panel, save_model, train_steps
from .primary_common import P, load_checkpoint, qualified_H7, setup_primary, source_freeze


def schedule(seed, start, count):
    return [{"batch_seed": seed * 100003 + 600000 + P["schedule_id"] * 1009 + step,
             "noise_seed": 107 + step, "condition": P["training_conditions"][step % 4]}
            for step in range(start, start + count)]


def path_resources(blocks, response, clean, action, advanced_steps):
    """Network invocations, not FLOPs; reused paths are explicitly labelled by caller."""
    n = sum(len(batch.source_ids) for _, batch in response)
    c = sum(len(batch.source_ids) for _, batch in clean)
    gradients = blocks * P["macro_steps"]
    return {"gradient_forward_calls": gradients, "backward_calls": gradients,
            "gradient_examples": gradients * P["batch_size"],
            "optimizer_steps": advanced_steps, "frozen_teacher_forward_calls": gradients,
            "frozen_teacher_examples": gradients * P["batch_size"],
            "teacher_forced_field_probe_calls": blocks * (len(response) + len(clean)),
            "teacher_forced_field_probe_examples": blocks * (n + c),
            "current_hard_value_forward_calls": blocks * len(response),
            "current_hard_value_examples": blocks * n,
            "rich_margin_forward_calls": blocks * len(response), "rich_margin_examples": blocks * n,
            "hard_value_and_margin_observer_digit_calls": blocks * 4 * len(response),
            "hard_value_and_margin_observer_digit_examples": blocks * 4 * n,
            "fixed_refinements_per_forward_example": 1 + (action != 0),
            "audit_observer_calls": 0, "test_retention_forward_calls": 0}


def constant_path(bank, trajectory, seed, recipe, initial_state, initial_optimizer):
    rows = sorted((row for row in bank["records"] if row["trajectory"] == trajectory),
                  key=lambda row: row["step"])
    if [row["step"] for row in rows] != list(range(0, recipe["steps"], P["macro_steps"])):
        raise ValueError("Ordinary candidate is not a complete registered path")
    previous_state, previous_optimizer, previous_output = initial_state, initial_optimizer, None
    previous_value = None
    for row in rows:
        if (row["seed"] != seed or row["partition"] != "fit" or row["trajectory_action"] != trajectory
                or row["schedule_sha256"] != object_hash(schedule(seed, row["step"], P["macro_steps"]))
                or row["state_sha256"] != previous_state or row["optimizer_sha256"] != previous_optimizer):
            raise ValueError("Ordinary candidate action/schedule/complete-state continuity differs")
        if previous_output is not None and (row["before_output_sha256"] != previous_output
                                            or row["current_value"] != previous_value):
            raise ValueError("Ordinary candidate hard-output continuation differs")
        if [branch["action"] for branch in row["branches"]] != list(range(4)):
            raise ValueError("Ordinary path lacks a complete four-action source bank")
        selected = row["branches"][trajectory]
        previous_state, previous_optimizer = selected["model_sha256"], selected["optimizer_sha256"]
        previous_output, previous_value = selected["output_sha256"], row["action_values"][trajectory]
    return rows


def checkpoint_receipt(path, out, model, optimizer, recipe, metadata, original, seed):
    save_model(path, model, optimizer, recipe, metadata)
    restored, restored_optimizer, record = load_checkpoint(path, original, seed, recipe)
    if (local_hash(restored) != local_hash(model)
            or optimizer_hash(restored_optimizer) != optimizer_hash(optimizer)
            or frozen_base_hash(restored) != frozen_base_hash(model)):
        raise RuntimeError("Saved primary checkpoint changed complete training state")
    return {"checkpoint": str(path.relative_to(out)), "checkpoint_sha256": digest(path),
            "local_sha256": record["local_sha256"], "optimizer_sha256": record["optimizer_sha256"],
            "base_sha256": frozen_base_hash(model)}


def ordinary_selection(args, corpus, observer, original, identity, recipe, action, sources, out, directory):
    seed, parent = args.seed, Path(args.parent_bank)
    bank_path = parent / f"fit-{seed}" / "BANK.json"
    bank = json.loads(bank_path.read_text())
    if (bank["recipe"] != recipe or bank["seed"] != seed or bank["phase"] != "fit"
            or bank["fixed_action"] != action):
        raise ValueError("Ordinary parent bank treatment differs")
    initial = make_model(original, seed, recipe)
    initial_optimizer = new_optimizer(initial, recipe)
    initial_state, initial_opt = local_hash(initial), optimizer_hash(initial_optimizer)
    batches = panel(corpus, P["ordinary_selection_panel"], seed)
    response, clean = panel(corpus, P["response_panel"], seed), panel(corpus, P["clean_probe"], seed)
    baseline = hard_outputs(original, batches, observer, action)
    candidates, values, endpoint_models = [], [baseline["values"]], []
    for index, multiplier in enumerate(P["multipliers"]):
        rows = constant_path(bank, index, seed, recipe, initial_state, initial_opt)
        path = parent / f"fit-{seed}" / f"trajectory-{index}-terminal.pt"
        model, optimizer, record = load_checkpoint(path, original, seed, recipe)
        expected = {"seed": seed, "trajectory": index, "phase": "fit",
                    "source_identity": identity, "fixed_action": action}
        if record["metadata"] != expected:
            raise ValueError("Reused ordinary checkpoint source metadata differs")
        terminal = rows[-1]["branches"][index]
        if (record["local_sha256"] != terminal["model_sha256"]
                or record["optimizer_sha256"] != terminal["optimizer_sha256"]
                or frozen_base_hash(model) != frozen_base_hash(initial)):
            raise ValueError("Reused ordinary endpoint differs from the committed parent path")
        scored = hard_outputs(model, batches, observer, action)
        if index == 0 and scored != baseline:
            raise RuntimeError("Zero-action ordinary candidate must exactly reproduce the fixed original")
        change = scored["by_condition"]["clean"] - baseline["by_condition"]["clean"]
        candidates.append({"action_index": index, "multiplier": multiplier,
            "value": scored["value"], "by_condition": scored["by_condition"],
            "gain_vs_original": scored["value"] - baseline["value"], "clean_change": change,
            "eligible": bool(change >= -P["ordinary_clean_margin"]),
            "source_checkpoint": str(path.relative_to(parent)), "source_checkpoint_sha256": digest(path),
            "local_sha256": record["local_sha256"], "optimizer_sha256": record["optimizer_sha256"],
            "selection_output_sha256": object_hash(scored["output_sha256"]),
            "parent_path_sha256": object_hash(rows)})
        values.append(scored["values"])
        endpoint_models.append((model, optimizer, rows))
    eligible = [row for row in candidates if row["eligible"]]
    selected = max(eligible, key=lambda row: (row["value"], -row["action_index"]))
    model, optimizer, rows = endpoint_models[selected["action_index"]]
    np.savez_compressed(directory / "ordinary-selection-values.npz", values=np.asarray(values))
    selection = {"schema": "hepta.field-bridge.v2.ordinary-selection.1", "seed": seed,
        "panel": P["ordinary_selection_panel"], "fixed_action": action,
        "baseline": {"value": baseline["value"], "by_condition": baseline["by_condition"],
                     "output_sha256": object_hash(baseline["output_sha256"])},
        "candidates": candidates, "selected": selected,
        "selection_rule": P["ordinary_selection"], "parent_bank_sha256": digest(bank_path),
        "values_file_sha256": digest(directory / "ordinary-selection-values.npz"),
        "new_resources": {"hard_value_forward_calls": 5 * len(batches),
                          "hard_value_examples": 5 * sum(len(b.source_ids) for _, b in batches),
                          "reward_observer_digit_calls": 10 * len(batches),
                          "reward_observer_digit_examples": 10 * sum(len(b.source_ids) for _, b in batches),
                          "audit_observer_calls": 0, "test_retention_forward_calls": 0}}
    write_json(directory / "FIT_SELECTION.json", selection)
    trace = {"schema": "hepta.field-bridge.v2.reused-training-path.1", "profile": "ordinary",
             "seed": seed, "source_bank_sha256": digest(bank_path), "records": rows,
             "reuse": True, "selected_constant_action": selected["action_index"],
             "logical_path_resources_already_in_shared_bank": path_resources(
                 len(rows), response, clean, action, recipe["steps"] if selected["action_index"] else 0),
             "new_gradient_or_probe_calls": 0}
    write_json(directory / "ordinary.json", trace)
    metadata = {"seed": seed, "profile": "ordinary", "source_identity": identity,
                "fixed_action": action, "schedule_id": P["schedule_id"], "steps": recipe["steps"],
                "source_files": sources, "reused_checkpoint_sha256": selected["source_checkpoint_sha256"],
                "selection_sha256": digest(directory / "FIT_SELECTION.json")}
    receipt = checkpoint_receipt(directory / "ordinary.pt", out, model, optimizer, recipe,
                                 metadata, original, seed)
    receipt.update(trace=str((directory / "ordinary.json").relative_to(out)),
                   trace_sha256=digest(directory / "ordinary.json"),
                   selected_constant_action=selected["action_index"], reused_from_shared_fit=True,
                   actual_new_gradient_calls=0, actual_new_boundary_probe_calls=0)
    return receipt, selection


def closed_loop(args, profile, controller, corpus, observer, original, identity, recipe, action, sources, out, directory):
    seed = args.seed
    model, data = make_model(original, seed, recipe), gradient_corpus(corpus)
    optimizer = new_optimizer(model, recipe)
    base_identity = frozen_base_hash(model)
    response, clean = panel(corpus, P["response_panel"], seed), panel(corpus, P["clean_probe"], seed)
    records, advanced, started = [], 0, time.perf_counter_ns()
    controller_hash = object_hash(controller)
    stream_path = directory / f"{profile}-decisions-before-updates.jsonl"
    with stream_path.open("x") as stream:
        for step in range(0, recipe["steps"], P["macro_steps"]):
            current = hard_outputs(model, response, observer, action)
            state = observe_field(model, optimizer, recipe, response, clean, action, step, current["value"])
            state += margin_features(model, response, observer, action)
            predicted = np.asarray(predict(controller, state, current["value"]), dtype=np.float64)
            if predicted.shape != (4,) or not np.isfinite(predicted).all():
                raise FloatingPointError("Primary controller produced an invalid four-action prediction")
            choice = int(np.argmax(predicted))
            decision = {"profile": profile, "seed": seed, "step": step, "state": state,
                "local_sha256": local_hash(model), "optimizer_sha256": optimizer_hash(optimizer),
                "controller_sha256": controller_hash, "predicted_values": predicted.tolist(),
                "choice": choice, "multiplier": P["multipliers"][choice],
                "current_value": current["value"], "current_output_sha256": object_hash(current["output_sha256"]),
                "schedule_sha256": object_hash(schedule(seed, step, P["macro_steps"])),
                "committed_monotonic_ns": time.monotonic_ns()}
            stream.write(json.dumps(decision, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
            train_steps(model, original, optimizer, data, action, recipe, seed, P["schedule_id"],
                        step, P["macro_steps"], P["multipliers"][choice])
            after = {"local_sha256": local_hash(model), "optimizer_sha256": optimizer_hash(optimizer)}
            if choice == 0 and any(after[k] != decision[k] for k in after):
                raise RuntimeError("Primary no-update action changed local weights or complete optimizer")
            advanced += P["macro_steps"] if choice else 0
            records.append({**decision, "decision_sha256": object_hash(decision), "after": after,
                            "completed_monotonic_ns": time.monotonic_ns()})
    if frozen_base_hash(model) != base_identity:
        raise RuntimeError("Primary adaptation changed a frozen base parameter")
    trace = {"schema": "hepta.field-bridge.v2.primary-training-trace.1", "profile": profile,
        "seed": seed, "records": records, "controller_sha256": controller_hash,
        "schedule_id": P["schedule_id"], "resources": path_resources(len(records), response, clean, action, advanced),
        "wall_ns": time.perf_counter_ns() - started, "audit_observer_loaded": False,
        "test_retention_scored": False, "decisions_file_sha256": digest(stream_path)}
    trace["resources"]["predictor_calls"] = len(records)
    write_json(directory / f"{profile}.json", trace)
    metadata = {"seed": seed, "profile": profile, "source_identity": identity, "fixed_action": action,
                "schedule_id": P["schedule_id"], "steps": recipe["steps"], "source_files": sources,
                "controller_sha256": controller_hash, "trace_sha256": digest(directory / f"{profile}.json")}
    receipt = checkpoint_receipt(directory / f"{profile}.pt", out, model, optimizer, recipe,
                                 metadata, original, seed)
    receipt.update(trace=str((directory / f"{profile}.json").relative_to(out)),
                   trace_sha256=digest(directory / f"{profile}.json"),
                   decisions_sha256=digest(stream_path), resources=trace["resources"], wall_ns=trace["wall_ns"])
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", required=True)
    parser.add_argument("--pilot", required=True)
    parser.add_argument("--parent-bank", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--seed", type=int, choices=P["seeds"], required=True)
    parser.add_argument("--registered-commit", required=True)
    args = parser.parse_args()
    started, sources = time.perf_counter_ns(), source_freeze()
    parent, pilot_path = Path(args.parent_bank), Path(args.pilot) / "PILOT_RESULT.json"
    if digest(pilot_path) != P["parent_pilot_result_sha256"]:
        raise ValueError("Primary actuator pilot identity differs")
    pilot = json.loads(pilot_path.read_text())
    recipe = PILOT["candidates"][pilot["selected"]["index"]]
    if (not pilot["allowed_to_fit_field"] or recipe != P["recipe"]
            or P["multipliers"] != B["multipliers"] or P["macro_steps"] != B["macro_steps"]):
        raise ValueError("Primary training treatment differs from qualified H7")
    freeze, qualification = qualified_H7(parent)
    if freeze["decision_steps"] != list(range(0, recipe["steps"], P["macro_steps"])):
        raise ValueError("Primary training decision grid differs from frozen predictors")
    controllers = {}
    for profile in ("field", "generic", "richer"):
        path = parent / "controllers" / f"{args.seed}-{profile}.json"
        controller = json.loads(path.read_text())
        if (digest(path) != freeze["controller_files_sha256"][str(path.relative_to(parent))]
                or object_hash(controller) != freeze["controller_sha256"][str(args.seed)][profile]):
            raise ValueError("Primary predictor changed after original pre-audit freeze")
        controllers[profile] = controller
    corpus, observers, originals, identities = setup_primary(args)
    if "audit" in observers:
        raise ValueError("Primary training must not load the independent audit observer")
    seed, action = args.seed, pilot["results"][str(args.seed)]["action"]
    out = Path(args.out).resolve()
    directory = out / "training" / str(seed)
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "SOURCE_FREEZE.json", {"source_files": sources,
               "registered_commit": args.registered_commit, "qualification": qualification})
    profiles = {}
    profiles["ordinary"], selection = ordinary_selection(args, corpus, observers["reward"], originals[seed],
        identities[seed], recipe, action, sources, out, directory)
    if abs(selection["baseline"]["value"] - pilot["results"][str(seed)]["baseline_value"]) > 1e-12:
        raise ValueError("Existing pilot development panel/fixed-policy baseline no longer reproduces")
    for profile, controller in controllers.items():
        profiles[profile] = closed_loop(args, profile, controller, corpus, observers["reward"], originals[seed],
            identities[seed], recipe, action, sources, out, directory)
        print(f"primary seed={seed} profile={profile} complete", flush=True)
    if source_freeze() != sources:
        raise RuntimeError("Primary scientific sources changed during training")
    fit_bank = json.loads((parent / f"fit-{seed}" / "BANK.json").read_text())
    audit_bank = json.loads((parent / f"audit-{seed}" / "BANK.json").read_text())
    complete = {"schema": "hepta.field-bridge.v2.primary-training-seed.1", "seed": seed,
        "recipe": recipe, "fixed_action": action, "profiles": profiles,
        "original_identity": identities[seed], "source_files": sources,
        "registered_commit": args.registered_commit, "qualification": qualification,
        "ordinary_selection_sha256": digest(directory / "FIT_SELECTION.json"),
        "ordinary_selection_new_resources": selection["new_resources"],
        "shared_fit_resources_count_once": fit_bank["resources"],
        "shared_fit_wall_ns": fit_bank["wall_ns"],
        "qualification_audit_resources_count_once": audit_bank["resources"],
        "qualification_audit_wall_ns": audit_bank["wall_ns"],
        "shared_predictor_fit_freeze_sha256": digest(parent / "PREDICTOR_FREEZE.json"),
        "predictor_fit_counting": "Count the parent freeze fit_candidate_evaluations and wall_ns once for all seeds/profiles",
        "wall_ns": time.perf_counter_ns() - started, "audit_observer_loaded": False,
        "test_retention_scored": False, "all_profiles_complete": True}
    write_json(directory / "COMPLETE.json", complete)
    print(f"primary seed={seed} complete: {directory / 'COMPLETE.json'}", flush=True)


if __name__ == "__main__":
    main()
