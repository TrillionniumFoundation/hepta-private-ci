"""Conditional directional-field development; the H7 study remains immutable.

Fitting labels are inherited from the verified H7 fitting bank. Only current
observations are enriched by replay. Audit labels use fresh path IDs 16..23.
"""

import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch

from ..field_bridge_20261027.run import setup, write_json, digest, object_hash
from ..field_bridge_20261027.adapters import local_hash, frozen_base_hash
from ..field_bridge_v2_20261027_review.gate_audit import audit as parent_gate_audit
from .learning import P, make_model, new_optimizer, gradient_corpus, panel, hard_outputs
from .learning import clone_optimizer_model, train_steps, observe_field, optimizer_hash, save_model
from .field_bank import B, margin_features, source_freeze as parent_source_freeze
from .directional_features import measure_directional
from .directional_predictor import predict


def source_freeze():
    root = Path(__file__).parent
    result = parent_source_freeze()
    for name in ("directional_bank.py", "directional_fit.py", "directional_features.py",
                 "directional_predictor.py", "DIRECTIONAL_PROTOCOL.json"):
        result[str((root / name).relative_to(root.parent))] = digest(root / name)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("fit", "audit"))
    parser.add_argument("--assets", required=True)
    parser.add_argument("--pilot", required=True)
    parser.add_argument("--parent-bank", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--seed", type=int, choices=P["seeds"], required=True)
    parser.add_argument("--registered-commit", required=True)
    parser.add_argument("--freeze")
    parser.add_argument("--parent-gates")
    args = parser.parse_args()
    pilot_file = Path(args.pilot) / "PILOT_RESULT.json"
    if digest(pilot_file) != B["actuator_pilot_result_sha256"]:
        raise ValueError("Actuator pilot changed")
    pilot = json.loads(pilot_file.read_text())
    recipe = P["candidates"][pilot["selected"]["index"]]
    if not pilot["allowed_to_fit_field"] or recipe["name"] != B["selected_recipe"]:
        raise ValueError("Unqualified local actuator")
    parent_gate_inputs = {}
    if args.phase == "audit":
        if not args.freeze or not args.parent_gates:
            raise ValueError("Conditional audit requires a predictor freeze and completed H7 gates")
        parent_gates = json.loads(Path(args.parent_gates).read_text())
        parent_root = Path(args.parent_bank)
        parent_freeze = json.loads((parent_root / "PREDICTOR_FREEZE.json").read_text())
        parent_records = []
        for partition in ("fit", "audit"):
            for seed in P["seeds"]:
                bank_path = parent_root / f"{partition}-{seed}" / "BANK.json"
                completion = json.loads(bank_path.with_name("COMPLETE.json").read_text())
                if (digest(bank_path) != completion["bank_sha256"]
                        or completion["source_files"] != parent_source_freeze()):
                    raise ValueError("Parent gate is not backed by completed immutable H7 banks")
                parent_gate_inputs[str(bank_path.relative_to(parent_root))] = digest(bank_path)
                parent_records.extend(json.loads(bank_path.read_text())["records"])
        reconstructed = parent_gate_audit(parent_records, parent_freeze)
        if any(parent_gates.get(k) != v for k, v in reconstructed.items()):
            raise ValueError("Supplied H7 gate receipt differs from independently reconstructed gates")
        parent_gate_inputs["PREDICTOR_FREEZE.json"] = digest(parent_root / "PREDICTOR_FREEZE.json")
        if parent_gates["gates"]["field_prediction_skill"] and parent_gates["gates"]["field_decision_skill"]:
            raise ValueError("H7 predictive/choice gates passed; conditional repair audit is not authorized by its protocol")
    action = pilot["results"][str(args.seed)]["action"]
    out = Path(args.out).resolve() / f"{args.phase}-{args.seed}"
    out.mkdir(parents=True, exist_ok=False)
    sources = source_freeze()
    write_json(out / "SOURCE_FREEZE.json", {"files": sources, "registered_commit": args.registered_commit})
    corpus, observers, originals, identities = setup(args)
    original, observer, data = originals[args.seed], observers["reward"], gradient_corpus(corpus)
    response, clean = panel(corpus, P["response_panel"], args.seed), panel(corpus, P["clean_probe"], args.seed)
    parent_path = Path(args.parent_bank) / f"fit-{args.seed}" / "BANK.json"
    parent = json.loads(parent_path.read_text())
    complete = json.loads(parent_path.with_name("COMPLETE.json").read_text())
    if digest(parent_path) != complete["bank_sha256"] or complete["source_files"] != parent_source_freeze():
        raise ValueError("Original fitting bank is not the verified frozen source")
    parent_rows = {(r["trajectory"], r["step"]): r for r in parent["records"]}
    controllers, controller_hashes = {}, {}
    if args.phase == "audit":
        freeze = json.loads(Path(args.freeze).read_text())
        if freeze["source_files"] != sources or freeze["decision_steps"] != list(range(0, recipe["steps"], 8)):
            raise ValueError("Directional source or decision grid differs from freeze")
        for mode in ("field", "generic", "richer"):
            c = json.loads((Path(args.freeze).parent / "controllers" / f"{args.seed}-{mode}.json").read_text())
            if object_hash(c) != freeze["controller_sha256"][str(args.seed)][mode]:
                raise ValueError("Directional controller identity changed")
            controllers[mode], controller_hashes[mode] = c, object_hash(c)
    trajectories = list(range(8)) if args.phase == "fit" else list(range(16, 24))
    records, receipts, started = [], [], time.perf_counter_ns()
    stream = (out / "PREDICTIONS_BEFORE_OUTCOMES.jsonl").open("x")
    for trajectory in trajectories:
        model = make_model(original, args.seed, recipe)
        optimizer = new_optimizer(model, recipe)
        base_identity = frozen_base_hash(model)
        rng = np.random.default_rng(271028 + args.seed * 1009 + trajectory * 7919)
        schedule_id = 0 if trajectory < 4 else trajectory
        vectors_by_step = []
        for step in range(0, recipe["steps"], 8):
            current = hard_outputs(model, response, observer, action)
            old_state = observe_field(model, optimizer, recipe, response, clean, action, step, current["value"])
            old_state += margin_features(model, response, observer, action)
            state_identity, opt_identity = local_hash(model), optimizer_hash(optimizer)
            extras, feature_receipt = measure_directional(model, original, optimizer, data, recipe,
                args.seed, schedule_id, step, response, clean, action)
            if local_hash(model) != state_identity or optimizer_hash(optimizer) != opt_identity:
                raise RuntimeError("Directional observation changed the controlled state")
            state = old_state[:7] + list(extras) + old_state[7:]
            if len(state) != 30:
                raise ValueError("Directional field must have twelve selected and eighteen richer coordinates")
            schedule = [{"batch_seed": args.seed * 100003 + 600000 + schedule_id * 1009 + s,
                         "noise_seed": 107 + s, "condition": P["conditions"][s % 4]}
                        for s in range(step, step + 8)]
            row = {"seed": args.seed, "trajectory": trajectory, "step": step, "partition": args.phase,
                   "state": state, "state_sha256": state_identity, "optimizer_sha256": opt_identity,
                   "schedule_sha256": object_hash(schedule), "current_value": current["value"],
                   "before_output_sha256": object_hash(current["output_sha256"]),
                   "directional_receipt_sha256": object_hash(feature_receipt)}
            receipts.append({"seed": args.seed, "trajectory": trajectory, "step": step, **feature_receipt})
            selected = trajectory if trajectory < 4 else int(rng.integers(4))
            if args.phase == "fit":
                old = parent_rows[(trajectory, step)]
                if (old_state != old["state"] or current["value"] != old["current_value"]
                        or state_identity != old["state_sha256"] or opt_identity != old["optimizer_sha256"]
                        or row["before_output_sha256"] != old["before_output_sha256"]
                        or row["schedule_sha256"] != old["schedule_sha256"] or selected != old["trajectory_action"]):
                    raise RuntimeError("Enrichment did not reproduce the original fitting state exactly")
                row.update(action_values=old["action_values"], branches=old["branches"], trajectory_action=selected,
                           inherited_parent_row_sha256=object_hash(old), fitting_labels_inherited=True)
                train_steps(model, original, optimizer, data, action, recipe, args.seed, schedule_id, step, 8,
                            B["multipliers"][selected])
                target = old["branches"][selected]
                if local_hash(model) != target["model_sha256"] or optimizer_hash(optimizer) != target["optimizer_sha256"]:
                    raise RuntimeError("Enriched trajectory failed exact original continuation")
            else:
                row["predictions"] = {mode: predict(c, state, current["value"]) for mode, c in controllers.items()}
                row["prediction_controller_sha256"] = controller_hashes
                prediction = {**row, "committed_monotonic_ns": time.monotonic_ns()}
                stream.write(json.dumps(prediction, sort_keys=True, allow_nan=False) + "\n")
                stream.flush()
                row["prediction_commit_sha256"] = object_hash(prediction)
                next_model, next_optimizer, values, after, vectors = None, None, [], [], []
                for index, multiplier in enumerate(B["multipliers"]):
                    branch, branch_optimizer = clone_optimizer_model(model, optimizer, recipe)
                    train_steps(branch, original, branch_optimizer, data, action, recipe, args.seed,
                                schedule_id, step, 8, multiplier)
                    output = hard_outputs(branch, response, observer, action)
                    after.append({"action": index, "model_sha256": local_hash(branch),
                        "optimizer_sha256": optimizer_hash(branch_optimizer),
                        "output_sha256": object_hash(output["output_sha256"]),
                        "semantic_change_fraction": float(np.mean([a != b for a, b in zip(current["decisions"], output["decisions"])])),
                        "measured_monotonic_ns": time.monotonic_ns()})
                    if index == 0 and (output != current or after[-1]["model_sha256"] != state_identity
                                       or after[-1]["optimizer_sha256"] != opt_identity):
                        raise RuntimeError("Directional no-update branch changed state or output")
                    values.append(output["value"])
                    vectors.append(output["values"])
                    if index == selected:
                        next_model, next_optimizer = branch, branch_optimizer
                row.update(action_values=values, branches=after, trajectory_action=selected,
                           outcomes_completed_monotonic_ns=time.monotonic_ns())
                vectors_by_step.append(vectors)
                model, optimizer = next_model, next_optimizer
            records.append(row)
        if frozen_base_hash(model) != base_identity:
            raise RuntimeError("Directional trajectory changed frozen generator")
        if args.phase == "audit":
            np.savez_compressed(out / f"trajectory-{trajectory}-values.npz", values=np.asarray(vectors_by_step))
        save_model(out / f"trajectory-{trajectory}-terminal.pt", model, optimizer, recipe,
                   {"seed": args.seed, "trajectory": trajectory, "phase": args.phase, "source_identity": identities[args.seed]})
        write_json(out / "BANK.json", {"records": records, "completed_trajectories": trajectories[:trajectories.index(trajectory) + 1]})
        write_json(out / "DIRECTIONAL_RECEIPTS.json", receipts)
        print(f"directional {args.phase} seed={args.seed} trajectory={trajectory} complete ({len(records)} snapshots)", flush=True)
    stream.close()
    if source_freeze() != sources:
        raise RuntimeError("Directional scientific source changed during execution")
    n, panel_examples = len(records), sum(len(batch.source_ids) for _, batch in response)
    clean_examples = sum(len(batch.source_ids) for _, batch in clean)
    gradient_calls, hard_factor = n * 8 * (1 if args.phase == "fit" else 4), 1 if args.phase == "fit" else 5
    directional_resources = {key: sum(row["resources"][key] for row in receipts)
                             for key in receipts[0]["resources"]}
    resources = {
        "candidate_gradient_forward_calls": gradient_calls,
        "candidate_gradient_examples": gradient_calls * P["batch_size"],
        "candidate_backward_calls": gradient_calls,
        "frozen_teacher_forward_calls": gradient_calls,
        "frozen_teacher_examples": gradient_calls * P["batch_size"],
        "teacher_forced_H25_probe_calls": n * (len(response) + len(clean)),
        "teacher_forced_H25_probe_examples": n * (panel_examples + clean_examples),
        "current_and_branch_hard_value_forward_calls": n * hard_factor * len(response),
        "current_and_branch_hard_value_examples": n * hard_factor * panel_examples,
        "rich_margin_forward_calls": n * len(response), "rich_margin_examples": n * panel_examples,
        "hard_value_and_margin_observer_digit_calls": n * 2 * (hard_factor + 1) * len(response),
        "hard_value_and_margin_observer_digit_examples": n * 2 * (hard_factor + 1) * panel_examples,
        "additional_directional_observation_work": directional_resources,
        "fixed_refinements_per_forward_example": 1 + (action != 0),
        "audit_observer_calls": 0, "test_retention_forward_calls": 0,
        "inherited_parent_fitting_resources": parent["resources"],
        "accounting": "Base counts exclude the separately summed directional work. Inherited parent search is shared existing work, counted once across modes; never omitted when reporting total search. Counts are calls/examples, not FLOPs or money.",
    }
    result = {"schema": "hepta.field-bridge.v2.directional-bank.1", "records": records,
        "phase": args.phase, "seed": args.seed, "recipe": recipe, "fixed_action": action,
        "source_files": sources, "registered_commit": args.registered_commit,
        "parent_fit_bank_sha256": digest(parent_path), "parent_fit_label_rows": len(records) if args.phase == "fit" else 0,
        "chosen_path_or_branch_gradient_calls": len(records) * 8 * (1 if args.phase == "fit" else 4),
        "chosen_path_or_branch_gradient_examples": len(records) * 8 * (1 if args.phase == "fit" else 4) * P["batch_size"],
        "additional_directional_measurements": len(receipts), "directional_receipts_sha256": digest(out / "DIRECTIONAL_RECEIPTS.json"),
        "resources": resources, "parent_gate_inputs_sha256": parent_gate_inputs,
        "wall_ns": time.perf_counter_ns() - started, "test_retention_scored": False,
        "audit_observer_loaded": False, "H7_audit_labels_used_for_fitting": False,
        "parent_gate_file_sha256": digest(args.parent_gates) if args.phase == "audit" else None}
    write_json(out / "BANK.json", result)
    write_json(out / "COMPLETE.json", {"bank_sha256": digest(out / "BANK.json"), "source_files": sources,
                                      "rows": len(records), "wall_ns": result["wall_ns"]})


if __name__ == "__main__":
    main()
