"""Bounded numerical audit of the existing trainable temporal Cell reference.

This checks the handwritten BPTT at actual post-training parameters. Synthetic
episodes and equal update counts do not establish architecture or task benefit.
No native state owner, HCSN admission, or production adoption is performed.
"""

import copy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .temporal import TemporalConfig, TemporalKernel


def check_temporal_gradients(
    kernel, episodes, actions, allowed_mask, *, epsilon=1e-6, atol=5e-8, rtol=2e-4
):
    """Compare every analytic parameter derivative with central differences.

    Perturbations affect a private model copy only. Bounds keep this expensive
    coordinate audit a numerical diagnostic rather than an unbounded trainer.
    """
    if not isinstance(kernel, TemporalKernel) or kernel.parameter_count > 2048:
        raise ValueError("gradient audit requires a temporal kernel with <=2048 scalars")
    if any(
        isinstance(value, bool) or not np.isfinite(value) or value <= 0
        for value in (epsilon, atol, rtol)
    ):
        raise ValueError("gradient audit tolerances must be finite and positive")
    x, action = np.asarray(episodes, dtype=np.float64), np.asarray(actions, dtype=np.float64)
    allowed = np.asarray(allowed_mask)
    if (
        x.ndim != 3
        or not 1 <= x.shape[0] * x.shape[1] <= 256
        or x.size > 8192
        or x.shape[2] != kernel.config.input_dim
        or action.shape != (len(x), kernel.config.action_dim)
        or allowed.shape != (len(x), kernel.config.output_dim)
        or allowed.dtype != np.bool_
        or not allowed.any(axis=1).all()
        or not np.isfinite(x).all()
        or not np.isfinite(action).all()
    ):
        raise ValueError("invalid or over-budget gradient audit data")
    model = copy.deepcopy(kernel._model)
    loss, gradients = model.loss_and_grads(x, action, allowed)
    if not np.isfinite(loss) or set(gradients) != set(model.params):
        raise ValueError("invalid analytic gradient result")
    rows = []
    for name, parameter in sorted(model.params.items()):
        analytic = gradients[name]
        if analytic.shape != parameter.shape or not np.isfinite(analytic).all():
            raise ValueError("invalid analytic gradient tensor")
        numerical = np.empty_like(parameter)
        for index in np.ndindex(parameter.shape):
            original = parameter[index]
            try:
                losses = []
                for offset in (epsilon, -epsilon):
                    parameter[index] = original + offset
                    logits = model.forward(x, action)
                    losses.append(
                        np.mean(
                            np.logaddexp.reduce(logits, axis=1)
                            - np.logaddexp.reduce(np.where(allowed, logits, -np.inf), axis=1)
                        )
                    )
                numerical[index] = (losses[0] - losses[1]) / (2 * epsilon)
            finally:
                parameter[index] = original
        error = np.abs(analytic - numerical)
        tolerance = atol + rtol * np.maximum(np.abs(analytic), np.abs(numerical))
        rows.append(
            {
                "parameter": name,
                "scalars": int(parameter.size),
                "analytic_nonzero_scalars": int(np.count_nonzero(analytic)),
                "maximum_absolute_error": float(error.max()),
                "maximum_tolerance_ratio": float((error / tolerance).max()),
                "passed": bool(np.isfinite(numerical).all() and (error <= tolerance).all()),
            }
        )
    return {
        "schema": "hepta.cell.temporal-gradient-check.v1",
        "weights_sha256": kernel.weights_sha256,
        "loss": float(loss),
        "method": "all-coordinate central finite differences; independent forward loss",
        "epsilon": epsilon,
        "absolute_tolerance": atol,
        "relative_tolerance": rtol,
        "coordinates_checked": sum(row["scalars"] for row in rows),
        "passed": all(row["passed"] for row in rows),
        "tensors": rows,
    }


def run_temporal_reference_probe(output_directory, *, seeds=(41, 67), updates=4):
    """Retain immutable checkpoints and audit real post-update GRU/diagonal models.

    Identical synthetic inputs, labels, action candidates and update budgets are
    used by both kernels. Actual parameter counts are reported, not matched.
    Any exception propagates; no unavailable kernel becomes a skipped pass.
    """
    seeds = tuple(seeds)
    if (
        not 1 <= len(seeds) <= 8
        or len(set(seeds)) != len(seeds)
        or any(type(seed) is not int or not 0 <= seed < 2**63 for seed in seeds)
        or type(updates) is not int
        or not 1 <= updates <= 32
    ):
        raise ValueError("invalid bounded temporal reference protocol")
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(13021)
    episodes = np.zeros((8, 5, 3), dtype=np.float64)
    cue, action_id = np.arange(8) % 2, (np.arange(8) // 2) % 2
    episodes[:, 0, 0] = 2 * cue - 1
    episodes[:, :, 1] = rng.normal(0, 0.2, (8, 5))
    episodes[:, -1, 2] = 1
    actions = np.eye(2)[action_id]
    allowed = np.eye(2, dtype=bool)[cue ^ action_id]
    # One genuinely unknown target also exercises the coarsened-loss derivative.
    allowed[-1] = True
    protocol = {
        "schema": "hepta.cell.temporal-reference-protocol.v1",
        "kernels": ["gru", "diag_ssm"],
        "seeds": list(seeds),
        "hidden_width": 4,
        "episodes": 8,
        "events_per_episode": 5,
        "post_training_updates": updates,
        "resume_updates": 1,
        "learning_rate": 0.003,
        "gradient_norm_cap": 5.0,
        "input": "early binary cue; independent distractor; final query flag",
        "target": "cue XOR candidate action; final label unknown",
        "selection": "none; numerical qualification only",
        "matching": "same input, dimensions and update budget; actual parameter counts differ",
    }
    wall, cpu = time.perf_counter(), time.process_time()
    attempts = []
    for seed in seeds:
        for kind in protocol["kernels"]:
            config = TemporalConfig(3, 2, 2, hidden_dim=4, seed=seed, kind=kind)
            parent = TemporalKernel("reference-prediction", config)
            parent_identity = (parent.weights_sha256, parent.optimizer_sha256)
            candidate, training = parent.train_candidate(
                episodes, actions, allowed, updates=updates
            )
            audit = check_temporal_gradients(candidate, episodes, actions, allowed)
            streamed = []
            for index, episode in enumerate(episodes):
                state = candidate.initial_state(f"reference:{index}")
                for cursor, observation in enumerate(episode):
                    state = candidate.observe(
                        state, observation, episode_id=f"reference:{index}", cursor=cursor
                    )
                streamed.append(
                    candidate.predict(state, actions[index], episode_id=f"reference:{index}")
                )
            stream_error = float(
                np.abs(np.stack(streamed) - candidate._model.forward(episodes, actions)).max()
            )
            state = candidate.initial_state("checkpoint:episode")
            for cursor, observation in enumerate(episodes[0, :2]):
                state = candidate.observe(
                    state, observation, episode_id="checkpoint:episode", cursor=cursor
                )
            checkpoint = output_directory / f"{kind}-{seed}.npz"
            checkpoint_sha = candidate.checkpoint(checkpoint, state)
            restored, recovered_state = TemporalKernel.restore_checkpoint(
                checkpoint,
                expected_sha256=checkpoint_sha,
                cell_id=candidate.cell_id,
                config=config,
            )
            state_equal = state == recovered_state
            for cursor in range(2, episodes.shape[1]):
                state = candidate.observe(
                    state, episodes[0, cursor], episode_id="checkpoint:episode", cursor=cursor
                )
                recovered_state = restored.observe(
                    recovered_state,
                    episodes[0, cursor],
                    episode_id="checkpoint:episode",
                    cursor=cursor,
                )
            continuation_equal = state == recovered_state
            next_a, receipt_a = candidate.train_candidate(episodes, actions, allowed)
            next_b, receipt_b = restored.train_candidate(episodes, actions, allowed)
            resume_equal = (
                next_a.weights_sha256,
                next_a.optimizer_sha256,
                receipt_a["losses"],
            ) == (
                next_b.weights_sha256,
                next_b.optimizer_sha256,
                receipt_b["losses"],
            )
            parent_unchanged = parent_identity == (
                parent.weights_sha256, parent.optimizer_sha256
            )
            attempts.append(
                {
                    "kind": kind,
                    "seed": seed,
                    "config": asdict(config),
                    "training": training,
                    "gradient_audit": audit,
                    "stream_batch_maximum_error": stream_error,
                    "checkpoint": checkpoint.name,
                    "checkpoint_sha256": checkpoint_sha,
                    "checkpoint_state_exact": state_equal,
                    "continuation_state_exact": continuation_equal,
                    "resumed_optimizer_update_exact": resume_equal,
                    "resume_receipts": [receipt_a, receipt_b],
                    "parent_unchanged": parent_unchanged,
                    "passed": all(
                        (audit["passed"], stream_error <= 1e-12, state_equal,
                         continuation_equal, resume_equal, parent_unchanged)
                    ),
                }
            )
    raw_protocol = json.dumps(protocol, sort_keys=True, separators=(",", ":"))
    return {
        "schema": "hepta.cell.temporal-reference-qualification.v1",
        "protocol": protocol,
        "protocol_sha256": hashlib.sha256(raw_protocol.encode()).hexdigest(),
        "attempts": attempts,
        "passed": all(attempt["passed"] for attempt in attempts),
        "wall_seconds": time.perf_counter() - wall,
        "process_cpu_seconds": time.process_time() - cpu,
        "numpy": np.__version__,
        "energy_joules": None,
        "architecture_ranking_established": False,
        "real_task_benefit_established": False,
        "production_qualified": False,
        "hcsn_fits_started": 0,
    }
