"""Causal actual-neural execution; evaluator labels enter only after emission."""

from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import time
import traceback

import numpy as np

from allocation_control import PLANS
from allocation_model import ACTIONS, REFINE_COST, tensor_hash, joint_hash
from feedback_model import weight_hashes
from metrics import score_outputs
from model import MODALITIES, encode
from world import _render_modality


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def prepare_worlds(seed, replicates):
    """Declared balanced input/environment metadata, never passed to a policy."""
    if type(seed) is not int or type(replicates) is not int or replicates not in (2, 32):
        raise ValueError("registered development or confirmation world count required")
    rows, modes, reps, labels = [], [], [], []
    for condition in range(8):
        for mode in range(4):
            for rep in range(replicates):
                rng = np.random.default_rng(np.random.SeedSequence([5100000, seed, condition, mode, rep]))
                rows.append(_render_modality(np.array([condition]), "text", rng, True)[0])
                modes.append(mode)
                reps.append(rep)
                labels.append(condition)
    return {"raw_text": np.asarray(rows, dtype=np.float32), "truth": np.array(labels, dtype=np.int64),
            "initial_mode": np.array(modes, dtype=np.int64), "replicate": np.array(reps, dtype=np.int64),
            "world_id": np.arange(len(rows), dtype=np.int64)}


def encoder_contract(model):
    """Pay for both actual clean-text nuisance alternatives before any rollout."""
    labels = np.tile(np.arange(8), 2)
    raw = _render_modality(labels, "text", np.random.default_rng(0), False).reshape(16, 4, 10)
    raw[8:, 3, 7], raw[8:, 3, 8] = 0, 1
    before = model.work_receipt()["linear_macs"]
    predicted = encode(model.source.base, "text", raw.reshape(16, 40))[0]
    receipt = {"inputs": 16, "correct": int(np.sum(predicted == labels)),
               "actual_linear_macs": model.work_receipt()["linear_macs"] - before,
               "predictions": predicted.tolist(), "expected_conditions": labels.tolist()}
    if receipt["correct"] != 16 or receipt["actual_linear_macs"] != 16 * 3072:
        raise RuntimeError("registered clean encoder contract failed: " + json.dumps(receipt))
    return receipt


def _reconcile(native, receipt):
    if (native["remaining"] != receipt["remaining_macs"] or native["version"] != receipt["version"]
            or native["refinement_counts"] != receipt["refinement_counts"]
            or native["total_refinements"] != sum(receipt["refinement_counts"])):
        raise AssertionError("native and actual-neural budget/state receipts differ")


def _strong_witnesses(rows):
    groups = {}
    for record in rows:
        events = record["events"]
        if len(events) < 2 or events[0]["action"] == 0 or events[1]["action"] == 0:
            continue
        first, second = events[:2]
        key = (record["condition"], record["initial_mode"], first["joint_hash"],
               first["action"], second["remaining_before"])
        groups.setdefault(key, []).append((first["branch"], second["action"], record["world_id"]))
    witnesses = []
    for key, observed in groups.items():
        pair = next(((a, b) for a in observed for b in observed if a[0] != b[0] and a[1] != b[1]), None)
        if pair is not None:
            witnesses.append({"condition": key[0], "initial_mode": key[1], "initial_joint_hash": key[2],
                              "first_action": key[3], "remaining_after_first": key[4],
                              "branch_action_world_pairs": [list(item) for item in pair]})
    return witnesses


def rollout_arm(model, policy, raw_text, modes, world_ids, arm, directory, native):
    """No evaluator truth/prototype argument enters this native-controlled loop.

    Partial states and completed emissions are saved even if an action fails.
    Innovation RNG construction happens strictly after native CHOOSE succeeds.
    """
    count = len(raw_text)
    if (count not in (64, 1024) or np.asarray(modes).shape != (count,)
            or not np.array_equal(world_ids, np.arange(count)) or np.any(np.asarray(modes) < 0)
            or np.any(np.asarray(modes) > 3)):
        raise ValueError("registered ordered input worlds required")
    if model.checkpoint_sha256 != policy.receipt["checkpoint_sha256"]:
        raise ValueError("policy and executed checkpoint differ")
    if weight_hashes(model.source)["all"] != policy.receipt["weight_sha256"]:
        raise ValueError("frozen learned tensor state changed")
    directory = Path(directory)
    directory.mkdir(parents=True)
    started, cpu = time.perf_counter(), time.process_time()
    model.reset_work()
    latents = np.zeros((count, 3, 4, 64), dtype=np.float32)
    observed_count = np.zeros(count, dtype=np.int64)
    outputs = {name: [] for name in MODALITIES}
    completed, control, current = [], [], None
    max_match_error, decision_seconds = 0., 0.
    summary = {"status": "running", "arm": arm, "seed": policy.seed,
               "started_at_utc": datetime.now(timezone.utc).isoformat()}
    failed = None
    with gzip.open(directory / "traces.jsonl.gz", "wt") as traces:
        try:
            for row, world_id in enumerate(world_ids):
                mode = int(modes[row])
                clean = arm == "clean_no_disturbance_reference"
                initial = np.zeros((1, 4, 64), dtype=np.float32) if clean else policy.tree["initial_modes"][[mode]]
                current = {"session_id": f"s{policy.seed}-{arm}-w{int(world_id)}", "world_id": int(world_id),
                           "initial_mode": mode, "replicate": row % (count // 32), "events": [], "status": "running"}
                before_world = model.work_receipt()["linear_macs"]
                state = model.initialize(raw_text[row:row + 1], initial)
                feedback = model.feedback(state)
                latents[row, 0] = feedback["latents"].numpy()[0]
                observed_count[row] = 1
                node, error = policy.match(feedback, clean=clean)
                max_match_error = max(max_match_error, error)
                plan_index = int(policy.policy["plan_choice"][node]) if arm == "initial_feedback_committed_open_loop" else None
                plan = PLANS[plan_index] if plan_index is not None else None
                policy_mode = "CLEAN" if clean else "COMMITTED" if plan is not None else "ADAPTIVE"
                current.update(condition=feedback["condition"], initial_root=node, plan_index=plan_index,
                               plan=list(plan) if plan is not None else None, q_hash=feedback["q_hash"])
                begun = native.begin(current["session_id"], feedback, policy_mode, plan)
                current.update(wire_session_id=begun["wire_session_id"], native_begin=begun)
                _reconcile(begun, state.receipt)
                while True:
                    depth = feedback["depth"]
                    latents[row, depth] = feedback["latents"].numpy()[0]
                    observed_count[row] = depth + 1
                    decision_started = time.perf_counter()
                    decision = policy.decision(arm, depth, node, plan)
                    decision_seconds += time.perf_counter() - decision_started
                    event = {"depth": depth, "node": node, "version": feedback["version"],
                             "spent_before": feedback["spent_macs"], "remaining_before": feedback["remaining_macs"],
                             "counts_before": feedback["refinement_counts"], "latent_hashes": feedback["latent_hashes"],
                             "joint_hash": feedback["joint_hash"], "residual_rms": feedback["residual_rms"][0].tolist(),
                             "last_update_rms": feedback["last_update_rms"][0].tolist(),
                             "action": decision["action"], "action_name": ACTIONS[decision["action"]],
                             "scores": decision["scores"].tolist(), "eligible": decision["eligible"].tolist(),
                             "branch": None, "global_refinement_index": None, "innovation_sha256": None}
                    current["events"].append(event)
                    chosen = native.choose(current["session_id"], feedback, decision)
                    event["native_choice"] = chosen
                    action = chosen["action"]
                    if action != decision["action"]:
                        raise AssertionError("native chose a different registered action")
                    if action == 0:
                        emitted = model.emit(state)
                        hashes = {name: tensor_hash(emitted[name]) for name in MODALITIES}
                        for name in MODALITIES:
                            outputs[name].append(emitted[name].numpy()[0].copy())
                        current.update(output_hashes=hashes, output_joint_hash=joint_hash(list(hashes.values()), "outputs"),
                                       receipt=state.receipt)
                        ack = native.emitted(current["session_id"], feedback, hashes)
                        event["native_ack"] = ack
                        _reconcile(ack, state.receipt)
                        current["status"] = "completed"
                        actual = model.work_receipt()["linear_macs"] - before_world
                        if actual != state.receipt["spent_macs"] or not state.receipt["sealed"]:
                            raise AssertionError("executed Linear hooks differ from sealed cost ledger")
                        control.append((actual, state.receipt["refinement_counts"], feedback["condition"]))
                        completed.append(current)
                        traces.write(json.dumps(current, allow_nan=False) + "\n")
                        traces.flush()
                        current = None
                        break
                    modality, index = action - 1, depth + 1
                    rng = np.random.default_rng(np.random.SeedSequence([5200000, policy.seed, int(world_id), index, modality]))
                    branch = int(rng.choice(3, p=policy.probabilities))
                    innovation = policy.tree["future_banks"][depth, modality, branch][None].copy()
                    event.update(branch=branch, global_refinement_index=index,
                                 innovation_sha256=hashlib.sha256(innovation.tobytes()).hexdigest())
                    state = model.refine_step(state, modality, innovation)
                    updated = model.feedback(state)
                    latents[row, updated["depth"]] = updated["latents"].numpy()[0]
                    observed_count[row] = updated["depth"] + 1
                    ack = native.refined(current["session_id"], updated)
                    event["native_ack"] = ack
                    _reconcile(ack, state.receipt)
                    match_started = time.perf_counter()
                    node, error = policy.match(updated, parent=node, previous_modality=modality)
                    decision_seconds += time.perf_counter() - match_started
                    max_match_error = max(max_match_error, error)
                    feedback = updated
            if weight_hashes(model.source)["all"] != policy.receipt["weight_sha256"]:
                raise AssertionError("frozen weights changed during rollout")
            if model.work_receipt()["linear_macs"] != sum(item[0] for item in control):
                raise AssertionError("whole-arm actual model work differs from world ledgers")
            summary["status"] = "completed"
        except Exception:
            failed = traceback.format_exc()
            summary.update(status="failed", traceback=failed)
            if current is not None:
                current.update(status="failed", traceback=failed)
                traces.write(json.dumps(current, allow_nan=False) + "\n")
                traces.flush()
        finally:
            output_arrays = {name: np.stack(values) if values else np.empty((0, model.source.dimensions[name]), dtype=np.float32)
                             for name, values in outputs.items()}
            np.savez_compressed(directory / "outputs.npz", **output_arrays)
            np.savez_compressed(directory / "latents.npz", latents=latents, observed_count=observed_count)
            control_arrays = {"macs": np.array([item[0] for item in control], dtype=np.int64),
                              "refinement_counts": np.array([item[1] for item in control], dtype=np.int64).reshape(-1, 4),
                              "condition": np.array([item[2] for item in control], dtype=np.int64),
                              "world_id": np.asarray(world_ids[:len(control)], dtype=np.int64)}
            np.savez_compressed(directory / "control.npz", **control_arrays)
            summary.update(completed_worlds=len(control), emitted_worlds=len(outputs["text"]), requested_worlds=count,
                           actual_model_work=model.work_receipt(),
                           wall_seconds=time.perf_counter() - started, process_cpu_seconds=time.process_time() - cpu,
                           python_policy_seconds=decision_seconds, max_latent_match_error=max_match_error,
                           strong_sibling_witnesses=_strong_witnesses(completed), all_four_outputs=len(control) == count,
                           completed_at_utc=datetime.now(timezone.utc).isoformat())
            write_json(directory / "summary.json", summary)
    if failed is not None:
        raise RuntimeError("causal rollout failed; partial evidence preserved in " + str(directory))
    return output_arrays, control_arrays, summary


def score_emitted(outputs, truth, targets, control, directory):
    """External labels and prototypes are attached only after complete emission."""
    scores = score_outputs(outputs, truth, targets)
    errors = []
    for name in MODALITIES:
        prototypes, values = np.asarray(targets[name], dtype=np.float64), np.asarray(outputs[name], dtype=np.float64)
        distances = np.column_stack([np.mean((prototypes - p) ** 2, axis=1) for p in prototypes])
        normalizer = distances[~np.eye(8, dtype=bool)].mean()
        errors.append(np.minimum(np.mean((values - prototypes[truth]) ** 2, axis=1) / normalizer, 2.))
    scores.update(control)
    scores["per_modality_error"] = np.column_stack(errors)
    scores["return"] = -scores["loss"] - (.015 / REFINE_COST) * scores["macs"]
    if not np.allclose(scores["per_modality_error"].mean(1), scores["raw_error"], rtol=0, atol=1e-10):
        raise AssertionError("per-modality errors disagree with external metric")
    path = Path(directory) / "scores.npz"
    if path.exists():
        raise FileExistsError("scored evidence cannot be overwritten")
    np.savez_compressed(path, **scores)
    if not np.array_equal(control["condition"], truth):
        raise AssertionError("clean-condition encoder contract failed; original labels retained")
    return scores
