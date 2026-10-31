"""Complete counterfactual local training branches on development data only."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from ..field_bridge_20261027.run import setup, write_json, digest, object_hash
from ..field_bridge_20261027.adapters import local_hash, frozen_base_hash
from ..field_bridge_20261027.adaptation import fixed_output
from .learning import P, make_model, new_optimizer, gradient_corpus, panel, hard_outputs
from .learning import clone_optimizer_model, train_steps, observe_field, optimizer_hash, save_model
from .field_predictor import predict

B = json.loads(Path(__file__).with_name("BANK_PROTOCOL.json").read_text())


def source_freeze():
    root = Path(__file__).parent
    names = ("__init__.py", "learning.py", "PILOT_PROTOCOL.json", "BANK_PROTOCOL.json", "field_bank.py", "field_predictor.py", "field_fit.py")
    paths = [root / name for name in names]
    paths.extend((root.parent / "field_bridge_20261027").glob("*.py"))
    paths.extend((root.parent / "v6").glob("*.py"))
    paths.append(root.parent / "field_bridge_v2_20261027_review" / "gate_audit.py")
    return {str(path.relative_to(root.parent)): digest(path) for path in sorted(paths)}


@torch.inference_mode()
def margin_features(model, batches, observer, action):
    text, image = [], []
    for index, (_, batch) in enumerate(batches):
        output = fixed_output(model, batch, action, 91027 + index)
        ordered = output.text_logits[:, [1, 3]].topk(2, dim=-1).values
        text.extend((ordered[:, :, 0] - ordered[:, :, 1]).reshape(-1).tolist())
        pixels = (output.image_logits.sigmoid() * 255).round() / 255
        for part in (pixels[:, :, :, :28], pixels[:, :, :, 28:]):
            top = observer(part).softmax(-1).topk(2, dim=-1).values
            image.extend((top[:, 0] - top[:, 1]).tolist())
    return [float(np.mean(text)), float(np.quantile(text, .1)), float(np.mean(image)),
            float(np.quantile(image, .1)), float(np.mean(np.asarray(text) < .25)),
            float(np.mean(np.asarray(image) < .1))]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("fit", "audit"))
    parser.add_argument("--assets", required=True)
    parser.add_argument("--pilot", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--seed", type=int, choices=P["seeds"], required=True)
    parser.add_argument("--registered-commit", required=True)
    parser.add_argument("--freeze")
    args = parser.parse_args()
    pilot_path = Path(args.pilot) / "PILOT_RESULT.json"
    if digest(pilot_path) != B["actuator_pilot_result_sha256"]:
        raise ValueError("Pilot outcome identity changed")
    pilot = json.loads(pilot_path.read_text())
    if not pilot["allowed_to_fit_field"] or pilot["selected"]["name"] != B["selected_recipe"]:
        raise ValueError("Actuator gate did not qualify this recipe")
    recipe = P["candidates"][pilot["selected"]["index"]]
    action = pilot["results"][str(args.seed)]["action"]
    out = Path(args.out).resolve() / f"{args.phase}-{args.seed}"
    out.mkdir(parents=True, exist_ok=False)
    sources = source_freeze()
    write_json(out / "SOURCE_FREEZE.json", {"files": sources, "registered_commit": args.registered_commit})
    corpus, observers, originals, identities = setup(args)
    original, observer, data = originals[args.seed], observers["reward"], gradient_corpus(corpus)
    response, clean = panel(corpus, P["response_panel"], args.seed), panel(corpus, P["clean_probe"], args.seed)
    controllers, controller_hashes = {}, {}
    if args.phase == "audit":
        if not args.freeze:
            raise ValueError("Audit requires a committed controller freeze")
        freeze = json.loads(Path(args.freeze).read_text())
        if freeze["source_files"] != sources or freeze["decision_steps"] != list(range(0, recipe["steps"], B["macro_steps"])):
            raise ValueError("Audit source/grid differs from the pre-audit freeze")
        for mode in ("field", "generic", "richer"):
            path = Path(args.freeze).parent / "controllers" / f"{args.seed}-{mode}.json"
            controllers[mode] = json.loads(path.read_text())
            controller_hashes[mode] = object_hash(controllers[mode])
            if controller_hashes[mode] != freeze["controller_sha256"][str(args.seed)][mode]:
                raise ValueError("Controller file differs from pre-audit freeze")
    records, started = [], time.perf_counter_ns()
    trajectories = B[args.phase + "_trajectory_ids"]
    stream = (out / "PREDICTIONS_BEFORE_OUTCOMES.jsonl").open("x")
    for trajectory in trajectories:
        model = make_model(original, args.seed, recipe)
        optimizer = new_optimizer(model, recipe)
        base_identity = frozen_base_hash(model)
        rng = np.random.default_rng(271028 + args.seed * 1009 + trajectory * 7919)
        schedule_id = 0 if trajectory < 4 else trajectory
        values_by_step = []
        for step in range(0, recipe["steps"], B["macro_steps"]):
            current = hard_outputs(model, response, observer, action)
            state = observe_field(model, optimizer, recipe, response, clean, action, step, current["value"])
            state += margin_features(model, response, observer, action)
            schedule = [{"batch_seed": args.seed * 100003 + 600000 + schedule_id * 1009 + s,
                         "noise_seed": 107 + s, "condition": P["conditions"][s % 4]}
                        for s in range(step, step + B["macro_steps"])]
            row = {"seed": args.seed, "trajectory": trajectory, "step": step, "partition": args.phase,
                   "state": state, "state_sha256": local_hash(model), "optimizer_sha256": optimizer_hash(optimizer),
                   "schedule_sha256": object_hash(schedule), "current_value": current["value"],
                   "before_output_sha256": object_hash(current["output_sha256"])}
            if args.phase == "audit":
                row["predictions"] = {mode: list(map(float, predict(c, state, current["value"]))) for mode, c in controllers.items()}
                row["prediction_controller_sha256"] = controller_hashes
            prediction = {**row, "committed_monotonic_ns": time.monotonic_ns()}
            stream.write(json.dumps(prediction, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            row["prediction_commit_sha256"] = object_hash(prediction)
            selected = trajectory if trajectory < 4 else int(rng.integers(4))
            next_model, next_optimizer, action_values, after, vectors = None, None, [], [], []
            for index, multiplier in enumerate(B["multipliers"]):
                branch, branch_optimizer = clone_optimizer_model(model, optimizer, recipe)
                train_steps(branch, original, branch_optimizer, data, action, recipe, args.seed,
                            schedule_id, step, B["macro_steps"], multiplier)
                value = hard_outputs(branch, response, observer, action)
                after.append({"action": index, "model_sha256": local_hash(branch),
                    "optimizer_sha256": optimizer_hash(branch_optimizer),
                    "output_sha256": object_hash(value["output_sha256"]),
                    "semantic_change_fraction": float(np.mean([a != b for a, b in zip(current["decisions"], value["decisions"])])),
                    "measured_monotonic_ns": time.monotonic_ns()})
                if index == 0 and (value != current or local_hash(branch) != row["state_sha256"]
                                   or optimizer_hash(branch_optimizer) != row["optimizer_sha256"]):
                    raise RuntimeError("No-update action failed exact state/output invariance")
                action_values.append(value["value"])
                vectors.append(value["values"])
                if index == selected:
                    next_model, next_optimizer = branch, branch_optimizer
            row.update(action_values=action_values, branches=after, trajectory_action=selected,
                       outcomes_completed_monotonic_ns=time.monotonic_ns())
            records.append(row)
            values_by_step.append(vectors)
            model, optimizer = next_model, next_optimizer
        if frozen_base_hash(model) != base_identity:
            raise RuntimeError("Exploratory trajectory changed frozen base")
        np.savez_compressed(out / f"trajectory-{trajectory}-values.npz", values=np.asarray(values_by_step))
        save_model(out / f"trajectory-{trajectory}-terminal.pt", model, optimizer, recipe,
                   {"seed": args.seed, "trajectory": trajectory, "phase": args.phase,
                    "source_identity": identities[args.seed], "fixed_action": action})
        write_json(out / "BANK.json", {"records": records, "completed_trajectories": trajectories[:trajectories.index(trajectory) + 1]})
        print(f"{args.phase} seed={args.seed} trajectory={trajectory} complete ({len(records)} complete branch sets)", flush=True)
    stream.close()
    if source_freeze() != sources:
        raise RuntimeError("Bank source changed during execution")
    n, panel_examples = len(records), sum(len(batch.source_ids) for _, batch in response)
    clean_examples = sum(len(batch.source_ids) for _, batch in clean)
    gradient_calls = n * len(B["multipliers"]) * B["macro_steps"]
    resources = {
        "count_definition": "Actual example-level network calls; each fixed_output includes encode, first couple, selected fixed continuation if non-stop, and one decoder call. This is not FLOPs, energy or money.",
        "candidate_gradient_forward_calls": gradient_calls,
        "candidate_gradient_examples": gradient_calls * P["batch_size"],
        "candidate_backward_calls": gradient_calls,
        "frozen_teacher_forward_calls": gradient_calls,
        "frozen_teacher_examples": gradient_calls * P["batch_size"],
        "teacher_forced_field_probe_calls": n * (len(response) + len(clean)),
        "teacher_forced_field_probe_examples": n * (panel_examples + clean_examples),
        "current_and_branch_hard_value_forward_calls": n * 5 * len(response),
        "current_and_branch_hard_value_examples": n * 5 * panel_examples,
        "rich_margin_forward_calls": n * len(response),
        "rich_margin_examples": n * panel_examples,
        "hard_value_and_margin_observer_digit_calls": n * 12 * len(response),
        "hard_value_and_margin_observer_digit_examples": n * 12 * panel_examples,
        "fixed_refinements_per_forward_example": 1 + (action != 0),
        "zero_branches_compute_gradients_but_hold_weights_and_momentum": True,
        "audit_observer_calls": 0, "test_retention_forward_calls": 0,
    }
    result = {"schema": "hepta.field-bridge.v2.branch-bank.1", "records": records, "recipe": recipe,
        "phase": args.phase, "seed": args.seed, "fixed_action": action,
        "source_files": sources, "registered_commit": args.registered_commit,
        "gradient_steps": len(records) * len(B["multipliers"]) * B["macro_steps"],
        "gradient_examples": len(records) * len(B["multipliers"]) * B["macro_steps"] * P["batch_size"],
        "wall_ns": time.perf_counter_ns() - started, "resources": resources, "audit_observer_loaded": False,
        "test_retention_scored": False, "same_fixed_training_value_panel": True}
    write_json(out / "BANK.json", result)
    write_json(out / "COMPLETE.json", {"bank_sha256": digest(out / "BANK.json"), "rows": len(records),
                                      "source_files": sources, "wall_ns": result["wall_ns"]})


if __name__ == "__main__":
    main()
