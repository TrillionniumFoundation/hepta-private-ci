"""Prespecified deterministic development-bank replay with actual media readback.

This repeats selected computations from their original initialization, including
complete optimizer state. It is execution verification on the same training
panel, not a new statistical replication or new task-label evaluation.
"""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from ..field_bridge_20261027.run import setup
from ..field_bridge_20261027.adaptation import fixed_output
from ..field_bridge_20261027.adapters import local_hash, frozen_base_hash
from ..v6.data import render_tokens
from ..v6.observer import observe_tensors, write_bundle, read_bundle
from ..field_bridge_v2_20261027.learning import (
    P, make_model, new_optimizer, gradient_corpus, panel, train_steps,
    observe_field, optimizer_hash,
)
from ..field_bridge_v2_20261027.field_bank import B, margin_features
from ..field_bridge_v2_20261027.field_predictor import predict
from .bank_integrity_audit import digest, object_hash


@torch.inference_mode()
def independently_score(model, response, observer, action, media_root=None):
    values, hashes, media = [], [], []
    for condition_index, (condition, batch) in enumerate(response):
        output = fixed_output(model, batch, action, 91027 + condition_index)
        pixels = (output.image_logits.sigmoid() * 255).round().to(torch.uint8)
        captions = [render_tokens(tokens) for tokens in output.token_ids]
        score_pixels = pixels.float() / 255
        if media_root is not None:
            for index in range(2):
                paths = write_bundle(media_root / condition / str(index), captions[index], score_pixels[index])
                restored_pixels, restored_caption, file_hashes = read_bundle(paths)
                if not torch.equal(restored_pixels[0], score_pixels[index]) or restored_caption != captions[index]:
                    raise ValueError("Delivered PNG/UTF8 differs from the actual decoder output")
                score_pixels[index] = restored_pixels[0]
                captions[index] = restored_caption
                media.append({"condition": condition, "index": index,
                    "relative_paths": {key: str(Path(value).relative_to(media_root)) for key, value in paths.items()},
                    "sha256": file_hashes})
        scores = observe_tensors(observer, score_pixels, captions, batch.target.pixels, batch.target.labels)
        values.extend(row["utility"] - .002 * (1 + (action != 0)) for row in scores)
        hashes.extend(hashlib.sha256(pixels[index].numpy().tobytes() + caption.encode()).hexdigest()
                      for index, caption in enumerate(captions))
    return {"value": float(np.mean(values)), "values": np.asarray(values, dtype=np.float64),
            "output_sha256": object_hash(hashes), "media": media}


def independent_clone(model, optimizer, recipe):
    copied = deepcopy(model)
    other = torch.optim.SGD([p for p in copied.parameters() if p.requires_grad],
                            lr=recipe["learning_rate"], momentum=P["momentum"])
    other.load_state_dict(deepcopy(optimizer.state_dict()))
    if local_hash(copied) != local_hash(model) or optimizer_hash(other) != optimizer_hash(optimizer):
        raise ValueError("Replay did not copy complete local state")
    return copied, other


def replay_phase(bank_root, phase, seed, corpus, observers, originals, destination, plan, controllers):
    directory = bank_root / f"{phase}-{seed}"
    bank = json.loads((directory / "BANK.json").read_text())
    complete = json.loads((directory / "COMPLETE.json").read_text())
    if complete["bank_sha256"] != digest(directory / "BANK.json"):
        raise ValueError("Replay source bank differs from completed identity")
    recipe, action = bank["recipe"], bank["fixed_action"]
    original, observer = originals[seed], observers["reward"]
    response = panel(corpus, P["response_panel"], seed)
    clean = panel(corpus, P["clean_probe"], seed)
    data = gradient_corpus(corpus)
    records = {(row["trajectory"], row["step"]): row for row in bank["records"]}
    report, vectors = [], []
    gradient_calls = 0
    for trajectory in plan[phase + "_trajectories"]:
        with np.load(directory / f"trajectory-{trajectory}-values.npz", allow_pickle=False) as file:
            expected_vectors = file["values"]
        model = make_model(original, seed, recipe)
        optimizer = new_optimizer(model, recipe)
        base = frozen_base_hash(model)
        schedule_id = 0 if trajectory < 4 else trajectory
        rng = np.random.default_rng(271028 + seed * 1009 + trajectory * 7919)
        for step in range(0, max(plan["steps"]) + 1, B["macro_steps"]):
            row = records[(trajectory, step)]
            selected = trajectory if trajectory < 4 else int(rng.integers(4))
            if (selected != row["trajectory_action"] or local_hash(model) != row["state_sha256"]
                    or optimizer_hash(optimizer) != row["optimizer_sha256"]):
                raise ValueError("Replayed preceding trajectory differs before a branch")
            if step not in plan["steps"]:
                train_steps(model, original, optimizer, data, action, recipe, seed,
                            schedule_id, step, B["macro_steps"], B["multipliers"][selected])
                gradient_calls += B["macro_steps"]
                continue
            current = independently_score(model, response, observer, action)
            field = observe_field(model, optimizer, recipe, response, clean, action, step, current["value"])
            field += margin_features(model, response, observer, action)
            feature_error = float(np.max(np.abs(np.asarray(field) - row["state"])))
            if (abs(current["value"] - row["current_value"]) > 1e-12
                    or current["output_sha256"] != row["before_output_sha256"] or feature_error > 1e-12):
                raise ValueError("Current hard output or field differs on deterministic replay")
            prediction_error = 0.
            if phase == "audit":
                for mode, controller in controllers[str(seed)].items():
                    value = predict(controller, field, current["value"])
                    prediction_error = max(prediction_error, float(np.max(np.abs(np.asarray(value) - row["predictions"][mode]))))
                if prediction_error > 1e-12:
                    raise ValueError("Frozen audit predictions differ on replay")
            branches, next_model, next_optimizer = [], None, None
            for index in plan["branches"]:
                branch, branch_optimizer = independent_clone(model, optimizer, recipe)
                train_steps(branch, original, branch_optimizer, data, action, recipe, seed,
                            schedule_id, step, B["macro_steps"], B["multipliers"][index])
                gradient_calls += B["macro_steps"]
                media = destination / "media" / f"{phase}-{seed}-t{trajectory}-s{step}-a{index}"
                actual = independently_score(branch, response, observer, action, media)
                expected = expected_vectors[step // B["macro_steps"], index]
                error = float(np.max(np.abs(actual["values"] - expected)))
                source = row["branches"][index]
                if (error > 1e-12 or abs(actual["value"] - row["action_values"][index]) > 1e-12
                        or actual["output_sha256"] != source["output_sha256"]
                        or local_hash(branch) != source["model_sha256"]
                        or optimizer_hash(branch_optimizer) != source["optimizer_sha256"]):
                    raise ValueError("Replayed branch state or decoded hard values differ")
                branches.append({"action": index, "value": actual["value"], "max_value_error": error,
                    "model_sha256": local_hash(branch), "optimizer_sha256": optimizer_hash(branch_optimizer),
                    "output_sha256": actual["output_sha256"], "media_root": str(media.relative_to(destination)),
                    "media_readbacks": actual["media"]})
                vectors.append(actual["values"])
                if index == selected:
                    next_model, next_optimizer = branch, branch_optimizer
            report.append({"phase": phase, "seed": seed, "trajectory": trajectory, "step": step,
                           "state_sha256": row["state_sha256"], "optimizer_sha256": row["optimizer_sha256"],
                           "before_output_sha256": current["output_sha256"], "max_field_error": feature_error,
                           "max_prediction_error": prediction_error, "branches": branches})
            model, optimizer = next_model, next_optimizer
            print(f"replay {phase} seed={seed} trajectory={trajectory} step={step}: four branches exact", flush=True)
        if frozen_base_hash(model) != base:
            raise ValueError("Replay changed the frozen original backbone")
    return report, vectors, gradient_calls


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank", type=Path, required=True)
    parser.add_argument("--assets", required=True)
    parser.add_argument("--phase", choices=("fit", "audit", "all"), required=True)
    parser.add_argument("--plan", type=Path, default=Path(__file__).with_name("REPLAY_PLAN.json"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Replay output directory must be new")
    plan = json.loads(args.plan.read_text())
    phases = ("fit", "audit") if args.phase == "all" else (args.phase,)
    study_parent = Path(__file__).parent.parent
    source_before = json.loads((args.bank / "fit-17" / "SOURCE_FREEZE.json").read_text())["files"]
    if any(digest(study_parent / path) != identity for path, identity in source_before.items()):
        raise ValueError("Frozen source identity changed before replay")
    controllers, input_files = {}, {}
    if "audit" in phases:
        freeze_path = args.bank / "PREDICTOR_FREEZE.json"
        freeze = json.loads(freeze_path.read_text())
        input_files[str(freeze_path)] = digest(freeze_path)
        for seed in plan["seeds"]:
            controllers[str(seed)] = {}
            for mode in ("field", "generic", "richer"):
                path = args.bank / "controllers" / f"{seed}-{mode}.json"
                value = json.loads(path.read_text())
                if object_hash(value) != freeze["controller_sha256"][str(seed)][mode]:
                    raise ValueError("Replay predictor differs from the pre-audit freeze")
                controllers[str(seed)][mode] = value
                input_files[str(path)] = digest(path)
    corpus, observers, originals, _ = setup(args)
    args.out.mkdir(parents=True)
    started = time.perf_counter_ns()
    reports, all_vectors, gradients = [], [], 0
    for phase in phases:
        for seed in plan["seeds"]:
            rows, vectors, calls = replay_phase(args.bank, phase, seed, corpus, observers, originals,
                                                args.out, plan, controllers)
            reports.extend(rows)
            all_vectors.extend(vectors)
            gradients += calls
            path = args.bank / f"{phase}-{seed}" / "BANK.json"
            input_files[str(path)] = digest(path)
    if any(digest(study_parent / path) != identity for path, identity in source_before.items()):
        raise ValueError("Frozen source identity changed during replay")
    np.savez_compressed(args.out / "REPLAYED_VALUES.npz", values=np.stack(all_vectors))
    result = {"schema": "hepta.field-bridge.v2.prespecified-bank-replay-result.v1",
              "plan_sha256": digest(args.plan), "script_sha256": digest(Path(__file__)),
              "input_files_sha256": input_files, "source_files": source_before,
              "snapshots": reports, "snapshot_count": len(reports), "branch_count": len(all_vectors),
              "individual_hard_values": int(np.stack(all_vectors).size),
              "actual_png_utf8_bundles_read_back": 8 * len(all_vectors),
              "actual_replay_gradient_calls": gradients, "gradient_examples": gradients * P["batch_size"],
              "wall_ns": time.perf_counter_ns() - started,
              "replayed_values_sha256": digest(args.out / "REPLAYED_VALUES.npz"),
              "max_hard_value_error": max(b["max_value_error"] for row in reports for b in row["branches"]),
              "max_field_error": max(row["max_field_error"] for row in reports),
              "max_prediction_error": max(row["max_prediction_error"] for row in reports),
              "audit_observer_loaded": False, "new_test_retention_scored": False,
              "scope": plan["limitations"]}
    (args.out / "REPLAY_AUDIT.json").write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({key: result[key] for key in ("snapshot_count", "branch_count", "individual_hard_values",
          "actual_png_utf8_bundles_read_back", "max_hard_value_error", "max_field_error", "max_prediction_error")}))


if __name__ == "__main__":
    main()
