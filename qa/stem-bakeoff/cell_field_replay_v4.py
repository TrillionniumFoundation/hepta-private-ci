"""Independent, label-denied replay of a completed and sealed V4 census.

This audit checks execution integrity, not scientific acceptance or promotion.
It imports the recorded implementation but never regenerates its historical
source inventory, and writes no files beneath the sealed run directory.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

import numpy as np

from cell_field_action_control import plan_action
from cell_field_action_io import deny_withheld_labels
from cell_field_dynamics_v4 import MODEL_NAMES
from cell_field_evaluate_v4 import verify_pre_label_seal
from cell_field_experiments_v4 import prepare
from cell_field_features import file_hash
from cell_field_fixed_actions import fixed_library
from cell_field_state import CellTrainingState, DEFAULT_PROTOCOL, dataset_digest
from cell_learning_models import NumpyCellHead, canonical, normalize_features


TRAIN_ROLES = ("old_train", "old_probe", "current_train", "current_probe")
CANDIDATE = "structured4_h8"
PLAN_TOLERANCE = 1e-12


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _read(path):
    return json.loads(Path(path).read_bytes())


def _arrays(path):
    with np.load(path, allow_pickle=False) as archive:
        arrays = {name: archive[name] for name in archive.files}
    _require(all(np.isfinite(value).all() for value in arrays.values()),
             "nonfinite stored array: " + str(path))
    return arrays


def _exact(actual, expected, label):
    _require(np.shape(actual) == np.shape(expected) and np.array_equal(actual, expected),
             "exact replay mismatch: " + label)


def _close(actual, expected, label):
    _require(np.shape(actual) == np.shape(expected), "shape mismatch: " + label)
    error = float(np.max(np.abs(np.asarray(actual) - np.asarray(expected)), initial=0.0))
    _require(np.isfinite(error) and error <= PLAN_TOLERANCE,
             f"plan mismatch ({error:.17g}): {label}")
    return error


def _task_inputs(root, task, plan):
    directory = root / task
    inputs = _read(directory / "inputs.json")
    arrays = _arrays(directory / "training.npz")
    _require(set(arrays) == {role + suffix for role in TRAIN_ROLES for suffix in ("_x", "_y")},
             "only training and controller-probe labels are permitted")
    split = {role: (arrays[role + "_x"], arrays[role + "_y"]) for role in TRAIN_ROLES}
    projected = _arrays(directory / "projected.npz")["features"]
    sources = inputs["sources"]
    _require(len(sources) == len(projected) == sum(plan["source_counts"][task].values()),
             "task row census changed")
    _require([row["index"] for row in sources] == list(range(len(projected))),
             "source row order changed")
    for role, (x, y) in split.items():
        indices = [row["index"] for row in sources if row["role"] == role]
        _require(len(indices) == plan["source_counts"][task][role] and y.shape == (len(indices),)
                 and y.dtype.kind in "iu", "training role or label shape changed")
        _exact(x, projected[indices], task + "/" + role + " source-feature order")
    contexts = {role: dataset_digest(*split[role]) for role in ("old_train", "current_train")}
    return inputs, split, projected, contexts


def _warmup(directory, task, seed, head, inputs, split, projected, contexts, plan, hashes, protocol_sha):
    bindings = {"protocol_sha256": protocol_sha, "task": task, "seed": seed,
        "head_mode": head, "feature_identity": inputs["feature_report"]["feature_identity"],
        "sources_sha256": inputs["input_hashes"]["sources.json"], "executed_code_sha256": hashes}
    expected = {"expected_bindings": bindings, "expected_protocol": plan["optimizer"],
                "expected_contexts": contexts}
    manifests = list(directory.rglob("manifest.json"))
    for path in manifests:
        manifest = _read(path)
        _require(manifest["bindings"] == bindings and manifest["contexts"] == contexts
                 and manifest["protocol"] == {**DEFAULT_PROTOCOL, **plan["optimizer"]}
                 and manifest["authority"] == "DENY_ALL", "checkpoint scenario binding: " + str(path))
    warm = _read(directory / "warmup/result.json")
    _require(warm["status"] == "completed", "warmup unavailable")
    state = CellTrainingState.load(directory / "warmup/checkpoint", **expected,
                                  expected_state_digest=warm["state_sha256"])
    history = _arrays(directory / "warmup/warmup.npz")
    receipts = _read(directory / "warmup/receipts.json")
    _require(len(history["states"]) == plan["warmup_steps"] + 1
             and len(receipts) == plan["warmup_steps"], "warmup sequence length changed")
    replay = CellTrainingState(NumpyCellHead(8, 4, head, seed=seed), bindings=bindings,
        protocol=plan["optimizer"], seed=seed, contexts=contexts, active_context="old_train")
    _exact(replay.vector(), history["states"][0], "seed initialization")
    for k in range(plan["warmup_steps"]):
        receipt = replay.advance(*split["old_train"])
        _require(receipt == receipts[k], "warmup transition receipt changed")
        _exact(replay.vector(), history["states"][k+1], "warmup trajectory")
    replay.select_context("current_train")
    _require(replay.digest() == state.digest(), "seed-to-warmup complete state differs")
    _exact(replay.head.predict_proba(projected), history["probabilities"], "warmup probabilities")
    old_x, old_y = split["old_probe"]
    anchor = float(replay.head.loss_gradients(normalize_features(old_x), old_y, 0.0)[0])
    _require(anchor == warm["old_anchor"], "warmup retention anchor differs")
    return state, warm, expected, len(manifests)


def _fixed_anchor(directory, baseline, expected, split, plan, old_anchor):
    frozen = _read(directory / "frozen_plan.json")
    checkpoint = CellTrainingState.load(directory / "initial", **expected,
                                       expected_state_digest=baseline.digest())
    _require(checkpoint.digest() == frozen["initial_state_sha256"]
             and frozen["old_anchor"] == old_anchor, "fixed checkpoint identity differs")
    library = fixed_library(checkpoint.parameter_count)
    names, actions = [name for name, _ in library], np.asarray([u for _, u in library])
    _require(frozen["actions"] == names and frozen["models"] == list(MODEL_NAMES)
             and frozen["frozen_predictions_sha256"] == file_hash(directory / "frozen_predictions.npz"),
             "fixed action/prediction commitment differs")
    prediction = _arrays(directory / "frozen_predictions.npz")
    actual = _arrays(directory / "actual_trajectories.npz")
    reference = _arrays(directory / "reference.npz")
    rows = _read(directory / "branches.json")
    _require(len(rows) == 49 and [row["action_id"] for row in rows] == names
             and all(row["status"] == "completed" for row in rows), "fixed branch census incomplete")
    _exact(prediction["actions"], actions, "registered SHA256 sign library")
    _exact(np.asarray([row["u"] for row in rows]), actions, "executed registered actions")
    p, h = checkpoint.parameter_count, plan["evaluation_horizon"]
    maps, predictions = prediction["loss_maps"], prediction["predictions"]
    _require(maps.shape == (5, h+1, 2, p) and predictions.shape == (5, 49, h+1, 2)
             and actual["states"].shape == (49, h+1, 3*p)
             and actual["observations"].shape == (49, h+1, 2), "fixed trajectory shape differs")
    _exact(maps[:, 0], np.zeros_like(maps[:, 0]), "initial tangent displacement")
    _exact(predictions[:, 0], np.zeros_like(predictions[:, 0]), "zero-action tangent path")
    algebra_error = _close(predictions, np.asarray([
        np.einsum("kij,aj->aki", item, actions) for item in maps]), "frozen action-map application")
    _exact(actual["states"][:, 0], np.tile(checkpoint.vector(), (49, 1)), "common branch start")
    _exact(reference["reference_states"][0], checkpoint.vector(), "reference start")
    # Complete tangent propagation independently reconstructed from the sealed A,C,scales.
    impulse = np.vstack((plan["h"] * np.eye(p), np.zeros((2*p, p))))
    impulse /= reference["state_scales"][:, None]
    state_maps = np.zeros((h+1, 3*p, p))
    for k in range(h):
        state_maps[k+1] = reference["A"][k] @ state_maps[k]
        if k == 0:
            state_maps[k+1] += impulse
    full = np.einsum("kij,kjl->kil", reference["C_extended"][:, :2], state_maps)
    full_error = _close(maps[-1], full, "complete optimizer tangent propagation")
    first_error = max(_close(item[1], full[1], "same first-step tangent") for item in maps)
    # Nonlinear first-step equality is in state space; finite loss changes need not equal a tangent.
    first_states = np.tile(reference["reference_states"][1], (49, 1))
    first_states[:, :p] += plan["h"] * actions
    _exact(actual["states"][:, 1], first_states, "post-Adam impulse and untouched moments")
    _exact(actual["states"][0], reference["reference_states"], "unforced zero branch states")
    _exact(actual["observations"][0], reference["reference_observations"][:, :2],
           "unforced zero branch observations")
    _exact(actual["real_delta"], actual["observations"] - reference["reference_observations"][:, :2],
           "measured loss deviations")
    probes = [(normalize_features(split[role][0]), split[role][1])
              for role in ("current_probe", "old_probe")]
    for index, row in enumerate(rows):
        replay = checkpoint.clone()
        for k in range(h+1):
            _exact(replay.vector(), actual["states"][index, k], "fixed nonlinear H8 state replay")
            losses = np.asarray([replay.head.loss_gradients(x, y, 0.0)[0] for x, y in probes])
            _exact(losses, actual["observations"][index, k], "fixed nonlinear H8 loss replay")
            if k < h:
                u = actions[index] if k == 0 else np.zeros(p)
                replay.advance(*split["current_train"], intervention=plan["h"] * u)
        _require(replay.digest() == row["final_state_sha256"], "fixed terminal state commitment differs")
    return {"path": str(directory.name), "branches": 49, "status": "passed",
            "map_application_max_abs": algebra_error, "full_tangent_max_abs": full_error,
            "first_step_tangent_max_abs": first_error, "zero_branch_exact": True,
            "first_step_nonlinear_state_exact": True, "nonlinear_h8_states_and_losses_exact": True,
            "replayed_optimizer_steps": 49*h,
            "tangent_scope": "algebra from sealed A/C/scales; no independent derivative reconstruction"}


def _mpc_replay(directory, warmup, expected, split, projected, plan, old_anchor):
    result = _read(directory / "result.json")
    _require(result["policy"] == CANDIDATE and result["status"] == "completed"
             and result["completed_steps"] == result["registered_steps"] == 8,
             "registered MPC candidate did not complete")
    trajectory = _arrays(directory / "trajectory.npz")
    receipts = _read(directory / "receipts.json")
    actions, states = trajectory["actions"], trajectory["states"]
    _require(actions.shape == (8, warmup.parameter_count) and states.shape == (9, len(warmup.vector()))
             and trajectory["probabilities"].shape == (9, len(projected), 4) and len(receipts) == 8,
             "MPC trajectory shape differs")
    _require(np.all(np.abs(actions) <= plan["mpc"]["action_bound"] / np.sqrt(warmup.parameter_count)),
             "MPC action budget changed")
    initial = CellTrainingState.load(directory / "initial", **expected,
                                    expected_state_digest=warmup.digest())
    _require(initial.digest() == result["initial_state_sha256"], "MPC initial state differs")
    frozen_plans = []
    for k in range(8):
        record = _read(directory / f"plans/{k}.json")
        frozen = _arrays(directory / f"plans/{k}.npz")
        _require(record["plan_sha256"] == file_hash(directory / f"plans/{k}.npz")
                 and record["solver"]["status"] == "qualified"
                 and record["initial_state_sha256"] == receipts[k]["previous_state_sha256"],
                 "frozen plan/receipt binding differs")
        _exact(frozen["u"], actions[k], "saved causal action")
        frozen_plans.append((record, frozen))
    _exact(initial.vector(), states[0], "MPC initial vector")
    _exact(initial.head.predict_proba(projected), trajectory["probabilities"][0], "MPC initial probabilities")
    for k in range(4):
        receipt = initial.advance(*split["current_train"], intervention=plan["h"] * actions[k])
        _require(receipt == receipts[k], "MPC prefix receipt differs")
        _exact(initial.vector(), states[k+1], "MPC prefix state")
        _exact(initial.head.predict_proba(projected), trajectory["probabilities"][k+1], "MPC prefix probabilities")
    restored = CellTrainingState.load(directory / "midpoint", **expected,
                                     expected_state_digest=initial.digest())
    _require(restored.digest() == frozen_plans[4][0]["initial_state_sha256"], "midpoint plan state differs")
    midpoint_digest = restored.digest()
    reference, models, _ = prepare(restored, split, plan, names=("structured4",), horizon=8)
    model = {**models["structured4"], "reference_observations": reference.observations[:, :2]}
    solved = plan_action(model, objective="direct_soft", lookahead=8, old_anchor=old_anchor,
        dt=plan["h"], effort_price=plan["effort_price"], action_bound=plan["mpc"]["action_bound"])
    _require(solved["status"] == "qualified" and restored.digest() == midpoint_digest,
             "midpoint planning failed or changed the complete state")
    maps_error = _close(model["loss_maps"], frozen_plans[4][1]["loss_maps"], "causal midpoint loss maps")
    action_error = _close(solved["u"], actions[4], "causal midpoint next action")
    for k in range(4, 8):
        receipt = restored.advance(*split["current_train"], intervention=plan["h"] * actions[k])
        _require(receipt == receipts[k], "restored MPC suffix receipt differs")
        _exact(restored.vector(), states[k+1], "restored MPC suffix state")
        _exact(restored.head.predict_proba(projected), trajectory["probabilities"][k+1],
               "restored MPC suffix probabilities")
    terminal = CellTrainingState.load(directory / "terminal", **expected,
                                     expected_state_digest=result["terminal_state_sha256"])
    _require(restored.digest() == terminal.digest(), "complete terminal state digest differs")
    _exact(restored.head.predict_proba(projected), trajectory["terminal_probabilities"], "terminal probabilities")
    return {"status": "passed", "midpoint_state_sha256": midpoint_digest,
            "terminal_state_sha256": restored.digest(), "replayed_suffix_steps": 4,
            "midpoint_maps_max_abs": maps_error, "midpoint_action_max_abs": action_error,
            "state_receipts_and_probabilities_exact": True}


def audit(run_directory, output, expected_protocol_sha256):
    root, target = Path(run_directory).resolve(), Path(output).resolve()
    _require(not target.is_relative_to(root) and not target.exists(),
             "new audit output must be outside the sealed run")
    # This is a process-local access boundary, not an OS isolation claim.
    sys.addaudithook(deny_withheld_labels)
    denied = []
    for name in ("validation_labels.json", "final_labels.json"):
        try:
            (root / name).open("rb").close()
        except PermissionError:
            denied.append(name)
    _require(len(denied) == 2, "withheld-label audit hook is not active")
    began = time.perf_counter_ns()
    report = {"schema": "hepta.cell-field-independent-replay.v4", "status": "failed",
        "run": str(root), "expected_protocol_sha256": expected_protocol_sha256,
        "auditor_sha256": file_hash(__file__), "withheld_label_paths_denied": denied,
        "authority": "DENY_ALL", "production_authority": False, "fits": [], "failures": [],
        "plan_absolute_tolerance": PLAN_TOLERANCE,
        "scope": "sealed local execution replay; no scientific gate, independent attestation, or promotion"}
    try:
        _require(file_hash(root / "protocol.json") == expected_protocol_sha256, "pinned protocol differs")
        seal = verify_pre_label_seal(root, root / "protocol.json")
        _require(seal.get("validation_labels_opened") is False, "validation access disposition differs")
        summary, plan, hashes = (_read(root / name) for name in
                                ("run.json", "protocol.json", "executed_source.json"))
        _require(summary.get("completed_at") and summary["registered_fits"] == 12
                 and len(summary["fits"]) == 12, "run has not completed its registered fit census")
        expected_fits = [(task, seed, head) for task in plan["tasks"]
                         for seed in plan["seeds"] for head in plan["head_modes"]]
        _require([(f["task"], f["seed"], f["head"]) for f in summary["fits"]] == expected_fits,
                 "fit identities or registered order changed")
        source_root = Path(__file__).parent
        required_sources = {"cell_field_state.py", "cell_learning_models.py", "cell_field_control.py",
            "cell_field_dynamics_v4.py", "cell_field_experiments_v4.py", "cell_field_mpc_v4.py",
            "cell_field_joint_run_v4.py", "cell_field_action_control.py", "cell_field_fixed_actions.py",
            "cell_field_action_io.py", "cell_field_action_run.py", "cell_field_io_v4.py"}
        _require(isinstance(hashes, dict) and required_sources <= set(hashes),
                 "recorded source inventory omits a required execution module")
        for name, digest in hashes.items():
            _require(Path(name).name == name and not (source_root / name).is_symlink()
                     and file_hash(source_root / name) == digest, "executed source closure differs: " + name)
        report.update(source_files_verified=len(hashes), sealed_files_verified=len(seal["files"]),
                      seal_sha256=file_hash(root / "pre_evaluation_seal.json"),
                      executed_source_sha256=file_hash(root / "executed_source.json"))
        task_inputs = {task: _task_inputs(root, task, plan) for task in plan["tasks"]}
        for task, seed, head in expected_fits:
            fit_id = f"{task}-seed{seed}-{head}"
            row = {"fit_id": fit_id, "status": "failed", "fixed": []}
            report["fits"].append(row)
            try:
                directory = root / task / f"seed{seed}-{head}"
                inputs, split, projected, contexts = task_inputs[task]
                warmup, warm, expected, manifests = _warmup(directory, task, seed, head, inputs,
                    split, projected, contexts, plan, hashes, expected_protocol_sha256)
                row["checkpoint_bindings_verified"] = manifests
                baseline, offset = warmup.clone(), 0
                for anchor in plan["anchor_offsets"]:
                    while offset < anchor:
                        baseline.advance(*split["current_train"])
                        offset += 1
                    row["fixed"].append(_fixed_anchor(directory / f"fixed/anchor{anchor}",
                        baseline, expected, split, plan, warm["old_anchor"]))
                row["mpc"] = _mpc_replay(directory / "mpc" / CANDIDATE, warmup, expected,
                                         split, projected, plan, warm["old_anchor"])
                row["status"] = "passed"
            except Exception as exc:
                report["failures"].append({"fit_id": fit_id, "type": type(exc).__name__, "message": str(exc)})
        # The inventory is checked again after replay; audit writes only its external report.
        verify_pre_label_seal(root, root / "protocol.json")
        report["run_unchanged_after_replay"] = True
        report["status"] = "passed" if not report["failures"] else "failed"
    except Exception as exc:
        report["failures"].append({"type": type(exc).__name__, "message": str(exc)})
    report.update(completed_at=datetime.now(timezone.utc).isoformat(), wall_ns=time.perf_counter_ns()-began)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(canonical(report) + b"\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-directory", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-protocol-sha256", required=True)
    result = audit(**vars(parser.parse_args()))
    print(json.dumps({"status": result["status"], "fits": len(result["fits"]),
                      "failures": result["failures"]}), flush=True)
    sys.exit(0 if result["status"] == "passed" else 1)
