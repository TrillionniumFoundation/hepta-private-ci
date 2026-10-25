"""Fixed inference and a separate-process, label-free full-output replay."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np

from .data_prepare import public_observations
from .io import (arrays, clock, cost, cpu_environment, deny_final, digest, file_hash,
                               published_source, read_arrays, read_json, require_identity, run_stage,
                               require_owner, seal, source_hashes, validate_data, verify_seal, write)
from .gates import verify_model_seal, verify_training


PLANS = (("refine_semantic", "couple"), ("couple", "refine_image"),
         ("couple", "refine_text"), ("refine_image", "refine_text"))
CALLS = {"encoder": 1, "gate": 1, "initial_transitions": 2, "suffix_transitions": 3,
         "decoder": 1, "emitted_modalities": 2, "audit_observer": 0, "forecast": 0, "search": 0}


def validate_run(directory, data, training, plan, replay=False):
    if plan["common_inference_calls"] != CALLS:
        raise ValueError("registered equal-work inference call schedule changed")
    root = require_owner(plan, directory, "replay" if replay else "inference")
    bound = verify_seal(root, "run-seal.json")
    result, rows = read_json(root / "run.json"), read_json(root / "rows.json")["rows"]
    _, cases = validate_data(data, plan)
    models = {(r["seed"], r["arm"]): r for r in training["models"]}
    expected = {(seed, arm, case["case_id"]) for seed, arm in models for case in cases}
    rng, arms = np.random.default_rng(plan["arm_order_seed"]), list(plan["arms"])
    order = [(seed, arms[int(i)], case["case_id"]) for seed in plan["seeds"] for case in cases
             for i in rng.permutation(len(arms))]
    lookup, case_map = {}, {case["case_id"]: case for case in cases}
    if (result["protocol_canonical_sha256"] != digest(plan) or result["completed_rows"] != len(expected)
            or len(rows) != len(expected) or result["final_targets_opened"] is not False
            or result["data_receipt_sha256"] != file_hash(Path(data) / "data-receipt.json")
            or result["training_canonical_sha256"] != digest(training)
            or result["model_seal_sha256"] != file_hash(Path(plan["source_owner_directory"]) / "model-seal.json")
            or result["stage"] != ("replay" if replay else "inference")):
        raise ValueError("inference is incomplete or bound to different inputs")
    required = {"run.json", "rows.json", "states.npz", "source-freeze.json"}
    if replay:
        required.add("replay.json")
    for ordinal, row in enumerate(rows):
        key = row["seed"], row["arm"], row["case_id"]
        if key not in expected or key in lookup or row["row_index"] != ordinal or key != order[ordinal]:
            raise ValueError("unexpected, duplicate or missing inference row")
        model, case = models[key[:2]], case_map[key[2]]
        stem = f"outputs/seed{row['seed']}-{row['arm']}/{row['case_id']}"
        paths = {"image": stem + "/image.png", "text": stem + "/caption.txt"}
        choice = row["initial_plan_index"]
        if (any(row[name] != case[name] for name in ("split", "index", "corruption", "source_ids"))
                or row["checkpoint_file_sha256"] != model["checkpoint_file_sha256"]
                or row["snapshot_sha256"] != model["snapshot_sha256"]
                or row["noise_seed"] != row["seed"] * 10000 + case["index"]
                or type(choice) is not int or not 0 <= choice < len(PLANS)
                or row["initial_plan"] != list(PLANS[choice]) or row["fixed_suffix"] != plan["fixed_suffix"]
                or row["calls"] != CALLS or row["paths"] != paths or len(row["state_keys"]) != 4):
            raise ValueError("inference changed source, checkpoint, noise, work or actions")
        for kind, relative in paths.items():
            require_identity(root / relative, {"sha256": row["output_sha256"][kind]})
            required.add(relative)
        lookup[key] = row
    if set(lookup) != expected or set(bound["files"]) != required:
        raise ValueError("run seal omits a required output or includes unregistered artifacts")
    states = read_arrays(root / "states.npz", {"features"})["features"]
    if states.shape != (len(expected), 4, 384) or states.dtype != np.float32:
        raise ValueError("full latent-state replay evidence is incomplete")
    if replay:
        audit = read_json(root / "replay.json")
        if (audit["all_output_bytes_equal"] is not True or audit["all_state_tensors_equal"] is not True
                or audit["rows_replayed"] != len(expected) or audit["new_final_targets_opened"] is not False):
            raise ValueError("label-free replay did not cover every registered row")
    return result, rows, states


def compare_replay(original_rows, original_states, rows, states):
    if len(original_rows) != len(rows) or not np.array_equal(original_states, states):
        raise ValueError("full output replay changed row count or latent state tensors")
    for before, after in zip(original_rows, rows, strict=True):
        if digest({k: v for k, v in before.items() if k != "cost"}) != digest({k: v for k, v in after.items() if k != "cost"}):
            raise ValueError("replayed raw bytes, model/source binding or state/action trace differs")


def execute(data, training, protocol, source_commit, output, runs=None):
    sys.addaudithook(deny_final)
    began = clock()
    plan = read_json(protocol)
    if plan["common_inference_calls"] != CALLS:
        raise ValueError("registered equal-work inference call schedule changed")
    source = published_source(plan, source_commit, protocol)
    torch, environment = cpu_environment(plan)
    from ..data import Observation, render_tokens
    from ..observer import read_bundle, write_bundle
    from ..plan_training import ControlledSnapshot, PLANS as ORIGINAL_PLANS
    if tuple(tuple(p) for p in ORIGINAL_PLANS) != PLANS:
        raise ValueError("registered finite plan library differs from original implementation")
    training_root = require_owner(plan, training, "training")
    root = require_owner(plan, output, "replay" if runs is not None else "inference")
    root.mkdir(parents=True, exist_ok=False)
    write(root / "source-freeze.json", source)
    verify_model_seal(plan)
    fitted = verify_training(training_root, plan)
    receipt, cases, values = public_observations(data, plan)
    if (environment != receipt["environment"] or environment != fitted["environment"]
            or fitted["data_receipt_sha256"] != file_hash(Path(data) / "data-receipt.json")):
        raise ValueError("actual numerical environment changed before inference")
    old_result = old_rows = old_states = None
    if runs is not None:
        old_result, old_rows, old_states = validate_run(runs, data, fitted, plan)
        if old_result["environment"] != environment:
            raise ValueError("replay numerical environment differs")
    model_rows = {(r["seed"], r["arm"]): r for r in fitted["models"]}
    snapshots = {key: ControlledSnapshot.load(training_root / row["path"],
                 expected_file_sha256=row["checkpoint_file_sha256"]) for key, row in model_rows.items()}
    if any(snapshot.verify_integrity() != model_rows[key]["snapshot_sha256"] for key, snapshot in snapshots.items()):
        raise ValueError("loaded model differs from the complete pre-inference seal")
    observations = [Observation(*(torch.from_numpy(values[name][i:i + 1].copy())
                                 for name in ("pixels", "masks", "tokens"))) for i in range(len(cases))]
    rows, features = [], []
    rng = np.random.default_rng(plan["arm_order_seed"])
    arms = list(plan["arms"])
    with torch.inference_mode():
        for seed in plan["seeds"]:
            for case, observation in zip(cases, observations, strict=True):
                for index in rng.permutation(len(arms)):
                    arm = arms[int(index)]
                    model, snapshot = model_rows[seed, arm], snapshots[seed, arm]
                    started = clock()
                    noise_seed = seed * 10000 + case["index"]
                    state = snapshot.encode(observation, noise_seed=noise_seed, content_control=True)
                    choice = int(state.plan_indices[0])
                    state_keys = [snapshot.state_key(state)]
                    state_features = [snapshot.state_features(state).numpy().copy()[0]]
                    for action in plan["fixed_suffix"]:
                        state = snapshot.step(state, action)
                        state_keys.append(snapshot.state_key(state))
                        state_features.append(snapshot.state_features(state).numpy().copy()[0])
                    output_tensor = snapshot.decode(state)
                    caption = render_tokens(output_tensor.token_ids[0])
                    pixels = output_tensor.image_logits.sigmoid()[0]
                    paths = write_bundle(root / "outputs" / f"seed{seed}-{arm}" / case["case_id"], caption, pixels)
                    _, reopened_caption, hashes = read_bundle(paths)
                    if reopened_caption != caption or snapshot.verify_integrity() != model["snapshot_sha256"]:
                        raise ValueError("emitted caption or frozen checkpoint changed")
                    features.append(np.stack(state_features))
                    rows.append({"row_index": len(rows), "seed": seed, "arm": arm, **case,
                                 "checkpoint_file_sha256": model["checkpoint_file_sha256"],
                                 "snapshot_sha256": model["snapshot_sha256"], "noise_seed": noise_seed,
                                 "initial_plan_index": choice, "initial_plan": list(PLANS[choice]),
                                 "fixed_suffix": plan["fixed_suffix"], "state_keys": state_keys,
                                 "token_ids": output_tensor.token_ids[0].tolist(),
                                 "paths": {kind: str(Path(path).relative_to(root)) for kind, path in paths.items()},
                                 "output_sha256": hashes, "calls": CALLS, "cost": cost(started)})
                if len(rows) % 120 == 0:
                    print(json.dumps({"stage": "replay" if runs else "inference", "rows_completed": len(rows)}), flush=True)
    states = np.stack(features)
    if runs is not None:
        compare_replay(old_rows, old_states, rows, states)
        write(root / "replay.json", {"schema": "hepta.ndu-fresh-factorial.replay.v1",
              "original_run_seal_sha256": file_hash(Path(runs) / "run-seal.json"),
              "rows_replayed": len(rows), "all_output_bytes_equal": True, "all_state_tensors_equal": True,
              "new_final_targets_opened": False,
              "scope": "separate-process reexecution of every row with the newly sealed model; not an independent model implementation"})
    if source_hashes(plan) != source["files"]:
        raise ValueError("source changed during inference")
    verify_training(training_root, plan)
    validate_data(data, plan)
    write(root / "rows.json", {"rows": rows})
    arrays(root / "states.npz", features=states)
    result = {"schema": "hepta.ndu-fresh-factorial.inference.v1", "stage": "replay" if runs else "inference",
              "protocol_canonical_sha256": digest(plan), "data_receipt_sha256": file_hash(Path(data) / "data-receipt.json"),
              "training_canonical_sha256": digest(fitted), "training_seal_sha256": file_hash(training_root / "training-seal.json"),
              "model_seal_sha256": file_hash(root.parent / "model-seal.json"),
              "completed_rows": len(rows), "environment": environment, "cost": cost(began),
              "total_calls": {key: value * len(rows) for key, value in CALLS.items()},
              "final_targets_opened": False, "authority": "DENY_ALL", "production_authority": False}
    write(root / "run.json", result)
    seal_hash = seal(root, "run-seal.json")
    validate_run(root, data, fitted, plan, replay=runs is not None)
    return {"rows_completed": len(rows), "run_seal_sha256": seal_hash, "cost": result["cost"], "final_targets_opened": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "training", "protocol", "source-commit", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--runs")
    print(json.dumps(run_stage(execute, vars(parser.parse_args())), sort_keys=True))
