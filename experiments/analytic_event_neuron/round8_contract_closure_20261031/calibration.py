"""Fixed-cell, deployment-aligned four-action calibration of frozen R7 fits.

The second stage changes a separate readout encoder.  A frozen encoder still
drives the cell, so its independent finite-DAG Q* targets remain valid.
"""

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from ..round7.data import task_configuration
from ..round7.model import JointCell, load_model
from ..round7.posthoc.independent_joint_optimal import (
    build_public_graph, forward_audit, network_greedy_actions, prepare_kernel, solve,
)
from ..round7.study import checkpoint_path
from ..round7.task import features


SCHEMA = "round8-fixed-cell-calibrator-v1"
MODES = ("direct", "continuous", "clocked", "first_passage")
SEEDS = tuple(range(11, 16))
SETTINGS = {
    "steps_per_stage": 400,
    "readout_learning_rate": 0.01,
    "content_readout_learning_rate": 0.003,
    "gradient_clip": 5.0,
    "trace_every": 20,
    "baseline_occupancy_weight": 0.45,
    "optimal_occupancy_weight": 0.45,
    "uniform_public_latent_weight": 0.10,
    "selection": "fixed final update; no checkpoint selection",
    "compute_price": 0.0005,
    "event_price": 0.0002,
}


class FixedCellCalibrator(JointCell):
    """The readout content branch can change without changing any transition."""

    def __init__(self, source):
        super().__init__(**source.configuration())
        self.load_state_dict(source.state_dict())
        self.kernel_content = copy.deepcopy(self.content)
        for parameter in self.parameters():
            parameter.requires_grad_(False)

    def encode(self, inputs):
        content = self.content(inputs)
        drive = 1.5 * torch.tanh(self.drive(self.kernel_content(inputs)).squeeze(-1))
        return content, drive

    def set_stage(self, stage):
        if stage not in ("readout", "content_readout"):
            raise ValueError(stage)
        for parameter in self.parameters():
            parameter.requires_grad_(False)
        modules = (self.readout,) if stage == "readout" else (self.content, self.readout)
        for module in modules:
            for parameter in module.parameters():
                parameter.requires_grad_(True)


def _json_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def tensor_digest(named_tensors):
    digest = hashlib.sha256()
    for key, tensor in sorted(named_tensors):
        value = tensor.detach().cpu().contiguous().numpy()
        digest.update(key.encode())
        digest.update(str((value.dtype.str, value.shape)).encode())
        digest.update(value.tobytes())
    return digest.hexdigest()


def frozen_cell_digest(model):
    return tensor_digest((key, value) for key, value in model.state_dict().items()
                         if key.startswith(("core.", "drive.", "kernel_content.")))


def save_calibrated(model, path, metadata):
    _json_write(path, {"schema": SCHEMA, "configuration": model.configuration(),
                       "metadata": metadata,
                       "state_dict": {key: value.detach().cpu().tolist()
                                      for key, value in model.state_dict().items()}})


def load_calibrated(path):
    record = json.loads(Path(path).read_text())
    if record.get("schema") != SCHEMA:
        raise ValueError("unsupported calibration checkpoint schema")
    model = FixedCellCalibrator(JointCell(**record["configuration"]))
    current = model.state_dict()
    model.load_state_dict({key: torch.as_tensor(value, dtype=current[key].dtype)
                           for key, value in record["state_dict"].items()})
    model.eval()
    if frozen_cell_digest(model) != record["metadata"]["frozen_cell_sha256"]:
        raise ValueError("checkpoint frozen-cell digest mismatch")
    return model, record["metadata"]


def training_table(model, graph, kernel):
    """Q* and weights use public transitions and the fixed cell, never a head target."""
    optimum = solve(graph, kernel)
    baseline = solve(graph, kernel, policy=network_greedy_actions(model, graph))
    _, baseline_mass, _ = forward_audit(graph, kernel, optimum, baseline)
    _, optimal_mass, _ = forward_audit(graph, kernel, optimum, optimum)
    weights = (SETTINGS["baseline_occupancy_weight"] * baseline_mass / baseline_mass.sum()
               + SETTINGS["optimal_occupancy_weight"] * optimal_mass / optimal_mass.sum()
               + SETTINGS["uniform_public_latent_weight"] / baseline_mass.size)
    if abs(weights.sum() - 1.0) > 1e-12:
        raise AssertionError("training weights must sum to one")
    legal = np.broadcast_to(graph.legal[:, None, :], optimum.q_after.shape).copy()
    q = np.where(legal, optimum.q_after, 0.0)
    table = {"q_after": q, "legal": legal, "weights": weights,
             "baseline_occupancy": baseline_mass, "optimal_occupancy": optimal_mass,
             "optimal_actions": optimum.actions}
    return optimum, table


def calibration_loss(prediction, target, legal, weights):
    # Invalid Q* entries have already been replaced by zero; never multiply inf by zero.
    squared = (prediction - target).square().masked_fill(~legal, 0.0)
    per_state = squared.sum(-1) / legal.sum(-1)
    return (weights * per_state).sum(), squared.sum() / legal.sum()


def fit_stage(model, graph, table, stage):
    """Fixed updates on a static table.  The greedy deployment is audited afterwards."""
    model.set_stage(stage)
    trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
    optimizer = torch.optim.Adam(trainable, lr=SETTINGS[f"{stage}_learning_rate"])
    inputs = torch.tensor(np.stack([features(state) for state in graph.states]), dtype=torch.float64)
    target = torch.from_numpy(table["q_after"])
    legal = torch.from_numpy(table["legal"])
    weights = torch.from_numpy(table["weights"])
    frozen_before = frozen_cell_digest(model)
    initial = {key: value.detach().clone() for key, value in model.named_parameters()}
    started, cpu_started = time.perf_counter(), time.process_time()
    curve, gradient_norm = [], None
    for step in range(SETTINGS["steps_per_stage"] + 1):
        optimizer.zero_grad(set_to_none=True)
        # Propagation is frozen and has no role in this supervised forward pass.
        content = model.content(inputs)
        prediction = model.state_action_values(inputs, content)[:, :, 1, :]
        loss, uniform_mse = calibration_loss(prediction, target, legal, weights)
        if not torch.isfinite(loss):
            raise FloatingPointError("nonfinite calibration objective")
        if step % SETTINGS["trace_every"] == 0 or step == SETTINGS["steps_per_stage"]:
            curve.append({"step": step, "weighted_mse": float(loss.detach()),
                          "uniform_legal_rmse": float(uniform_mse.detach().sqrt()),
                          "previous_update_gradient_norm": gradient_norm,
                          "process_cpu_seconds": time.process_time() - cpu_started})
        if step == SETTINGS["steps_per_stage"]:
            break
        loss.backward()
        gradient_norm = float(torch.nn.utils.clip_grad_norm_(trainable, SETTINGS["gradient_clip"]))
        if not np.isfinite(gradient_norm):
            raise FloatingPointError("nonfinite calibration gradient")
        optimizer.step()
    if frozen_cell_digest(model) != frozen_before:
        raise AssertionError("frozen cell changed during calibration")
    changes = {key: float((value.detach() - initial[key]).norm())
               for key, value in model.named_parameters()}
    return {"stage": stage, "steps": SETTINGS["steps_per_stage"],
            "learning_rate": SETTINGS[f"{stage}_learning_rate"], "trace": curve,
            "training_wall_seconds": time.perf_counter() - started,
            "training_process_cpu_seconds": time.process_time() - cpu_started,
            "active_parameter_count": sum(p.numel() for p in trainable),
            "stored_parameter_count": sum(p.numel() for p in model.parameters()),
            "parameter_change_l2": changes, "frozen_cell_unchanged": True,
            "Q1_head_trained_or_claimed": False}


def calibrate_one(round7, output, mode, seed):
    from .calibration_audit import exact_audit, zero_event_price_audit

    started, cpu_started = time.perf_counter(), time.process_time()
    source = checkpoint_path(Path(round7) / "evidence", mode, "none", seed)
    source_bytes = source.read_bytes()
    original, _ = load_model(source)
    model = FixedCellCalibrator(original)
    graph = build_public_graph([task_configuration(index) for index in range(8)])
    kernel = prepare_kernel(model, graph)
    optimum, table = training_table(model, graph, kernel)
    output = Path(output)
    target_path = output / "calibration_targets" / f"{mode}_none_{seed}.npz"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with target_path.open("xb") as stream:
        np.savez_compressed(stream, **table)
    base_metadata = {
        "mode": mode, "seed": seed, "source_checkpoint": str(source),
        "source_checkpoint_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "frozen_cell_sha256": frozen_cell_digest(model), "settings": SETTINGS,
        "public_training_configurations": [p.to_dict() for p in graph.configurations],
        "public_state_count": len(graph.states),
        "target_archive": str(target_path),
        "target_archive_sha256": hashlib.sha256(target_path.read_bytes()).hexdigest(),
        "target_source": "independent fixed-cell full four-action finite-DAG Q*",
        "architecture": "separate frozen kernel_content and trainable readout content",
        "evaluation_split": "R7 nominal development; no heldout values used for training or selection",
    }
    audits, stages, checkpoints = {}, {}, {}
    for stage in ("baseline", "readout", "content_readout"):
        if stage != "baseline":
            stages[stage] = fit_stage(model, graph, table, stage)
        new_kernel = prepare_kernel(model, graph)
        difference = float(np.max(np.abs(new_kernel.transition - kernel.transition)))
        if difference != 0.0:
            raise AssertionError("cell transition changed; fixed targets would be stale")
        audits[stage] = exact_audit(model, graph, kernel, optimum, table)
        metadata = dict(base_metadata, stage=stage, training=stages.get(stage),
                        exact_training_graph_audit=audits[stage],
                        maximum_kernel_change=difference)
        path = output / "calibration_models" / f"{mode}_none_{seed}_{stage}.json"
        save_calibrated(model, path, metadata)
        checkpoints[stage] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        print(json.dumps({"mode": mode, "seed": seed, "stage": stage,
                          "gap": audits[stage]["optimal_minus_greedy_mean"],
                          "weighted_rmse": audits[stage]["training_weighted_rmse"]}), flush=True)
    result = dict(base_metadata, stages=stages, audits=audits, checkpoints=checkpoints,
                  zero_event_price_audit=zero_event_price_audit(graph, kernel),
                  source_checkpoint_unchanged=source.read_bytes() == source_bytes,
                  total_wall_seconds=time.perf_counter() - started,
                  total_process_cpu_seconds=time.process_time() - cpu_started,
                  completed_utc=datetime.now(timezone.utc).isoformat())
    if not result["source_checkpoint_unchanged"]:
        raise AssertionError("source checkpoint changed")
    _json_write(output / f"calibration_{mode}_{seed}.json", result)
    return result


def summarize(records):
    rows = []
    for mode in MODES:
        selected = [record for record in records if record["mode"] == mode]
        if not selected:
            continue
        for stage in ("baseline", "readout", "content_readout"):
            audit = [record["audits"][stage] for record in selected]
            rows.append({"mode": mode, "stage": stage, "fits": len(selected),
                         "optimal_minus_greedy_mean": float(np.mean([a["optimal_minus_greedy_mean"] for a in audit])),
                         "greedy_return_mean": float(np.mean([a["greedy_return_mean"] for a in audit])),
                         "uniform_legal_rmse_mean": float(np.mean([a["uniform_legal_rmse"] for a in audit])),
                         "all_preset4_initial_STOP": all(a["initial_decisions"][4]["greedy_action_probabilities"][3] > 1 - 1e-10 for a in audit),
                         "preset7_optimality_gap_mean": float(np.mean([a["per_configuration"][7]["optimal_minus_greedy"] for a in audit]))})
    return {"classification": "development calibration with exact finite-law audits, not heldout superiority",
            "settings": SETTINGS, "summary": rows, "completed_fits": len(records),
            "independent_unit": "original fit seed; states, trajectories and stages are not independent fits",
            "all_zero_event_price_checks_passed": all(r["zero_event_price_audit"]["passed"] for r in records),
            "all_original_checkpoints_unchanged": all(r["source_checkpoint_unchanged"] for r in records),
            "total_process_cpu_seconds": sum(r["total_process_cpu_seconds"] for r in records)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round7", type=Path, default=Path(__file__).resolve().parents[1] / "round7")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "evidence")
    parser.add_argument("--modes", nargs="+", choices=MODES, default=list(MODES))
    parser.add_argument("--seeds", nargs="+", type=int, choices=SEEDS, default=list(SEEDS))
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    records = [calibrate_one(args.round7, args.output, mode, seed)
               for mode in args.modes for seed in args.seeds]
    _json_write(args.output / "calibration_summary.json", summarize(records))


if __name__ == "__main__":
    main()
