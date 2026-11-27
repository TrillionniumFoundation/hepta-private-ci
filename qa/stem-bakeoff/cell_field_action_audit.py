"""Independent V3 candidate freeze, convex plans and actual Adam branch audit."""

import argparse
from collections import Counter, defaultdict
import itertools
import json
import os
from pathlib import Path
import sys

import numpy as np

from cell_field_action_math_audit import audit_plan, common_scores
from cell_field_action_replay_audit import audit_replays
from cell_field_audit import (_checkpoint_vector, _load_arrays, _probability_and_gradient,
                              canonical, sha, verify_seal)
from cell_field_retention_audit import adam_transition


def array_sha(value):
    value = np.ascontiguousarray(value)
    return sha(canonical([value.dtype.str, list(value.shape)]) + value.tobytes())


def checkpoint(root, path):
    vector, manifest = _checkpoint_vector(root / path)
    excluded = {"state_sha256", "payload_sha256", "tensor_sha256", "retained_tensor_bytes", "authority"}
    metadata = {key: value for key, value in manifest.items() if key not in excluded}
    arrays = _load_arrays(root / path / "state.npz")
    if ({key: array_sha(value) for key, value in arrays.items()} != manifest["tensor_sha256"]
            or sha(canonical(metadata) + bytes.fromhex(array_sha(vector))) != manifest["state_sha256"]
            or manifest["authority"] != "DENY_ALL" or manifest["sampler_draw_count"] != 0
            or manifest["external_batch_count"] != 0):
        raise ValueError("complete checkpoint digest, tensor identity or full-batch state differs")
    return vector, manifest, metadata


def audit_runs(run_dir, data_dir, protocol_path):
    root, data = Path(run_dir), Path(data_dir)
    seal = verify_seal(root)
    runs = json.loads((root / "runs.json").read_bytes())
    plan_bytes = Path(protocol_path).read_bytes()
    plan = json.loads(plan_bytes)
    frozen_bytes = (root / "candidate_freeze.json").read_bytes()
    frozen = json.loads(frozen_bytes)
    receipt_bytes = (data / "data_receipt.json").read_bytes()
    receipt = json.loads(receipt_bytes)
    label_bytes = (data / "train_labels.json").read_bytes()
    if (sha(plan_bytes) != seal["protocol_sha256"] or runs["protocol_sha256"] != seal["protocol_sha256"]
            or sha(receipt_bytes) != runs["data_receipt_sha256"]
            or sha(label_bytes) != receipt["files"]["train_labels.json"]["sha256"]
            or seal["validation_labels_opened"] is not False or runs["validation_labels_opened"] is not False
            or frozen["validation_labels_opened"] is not False or frozen["final_labels_opened"] is not False
            or frozen["candidate_branches_executed"] != 0 or frozen["record_count"] != 342
            or sha(frozen_bytes) != runs["candidate_freeze_sha256"]):
        raise ValueError("protocol, source, candidate freeze or label boundary differs")
    if not (seal["sourcecode_hashes"] == runs["sourcecode_hashes"] == frozen["sourcecode_hashes"]):
        raise ValueError("frozen execution source closure differs")
    for name, expected in seal["sourcecode_hashes"].items():
        if sha((root / "source" / name).read_bytes()) != expected:
            raise ValueError("frozen execution source copy differs")
    for name, expected in seal["sourcecode_hashes"].items():
        if Path(name).name != name or sha(Path(__file__).with_name(name).read_bytes()) != expected:
            raise ValueError("independent auditor changed after predictions were frozen")
    for name, item in frozen["files"].items():
        if seal["files"].get(name) != item:
            raise ValueError("a pre-branch frozen artifact was changed or removed")
    index = json.loads((root / "candidate_index.json").read_bytes())
    if index["initial_order"] != runs["initial_order"] or index["warmup_order"] != runs["warmup_order"]:
        raise ValueError("shared states changed after candidate freeze")
    expected = [(seed, head, anchor, "zero", 0, "zero") if method is None else
                (seed, head, anchor, method[1], method[2], method[0])
                for seed, head, anchor in itertools.product(plan["seeds"], plan["head_modes"], plan["anchor_offsets"])
                for method in [None, *itertools.product(plan["objectives"], plan["observations"], plan["lookaheads"])]]
    keys = [(r["seed"], r["head"], r["anchor_offset"], r["observation"], r["lookahead"], r["objective"])
            for r in runs["records"]]
    if keys != expected or len(keys) != 342 or len(index["records"]) != 342:
        raise ValueError("fixed candidate order or condition census differs")
    features = _load_arrays(root / "projected_features.npz")["features"]
    predictions = _load_arrays(root / "predictions.npz")
    wanted_shapes = {"terminal_probabilities": (342, 624, 4), "retention_probabilities": (342, 9, 128, 4),
                     "warmup_probabilities": (6, 624, 4), "initial_probabilities": (18, 624, 4)}
    if (features.shape != (624, 8) or set(predictions) != set(wanted_shapes)
            or any(predictions[name].shape != shape for name, shape in wanted_shapes.items())):
        raise ValueError("registered predictor or prediction array shape differs")
    for rows, names in ((runs["records"], ("terminal_probabilities", "retention_probabilities")),
                        (runs["warmup_order"], ("warmup_probabilities",)),
                        (runs["initial_order"], ("initial_probabilities",))):
        for i, record in enumerate(rows):
            for name in names:
                if record["status"] != "completed" and not np.isnan(predictions[name][i]).all():
                    raise ValueError("failed condition retained scored predictions")
    train = json.loads(label_bytes)["roles"]
    split = {role: (features[info["indices"]], np.asarray(info["labels"])) for role, info in train.items()}
    maxima, count = defaultdict(float), 0

    def close(name, actual, wanted, tolerance=3e-11):
        nonlocal count
        a, b = np.asarray(actual, dtype=float), np.asarray(wanted, dtype=float)
        if a.shape != b.shape or not np.isfinite(a).all() or not np.isfinite(b).all():
            raise ValueError("invalid independent comparison: " + name)
        error = float(np.max(np.abs(a - b))) if a.size else 0.0
        maxima[name] = max(error, maxima[name]); count += a.size
        if error > tolerance * (1 + (float(np.max(np.abs(b))) if b.size else 0.0)):
            raise ValueError("independent " + name + " differs: " + str(error))

    warm_states, anchors, models = {}, {}, {}
    for wi, warm in enumerate(runs["warmup_order"]):
        if warm["status"] != "completed": continue
        vector, manifest, metadata = checkpoint(root, warm["checkpoint_path"])
        p = len(vector) // 3
        if (manifest["step_count"] != plan["warmup_steps"] or manifest["active_context"] != "current_train"
                or any(manifest["protocol"][key] != value for key, value in plan["optimizer"].items())
                or manifest["bindings"]["executed_code_sha256"] != seal["sourcecode_hashes"]
                or manifest["bindings"]["protocol_sha256"] != seal["protocol_sha256"]
                or manifest["head"]["mode"] != warm["head"]
                or warm["state_sha256"] != manifest["state_sha256"]):
            raise ValueError("warmup protocol, source, head or complete state differs")
        close("warmup_probability", predictions["warmup_probabilities"][wi], _probability_and_gradient(vector[:p], warm["head"], features)[0])
        old_anchor = _probability_and_gradient(vector[:p], warm["head"], *split["old_probe"])[1]
        close("warmup_old_anchor", warm["old_probe_anchor"], old_anchor)
        name = f"seed{warm['seed']}-{warm['head']}"
        path = _load_arrays(root / f"warmup/{name}.npz")["states"]
        close("warmup_terminal", path[-1], vector, 0)
        initial_theta = np.r_[np.random.default_rng(warm["seed"]).normal(0, 0.01 / np.sqrt(features.shape[1]),
                              (features.shape[1], 4)).ravel(), np.zeros(p - features.shape[1] * 4)]
        close("warmup_initial", path[0], np.r_[initial_theta, np.zeros(2 * p)], 0)
        for k in range(plan["warmup_steps"]):
            close("warmup_adam", path[k + 1], adam_transition(path[k], warm["head"], *split["old_train"], k, plan["optimizer"]))
        baseline = _load_arrays(root / f"baseline/{name}.npz")["states"]
        close("baseline_initial", baseline[0], vector, 0)
        for k in range(len(baseline) - 1):
            close("baseline_adam", baseline[k + 1], adam_transition(baseline[k], warm["head"], *split["current_train"], plan["warmup_steps"] + k, plan["optimizer"]))
        warm_states[wi] = (vector, old_anchor, baseline)
    for ai, initial in enumerate(runs["initial_order"]):
        if initial["status"] != "completed": continue
        vector, manifest, metadata = checkpoint(root, initial["checkpoint_path"])
        p, H = len(vector) // 3, plan["evaluation_horizon"]
        old_anchor, baseline = warm_states[initial["warmup_index"]][1:]
        close("anchor_state", vector, baseline[initial["anchor_offset"]], 0)
        close("anchor_old_target", initial["old_probe_anchor"], old_anchor)
        if (manifest["step_count"] != plan["warmup_steps"] + initial["anchor_offset"]
                or manifest["state_sha256"] != initial["state_sha256"]):
            raise ValueError("anchor step changed")
        close("initial_probability", predictions["initial_probabilities"][ai], _probability_and_gradient(vector[:p], initial["head"], features)[0])
        ref = _load_arrays(root / initial["reference_path"])
        close("reference_initial", ref["reference_states"][0], vector, 0)
        for k in range(H):
            close("reference_adam", ref["reference_states"][k + 1], adam_transition(ref["reference_states"][k], initial["head"],
                *split["current_train"], manifest["step_count"] + k, plan["optimizer"]))
        for observation in ("loss2", "full"):
            model = _load_arrays(root / initial["model_paths"][observation])
            close("all_mask", model["B"], np.eye(p), 0)
            E = np.tile(np.vstack([plan["h"] * np.eye(p), np.zeros((2 * p, p))]) / ref["state_scales"][:, None], (H, 1, 1))
            close("physical_action_map", model["E"], E)
            C = np.tile(np.eye(3 * p), (H + 1, 1, 1)) if observation == "full" else ref["C_extended"][:, :2]
            F = ref["A"] if observation == "full" else np.array([C[k + 1] @ ref["A"][k] @ np.linalg.pinv(C[k], rcond=1e-10) for k in range(H)])
            D = E if observation == "full" else np.array([C[k + 1] @ E[k] for k in range(H)])
            charged = ref["C_extended"][:, :2] if observation == "full" else np.tile(np.eye(2), (H + 1, 1, 1))
            for name, wanted in (("Cobs", C), ("F", F), ("D", D), ("charged", charged)):
                close("model_" + name, model[name], wanted)
            impulse = np.zeros((H + 1, F.shape[1], p)); impulse[1] = D[0]
            for k in range(1, H): impulse[k + 1] = F[k] @ impulse[k]
            close("model_impulse", model["impulse_states"], impulse)
            close("model_loss_map", model["loss_maps"], np.einsum("kij,kjl->kil", charged, impulse))
            close("model_baseline", model["reference_observations"], ref["reference_observations"][:, :2], 0)
            models[(ai, observation)] = model
        anchors[ai] = (vector, manifest, metadata, ref, old_anchor)
    plan_census, gaps, margins = Counter(), [], []
    for number, (record, prior) in enumerate(zip(runs["records"], index["records"])):
        for key, value in prior.items():
            if key in {"status", "error", "paths"}: continue
            if record.get(key) != value: raise ValueError("candidate field changed after all-plan freeze: " + key)
        for key, value in prior["paths"].items():
            if record["paths"].get(key) != value: raise ValueError("candidate artifact identity changed")
        if prior["status"] != "planned" and record["status"] != prior["status"]:
            raise ValueError("unqualified candidate acquired an executed disposition")
        if prior["status"] == "planned" and record["status"] not in {"completed", "execution_failure"}:
            raise ValueError("qualified candidate silently disappeared")
        if record["status"] == "initial_failure": continue
        ai, paths = record["initial_index"], record["paths"]
        vector, manifest, metadata, ref, old_anchor = anchors[ai]
        p, H = len(vector) // 3, plan["evaluation_horizon"]
        if not all((root / paths[key]).exists() for key in ("candidate", "candidate_record")):
            if record["status"] != "solver_failure" or "error" not in record: raise ValueError("candidate evidence absent")
            plan_census["planning_exception"] += 1
            continue
        arrays = _load_arrays(root / paths["candidate"])
        saved = json.loads((root / paths["candidate_record"]).read_bytes())
        if (record["solver_status"] != saved["status"] or record["solver_record"] != saved["record"]
                or record["initial_state_sha256"] != manifest["state_sha256"]):
            raise ValueError("candidate record or common-state binding differs")
        if record["method_id"] != "zero":
            certificate = audit_plan(arrays, saved, models[(ai, record["observation"])], record, old_anchor, plan, close)
            plan_census[certificate["kind"]] += 1
            if "gap" in certificate: gaps.append(certificate["gap"])
            if "witness_margin" in certificate: margins.append(certificate["witness_margin"])
            if certificate["kind"] != "qualified" and record["status"] != certificate["kind"]:
                raise ValueError("solver proof and branch disposition differ")
        else:
            close("zero_action", arrays["u"], np.zeros(p), 0); plan_census["fixed_zero"] += 1
        if prior["status"] != "planned": continue
        actions = arrays["actions"]
        if actions.shape != (H, p): raise ValueError("fixed action sequence shape differs")
        close("one_impulse", actions[1:], np.zeros((H - 1, p)), 0)
        close("first_action", actions[0], arrays["u"], 0)
        if np.max(np.abs(arrays["u"])) > plan["action_bound"] / np.sqrt(p): raise ValueError("physical budget exceeded")
        for obs in ("loss2", "full"):
            fields = np.einsum("kij,j->ki", models[(ai, obs)]["loss_maps"], arrays["u"])
            close("same_action_" + obs, arrays["predicted_" + obs + "_fields"], fields)
            for key, value in common_scores(fields, actions, ref["reference_observations"][:, :2], old_anchor, plan).items():
                close("predicted_" + key, record["predicted_scores"][obs][key], value)
        if record["status"] != "completed": continue
        trajectory = _load_arrays(root / paths["trajectory"])
        final, final_manifest, _ = checkpoint(root, paths["checkpoint"])
        if (trajectory["states"].shape != (H + 1, 3 * p) or trajectory["observations"].shape != (H + 1, 4)
                or trajectory["fields"].shape != (H + 1, 2)):
            raise ValueError("complete branch trajectory shape differs")
        close("branch_initial_state", trajectory["states"][0], vector, 0)
        close("branch_final_state", trajectory["states"][-1], final, 0)
        close("branch_actions", trajectory["actions"], actions, 0)
        if final_manifest["step_count"] != manifest["step_count"] + H or final_manifest["state_sha256"] != record["final_state_sha256"]:
            raise ValueError("terminal checkpoint state identity differs")
        receipts = json.loads((root / paths["receipts"]).read_bytes())
        if len(receipts) != H: raise ValueError("transition receipt census differs")
        for k, state in enumerate(trajectory["states"]):
            obs, interactions = [], []
            for role in ("current_probe", "old_probe"):
                _, loss, gradient = _probability_and_gradient(state[:p], record["head"], *split[role])
                obs.append(loss); interactions.append(float(gradient @ state[p:2*p]))
            close("actual_probe_observation", trajectory["observations"][k], obs + interactions)
            probability = _probability_and_gradient(state[:p], record["head"], features)[0]
            close("retention_probability", predictions["retention_probabilities"][number, k], probability[runs["retention_indices"]])
            if k == H: close("terminal_probability", predictions["terminal_probabilities"][number], probability)
            if k < H:
                successor = adam_transition(state, record["head"], *split["current_train"], manifest["step_count"] + k, plan["optimizer"])
                successor[:p] += plan["h"] * actions[k]
                close("actual_adam", trajectory["states"][k + 1], successor)
                before = sha(canonical({**metadata, "step_count": manifest["step_count"] + k}) + bytes.fromhex(array_sha(state)))
                after = sha(canonical({**metadata, "step_count": manifest["step_count"] + k + 1}) + bytes.fromhex(array_sha(trajectory["states"][k + 1])))
                receipt = receipts[k]
                if (receipt["previous_state_sha256"] != before or receipt["state_sha256"] != after
                        or receipt["step"] != manifest["step_count"] + k + 1 or receipt["mark_origin"] != "full_batch"
                        or receipt["context"] != metadata["active_context"] or receipt["authority"] != "DENY_ALL"
                        or receipt["dataset_sha256"] != metadata["contexts"][metadata["active_context"]]
                        or receipt["marks"] != list(range(len(split["current_train"][1])))
                        or receipt["intervention_sha256"] != array_sha(plan["h"] * actions[k])
                        or receipt["mask_sha256"] != array_sha(np.ones(p, dtype=bool))):
                    raise ValueError("complete transition receipt differs")
                close("intervention_l2", receipt["intervention_l2"], np.linalg.norm(plan["h"] * actions[k]))
                close("parameter_update_l2", receipt["parameter_update_l2"], np.linalg.norm(trajectory["states"][k + 1, :p] - state[:p]))
        close("actual_fields", trajectory["fields"], trajectory["observations"][:, :2] - ref["reference_observations"][:, :2])
        for key, value in common_scores(trajectory["fields"], actions, ref["reference_observations"][:, :2], old_anchor, plan).items():
            close("actual_" + key, record["actual_scores"][key], value)
        close("physical_effort", record["physical_intervention_squared_norm"], np.square(plan["h"] * actions).sum())
    replay = audit_replays(root, runs, plan)
    return {"schema": "hepta.cell-action-independent-run-audit.v3", "registered_records": 342,
            "replays": replay, "all_registered_replays_passed": replay["all_registered_replays_passed"],
            "status_census": dict(Counter(r["status"] for r in runs["records"])), "plan_census": dict(plan_census),
            "sealed_files_verified": len(seal["files"]), "frozen_candidate_files_verified": len(frozen["files"]),
            "scalar_equalities_checked": int(count), "maximum_absolute_errors": dict(maxima),
            "largest_recomputed_gap_bound": max(gaps) if gaps else None,
            "smallest_infeasibility_witness_margin": min(margins) if margins else None,
            "pre_evaluation_seal_sha256": sha((root / "pre_evaluation_seal.json").read_bytes()),
            "candidate_freeze_sha256": sha(frozen_bytes), "auditor_sha256": sha(Path(__file__).read_bytes()),
            "solver_imported": False, "training_state_imported": False,
            "validation_labels_opened": False, "final_labels_opened": False,
            "scope": "declared tangent arithmetic and actual finite Adam paths; no nonlinear global or population guarantee"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("runs", "data", "protocol", "output"): parser.add_argument("--" + name, required=True)
    parser.add_argument("--evaluation")
    args = parser.parse_args()
    if args.evaluation:
        from cell_field_action_score_audit import audit_evaluation
        result = audit_evaluation(args.runs, args.data, args.protocol, args.evaluation)
    else:
        def deny(event, arguments):
            if event == "open" and arguments and isinstance(arguments[0], (str, bytes, os.PathLike)):
                if Path(os.fsdecode(arguments[0])).name in {"validation_labels.json", "final_labels.json"}:
                    raise PermissionError("pre-evaluation auditor cannot open withheld payloads")
        sys.addaudithook(deny)
        result = audit_runs(args.runs, args.data, args.protocol)
    Path(args.output).write_bytes(canonical(result) + b"\n")
    print(json.dumps(result, indent=2))
