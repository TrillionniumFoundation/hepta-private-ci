"""Prespecified constructed momentum reflection; no reachable-state guarantee.

Changes only momentum at three fixed A-bank parents, using current gradients.
Future labels and replay tapes are not construction features. This is not an
independent efficacy test or a sufficiency theorem on reachable occupancy.
"""

import argparse
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import time

import numpy as np
import torch

from ..multimodal_output_portfolio.field_bridge_v3_20261027 import learning, training_features
from ..multimodal_output_portfolio.field_bridge_v3_20261027.assets import load_assets
from ..multimodal_output_portfolio.field_bridge_v3_20261027.training_common import Costs
from .bank import initialize, measure
from .branching import BASELINES, codec, dynamics_identity, state_difference, strict, timed
from .endpoints import EndpointBudget, TRAINING_ROLES, save_score
from .heads import choose
from .run import ROOT, file_hash, verify_freeze
from .sources import load_training_roles

SEEDS = (17, 29, 43)
SCHEDULE, CLOCK, TERMINAL = 6000, 48, 288
RANK_RTOL, FIELD_TOLERANCE, MICROSTEP_CAP = 1e-10, 1e-5, 2880
STEM = "schedule-6000-baseline-step-48"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def orthogonal_reflection(momentum, directions):
    """Reflect across the SVD-retained span of four unscaled row vectors."""
    m, rows = np.asarray(momentum, dtype=np.float64), np.asarray(directions, dtype=np.float64)
    require(m.ndim == 1 and m.size > 0 and rows.shape == (4, m.size)
            and np.isfinite(m).all() and np.isfinite(rows).all(), "Invalid reflection coordinates")
    _, singular, vectors = np.linalg.svd(rows, full_matrices=False)
    cutoff = float(singular[0]) * RANK_RTOL if len(singular) else 0.
    rank = int(np.sum(singular > cutoff))
    basis = vectors[:rank]
    projection = basis.T @ (basis @ m)
    reflected = 2. * projection - m
    normal = m - projection
    before, after = rows @ m, rows @ reflected
    return reflected, {"rank": rank, "rank_relative_cutoff": RANK_RTOL, "singular_values": singular.tolist(),
                       "absolute_singular_cutoff": cutoff, "momentum_norm": float(np.linalg.norm(m)),
                       "reflected_float64_norm": float(np.linalg.norm(reflected)),
                       "orthogonal_residual_norm": float(np.linalg.norm(normal)),
                       "reflection_change_norm": float(np.linalg.norm(reflected - m)),
                       "constraint_inner_products_before": before.tolist(),
                       "constraint_inner_products_after": after.tolist(),
                       "max_constraint_drift": float(np.abs(after - before).max())}


def momentum_coordinates(record, names):
    by_name = {name: index for index, name in record["optimizer_parameter_names"].items()}
    require(set(names) == set(record["parameters"]) and len(names) == len(by_name), "Momentum coordinate inventory differs")
    arrays, layout = [], []
    for name in names:
        parameter = record["parameters"][name]
        require(parameter.dtype == np.float32, "W requires declared float32 parameters")
        value = record["optimizer"]["state"].get(by_name[name], {}).get("momentum_buffer")
        require(value is None or value.shape == parameter.shape and value.dtype == np.float32,
                "Momentum layout differs from its parameter")
        arrays.append(np.zeros(parameter.size) if value is None else value.astype(np.float64).reshape(-1))
        layout.append({"name": name, "shape": list(parameter.shape), "size": parameter.size,
                       "momentum_present": value is not None, "optimizer_id": by_name[name]})
    return np.concatenate(arrays), layout


def replace_momentum(record, names, reflected):
    original, layout = momentum_coordinates(record, names)
    vector = np.asarray(reflected, dtype=np.float64)
    require(vector.shape == original.shape and np.isfinite(vector).all(), "Invalid reflected momentum")
    changed, offset, introduced = deepcopy(record), 0, []
    for item in layout:
        part = vector[offset:offset + item["size"]].reshape(item["shape"]).astype(np.float32)
        offset += item["size"]
        require(np.isfinite(part).all(), "Reflected float32 momentum overflow")
        if item["momentum_present"] or np.any(part):
            fields = changed["optimizer"]["state"].setdefault(item["optimizer_id"], {})
            fields["momentum_buffer"] = part
            if not item["momentum_present"]:
                introduced.append(item["name"])
    left, right = deepcopy(record), deepcopy(changed)
    left["optimizer"]["state"], right["optimizer"]["state"] = {}, {}
    require(codec.dumps(left) == codec.dumps(right), "Reflection changed non-momentum state")
    return changed, layout, introduced


def current_directions(adapter, names):
    """Paid current weighted gradient and three probe gradients; restore all state."""
    raw, sha = adapter.seal()
    context, model, optimizer = adapter.context, adapter.model, adapter.optimizer
    parameters = [dict(model.named_parameters())[name] for name in names]
    try:
        next_row = learning.schedule(context.seed, adapter.schedule_id, adapter.clock, 1, context.protocol)[0]
        adapt, rehearsal = context.batches(next_row)
        learning.update(model, context.original, optimizer, adapt, rehearsal, context.action, 0.,
                        next_row["noise_seed"], context.protocol, context.costs, name="witness_directional")
        present = [parameter.grad is not None for parameter in parameters]
        gradients = [torch.zeros_like(parameter) if parameter.grad is None else parameter.grad.detach().clone()
                     for parameter in parameters]
        rows = [np.concatenate([value.double().numpy().reshape(-1) for value in gradients])]
        losses = training_features.probe_losses(context, model)
        for index, loss in enumerate((losses["adapt"]["image_bce"], losses["adapt"]["text_ce"], losses["clean"]["joint"])):
            values = torch.autograd.grad(loss, parameters, retain_graph=index == 0, allow_unused=True)
            rows.append(np.concatenate([np.zeros(parameter.numel()) if value is None else
                                       value.detach().double().numpy().reshape(-1)
                                       for parameter, value in zip(parameters, values, strict=True)]))
            context.costs.add("witness_probe_reverse_calls")
            panel = context.probe if index < 2 else context.guard
            context.costs.add("witness_probe_reverse_examples", sum(len(part.batch.source_ids) for part in panel))
        mask = np.concatenate([np.full(parameter.numel(), active, dtype=bool)
                               for parameter, active in zip(parameters, present, strict=True)])
        matrix = np.asarray(rows, dtype=np.float64)
        metadata = {"names": names, "next_gradient_present": dict(zip(names, present, strict=True)),
                    "probe_gradient_norm_on_inactive_next_gradient_coordinates":
                        np.linalg.norm(matrix[1:, ~mask], axis=1).tolist(),
                    "direction_names": ["clipped_next_weighted_gradient", "adapt_image_bce_gradient",
                                        "adapt_text_ce_gradient", "clean_joint_gradient"]}
    finally:
        adapter.restore(raw, sha)
    require(codec.dumps(adapter.capture()) == raw, "Projection measurement failed complete-state restoration")
    return matrix, metadata


def ranking(values):
    values = np.asarray(values, dtype=np.float64)
    require(values.shape == (4,) and np.isfinite(values).all(), "Invalid four-action values")
    return [[int(i) for i in np.flatnonzero(values == value)] for value in sorted(set(values.tolist()), reverse=True)]


def persist(path, payload, check):
    check(len(payload))
    path = Path(path)
    with path.open("xb") as stream:
        stream.write(payload)
    sha = hashlib.sha256(payload).hexdigest()
    require(path.stat().st_size == len(payload) and file_hash(path) == sha, "W evidence readback differs")
    return {"path": path.name, "bytes": len(payload), "sha256": sha}


def persist_json(path, record, check):
    return persist(path, (json.dumps(record, sort_keys=True, indent=2, allow_nan=False) + "\n").encode(), check)


def inputs(root):
    result = []
    for seed in SEEDS:
        parent_directory = Path(root) / "stage_A" / f"seed-{seed}"
        require(not (parent_directory / "FAILED.json").exists(), "A failed A instance cannot supply W evidence")
        directory = parent_directory / "bank"
        bank_path = directory / "BANK.json"
        bank = json.loads(bank_path.read_text())
        require(bank.get("complete") is True and bank["seed"] == seed and len(bank["records"]) == 48,
                "W requires every complete A bank")
        matches = [(i, row) for i, row in enumerate(bank["records"])
                   if (row["schedule_id"], row["prefix"], row["step"]) == (SCHEDULE, "baseline", CLOCK)]
        require(len(matches) == 1, "Fixed W parent is missing or duplicated")
        index, row = matches[0]
        raw = (directory / (STEM + ".state")).read_bytes()
        parent = codec.loads(raw, row["parent_sha256"], row["parent_bytes"])
        require(parent["cursor"]["seed"] == seed and parent["cursor"]["clock"] == CLOCK
                and parent["cursor"]["schedule_id"] == SCHEDULE and parent["cursor"]["path_kind"] == "baseline",
                "W parent coordinates differ")
        with np.load(directory / "field12-bank.npz", allow_pickle=False) as stored:
            field = stored["features"][index].copy()
        head_path = directory / "field12-head.npz"
        with np.load(head_path, allow_pickle=False) as stored:
            head = {**json.loads(stored["metadata_json"].item()),
                    **{key: stored[key].copy() for key in stored.files if key != "metadata_json"}}
        require(head["dimension"] == 12 and head["baseline"] == BASELINES[seed]
                and head["fit_count"] == 36 and head["calibration_count"] == 12, "W normalizer/head differs")
        original_artifacts = []
        for action in range(4):
            path = directory / f"{STEM}-action-{action}.npz"
            with np.load(path, allow_pickle=False) as stored:
                value = float(stored["values_reward"].mean())
            require(value == row["action_values"][action], "Original paired bank value differs from raw outputs")
            original_artifacts.append({"path": str(path.relative_to(Path(root))), "sha256": file_hash(path)})
        result.append({"seed": seed, "parent": parent, "raw": raw, "row": row, "field": field, "head": head,
                       "bank_sha256": file_hash(bank_path), "head_sha256": file_hash(head_path),
                       "original_output_artifacts": original_artifacts})
    return result


def run_seed(entry, original, observers, corpus, protocol, costs, destination, check):
    seed, parent = entry["seed"], entry["parent"]
    directory = destination / f"seed-{seed}"
    directory.mkdir()
    context = learning.make_context(original, corpus, observers, seed, "development", protocol, costs)
    adapter = initialize(context, parent["binding"], SCHEDULE, "baseline")
    adapter.restore(entry["raw"], entry["row"]["parent_sha256"])
    original_state = persist(directory / "original-parent.state", entry["raw"], check)
    unused, unused_sha, unused_record, measured, original_receipt = measure(adapter)
    old_field = measured["field12"]
    require(np.array_equal(old_field, entry["field"]), "Fixed parent H12 does not exactly replay its bank measurement")
    names = sorted(parent["parameters"])
    directions, direction_metadata = timed(costs, "witness_direction_basis", lambda: current_directions(adapter, names))
    old_momentum, _ = momentum_coordinates(parent, names)
    new_momentum, projection = timed(costs, "witness_svd", lambda: orthogonal_reflection(old_momentum, directions))
    constructed, layout, introduced = replace_momentum(parent, names, new_momentum)
    raw = codec.dumps(constructed)
    digest = hashlib.sha256(raw).hexdigest()
    adapter.restore(raw, digest)
    require(codec.dumps(adapter.capture()) == raw, "Constructed momentum state did not restore literally")
    reflected_state = persist(directory / "reflected-parent.state", raw, check)
    unused, unused_sha, unused_record, reflected, reflected_receipt = measure(adapter)
    new_field = reflected["field12"]
    actual_momentum, _ = momentum_coordinates(constructed, names)
    difference = new_field - old_field
    normalized = np.abs(difference) / np.maximum(entry["head"]["scale"], 1e-8)
    geometry = io.BytesIO()
    np.savez_compressed(geometry, directions=directions, momentum=old_momentum, reflected_float64=new_momentum,
                        reflected_float32_as_float64=actual_momentum, field_before=old_field, field_after=new_field,
                        training_scale=entry["head"]["scale"])
    geometry_artifact = persist(directory / "projection.npz", geometry.getvalue(), check)
    first_states, branches, values = {}, [], []
    for action in range(4):
        check()
        adapter.restore(raw, digest)
        before_work = costs.snapshot()
        first = adapter.transition(action)
        first_raw, first_sha = adapter.seal()
        first_states[action] = adapter.capture()
        first_artifact = persist(directory / f"action-{action}-first.state", first_raw, check)
        transactions = [first]
        while adapter.clock < TERMINAL:
            check()
            transactions.append(adapter.transition(BASELINES[seed]))
        terminal_raw, terminal_sha = adapter.seal()
        terminal_artifact = persist(directory / f"action-{action}-terminal.state", terminal_raw, check)
        score = timed(costs, "witness_label_scoring", lambda: learning.hard_panel(
            adapter.model, context.probe, observers, context.action, protocol, costs, "witness_reference_tail", retain=True))
        output = timed(costs, "witness_output_persist", lambda: save_score(
            directory / f"action-{action}-outputs.npz", score, check_write=check))
        value = score["means"]["reward"]
        values.append(value)
        identity = dynamics_identity(first_states[action])
        old_identity = entry["row"]["branches"][action]["first"]
        branch = {"action": action, "value": value, "first_state": first_artifact, "terminal_state": terminal_artifact,
                  "first_state_sha256": first_sha, "terminal_state_sha256": terminal_sha,
                  "original_vs_reflected_first_different_components":
                      [key for key, value in identity["components"].items() if old_identity["components"][key] != value],
                  "outputs": {"path": f"action-{action}-outputs.npz", **output},
                  "transactions": transactions, "costs": costs.since(before_work)}
        persist_json(directory / f"action-{action}.json", branch, check)
        branches.append(branch)
    original_values = np.asarray(entry["row"]["action_values"])
    original_ranking, reflected_ranking = ranking(original_values), ranking(values)
    original_choice, original_choice_receipt = choose(entry["head"], old_field)
    reflected_choice, reflected_choice_receipt = choose(entry["head"], new_field)
    near = bool(normalized.max() <= FIELD_TOLERANCE)
    summary = {"seed": seed, "parent": {"schedule": SCHEDULE, "prefix": "baseline", "clock": CLOCK},
               "constructed_off_policy": True, "reachable_state_guarantee": False, "certificate": False,
               "interpretation": "Numerical constructed-state diagnostic; not reachable-occupancy insufficiency or independent efficacy.",
               "original_parent": original_state, "reflected_parent": reflected_state, "geometry": geometry_artifact,
               "projection": projection, "coordinate_layout": layout, "introduced_momentum_buffers": introduced,
               "direction_metadata": direction_metadata,
               "stored_float32_momentum_change_norm": float(np.linalg.norm(actual_momentum - old_momentum)),
               "stored_float32_momentum_norm_drift": float(np.linalg.norm(actual_momentum) - np.linalg.norm(old_momentum)),
               "stored_float32_constraint_drift": (directions @ (actual_momentum - old_momentum)).tolist(),
               "field_before": old_field.tolist(), "field_after": new_field.tolist(),
               "absolute_field_drift": np.abs(difference).tolist(), "normalized_field_drift": normalized.tolist(),
               "near_field_tolerance": FIELD_TOLERANCE, "near_field": near,
               "original_action_values": original_values.tolist(), "reflected_action_values": values,
               "original_advantages": (original_values - original_values[BASELINES[seed]]).tolist(),
               "reflected_advantages": (np.asarray(values) - values[BASELINES[seed]]).tolist(),
               "original_ranking": original_ranking, "reflected_ranking": reflected_ranking,
               "ranking_changed": original_ranking != reflected_ranking,
               "best_action_set_changed": original_ranking[0] != reflected_ranking[0],
               "head_choices": {"original": original_choice, "reflected": reflected_choice,
                                "original_receipt": original_choice_receipt, "reflected_receipt": reflected_choice_receipt},
               "parent_full_state_difference": state_difference(parent, constructed),
               "reflected_postguard_difference_from_own_baseline":
                   {str(action): state_difference(state, first_states[BASELINES[seed]]) for action, state in first_states.items()},
               "original_measurement": original_receipt, "reflected_measurement": reflected_receipt,
               "original_bank_sha256": entry["bank_sha256"], "original_head_sha256": entry["head_sha256"],
               "original_output_artifacts": entry["original_output_artifacts"], "branches": branches}
    persist_json(directory / "WITNESS.json", summary, check)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--freeze", required=True)
    parser.add_argument("--protocol", default=str(Path(__file__).with_name("PROTOCOL.json")))
    args = parser.parse_args()
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    freeze = verify_freeze(args.freeze, "W")
    final_protocol = json.loads(Path(args.protocol).read_text())
    require(final_protocol.get("execution_ready") is True and file_hash(args.protocol) == freeze["protocol_sha256"],
            "W requires a source-bound execution-ready protocol")
    registration = final_protocol["stage_W"]
    require(registration["model_seeds"] == list(SEEDS)
            and registration["parent"] == {"stage": "A_bank", "schedule": SCHEDULE, "prefix": "baseline", "clock": CLOCK}
            and registration["additional_scheduled_gradient_microsteps"] == MICROSTEP_CAP,
            "W registration differs from its fixed parents and work count")
    require(str(Path(__file__).resolve().relative_to(ROOT)) in freeze["source_files"], "W code is absent from source freeze")
    root, costs = Path(args.root).resolve(), Costs()
    budget = EndpointBudget(root, costs, "W")
    def check(additional=0):
        budget(additional)
        require(costs.values.get("scheduled_gradient_microsteps", 0) <= MICROSTEP_CAP, "W physical gradient cap exceeded")
    check()
    selected = inputs(root)
    runtime = codec.digest(strict.runtime_descriptor())
    require(all(entry["parent"]["binding"]["runtime_sha256"] == runtime for entry in selected), "W runtime differs from A parents")
    destination = root / "stage_W"
    destination.mkdir(exist_ok=False)
    try:
        originals, observers, assets = load_assets(args.assets, list(SEEDS), ["reward"])
        corpus = load_training_roles(args.assets, "A", TRAINING_ROLES)
        protocol = json.loads(Path(learning.__file__).with_name("PROTOCOL.json").read_text())
        summaries = []
        for entry in selected:
            before = costs.snapshot()
            summary = run_seed(entry, originals[entry["seed"]], observers, corpus, protocol, costs, destination, check)
            summary["all_seed_work"] = costs.since(before)
            summaries.append(summary)
            print(json.dumps({"stage": "W", "seed": entry["seed"], "near_field": summary["near_field"],
                              "ranking_changed": summary["ranking_changed"]}), flush=True)
        require(costs.values.get("scheduled_gradient_microsteps") == MICROSTEP_CAP, "W work inventory is incomplete")
        result = {"schema": "hepta.fullstudy.constructed-momentum-witness.1", "complete": True,
                  "records": summaries, "costs": costs.snapshot(), "scheduled_gradient_microsteps": MICROSTEP_CAP,
                  "wall_seconds": time.monotonic() - budget.wall, "cpu_seconds": time.process_time() - budget.cpu,
                  "source_freeze_sha256": file_hash(args.freeze), "registered_commit": freeze["registered_commit"],
                  "assets": assets, "new_endpoint_roles_opened": [], "original_replay_gradient_microsteps": 0,
                  "reachable_state_guarantee": False, "independent_efficacy_claim": False}
        persist_json(destination / "COMPLETE.pending.json", result, check)
        check()
        (destination / "COMPLETE.pending.json").rename(destination / "COMPLETE.json")
    except BaseException as error:
        failure = {"complete": False, "error_type": type(error).__name__, "message": str(error),
                   "costs": costs.snapshot(), "partial_evidence_preserved": True}
        try:
            persist_json(destination / "FAILED.json", failure, lambda additional=0: None)
        except OSError:
            print(json.dumps(failure), flush=True)
        raise


if __name__ == "__main__":
    main()
