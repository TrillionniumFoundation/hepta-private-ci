"""Independent spatial/temporal credit factors using the existing FP64 kernel.

This synthetic cue-copy panel grants no native-owner or agent-efficacy status.
Dense timing supplies more supervised events than terminal timing. Compare local
methods within one timing/horizon/coverage stratum; BPTT has privileged full
derivatives and is an offline oracle, not an information/cost-matched local arm.
"""

from dataclasses import replace
from pathlib import Path
import time

import numpy as np

from . import credit
from .protocol import canonical_digest, source_inventory


METHODS = (
    "bptt",
    "shared_scalar",
    "type_specific",
    "shuffled_routing",
    "diffusion",
    "shuffled_diffusion",
    "zero_feedback",
)
HORIZONS = (4, 16)
TIMINGS = ("dense", "terminal")
COVERAGES = ("all", "sparse")
EVALUATION_EPISODES = 12
ROUTING_PERMUTATION = (3, 0, 6, 2, 5, 1, 4)
_ROOT = Path(__file__).resolve().parent
_SOURCES = ("credit_axes.py", "credit.py", "protocol.py")
_IMPORTED_SOURCE = source_inventory(_ROOT, _SOURCES)


def _spec(seed, updates, horizon, timing, coverage, method):
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("seed must be a nonnegative bounded integer")
    if type(updates) is not int or not 1 <= updates <= 128:
        raise ValueError("updates must be an integer in 1..128")
    if (
        type(horizon) is not int
        or horizon not in HORIZONS
        or timing not in TIMINGS
        or coverage not in COVERAGES
        or method not in METHODS
    ):
        raise ValueError("unknown credit-axis configuration")
    paired = dict(
        seed=seed, updates=updates, horizon=horizon, timing=timing, coverage=coverage
    )
    declared = {
        "schema": "hepta.credit-axes-spec.v1",
        "family": "credit_axes",
        **paired,
        "method": method,
        "comparison_id": canonical_digest(paired),
        "budget": {
            "optimizer_updates": updates,
            "training_observations": updates * horizon,
            "supervised_events": updates * (horizon if timing == "dense" else 1),
            "evaluation_episodes_per_model": EVALUATION_EPISODES,
            "tuning_trials": 0,
        },
    }
    return {**declared, "attempt_id": "credit_axes:" + canonical_digest(declared)}


def credit_axes_specs(seeds, updates=12):
    """Freeze all opportunities before training; repetitions are not new seeds."""
    if not isinstance(seeds, (tuple, list)) or not 1 <= len(seeds) <= 32:
        raise ValueError("provide 1..32 distinct integer seeds")
    for seed in seeds:
        _spec(seed, updates, HORIZONS[0], TIMINGS[0], COVERAGES[0], METHODS[0])
    if len(set(seeds)) != len(seeds):
        raise ValueError("duplicate seeds")
    return [
        _spec(seed, updates, horizon, timing, coverage, method)
        for seed in seeds
        for horizon in HORIZONS
        for timing in TIMINGS
        for coverage in COVERAGES
        for method in METHODS
    ]


def credit_axes_rule(model, method, coverage):
    """Same clipped residual, unit-L1 routes; route shuffle keeps graph fixed.

    The frozen scalar readout's signs supply type routes, without extra labels.
    Normalizing each row removes the old signed-average attenuation and equalizes
    route magnitude with the all-positive shared-scalar arm. This is a new declared
    mapping, not a rerun of the historical type-specific panel.
    """
    if method not in METHODS or coverage not in COVERAGES:
        raise ValueError("unknown credit method/coverage")
    if model.head.shape != (1, 7) or model.cell_types != tuple(range(7)):
        raise ValueError("this panel requires seven units and one scalar readout")
    rule = credit.make_rule(model, sparse_feedback=coverage == "sparse")
    norms = np.abs(rule.group_map).sum(axis=1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError("zero readout route cannot be normalized")
    mapping = rule.group_map / norms
    mask = rule.feedback_mask
    kernel = method
    if method == "shared_scalar":
        mapping = np.ones_like(mapping)
        kernel = "three_factor"
    elif method == "shuffled_routing":
        mapping = mapping[list(ROUTING_PERMUTATION)]
        kernel = "type_specific"
    elif method == "zero_feedback":
        mask = np.zeros_like(mask)
        kernel = "type_specific"
    return kernel, replace(rule, group_map=mapping, feedback_mask=mask)


def credit_axes_data(seed, horizon, split, count):
    """Reconstruct paired raw examples, independently of method and feedback.

    Train and evaluation have disjoint RNG namespaces and task IDs. They remain
    synthetic draws from the same generator, not independently sourced real tasks.
    """
    if (
        type(seed) is not int
        or not 0 <= seed < 2**32
        or type(horizon) is not int
        or horizon not in HORIZONS
        or type(count) is not int
        or not 1 <= count <= 128
    ):
        raise ValueError("invalid data dimensions or seed")
    if split not in ("train", "evaluation"):
        raise ValueError("unknown data split")
    rng = np.random.default_rng(
        np.random.SeedSequence([seed, 9127, split == "evaluation"])
    )
    examples, manifest = [], []
    for index in range(count):
        inputs, targets, _, messages = credit.copy_episode(rng, horizon)
        task_id = f"cue-copy:{seed}:{horizon}:{split}:{index}"
        payload = {
            "inputs": inputs.tolist(),
            "targets": targets.tolist(),
            "messages": messages.tolist(),
        }
        examples.append((task_id, inputs, targets, messages))
        manifest.append(
            {
                "task_id": task_id,
                "payload_sha256": canonical_digest(payload),
                "target_sha256": canonical_digest(payload["targets"]),
            }
        )
    return examples, manifest


def run_credit_axes_attempt(spec):
    """Execute one declared slot; retain partial work on ordinary failures.

    Invalid specs fail before execution. Process interruptions propagate so the
    outer create-only runner can retain its unfinished slot. No candidate is adopted.
    """
    if not isinstance(spec, dict):
        raise ValueError("spec must be an object")
    expected = _spec(
        *(
            spec.get(k)
            for k in ("seed", "updates", "horizon", "timing", "coverage", "method")
        )
    )
    if spec != expected or canonical_digest(spec) != canonical_digest(expected):
        raise ValueError("altered or incomplete declared spec")
    started, cpu_started = time.perf_counter(), time.process_time()
    record = {
        **spec,
        "status": "running",
        "reason": None,
        "failure_stage": None,
        "scope": "synthetic_cue_copy_fp64",
        "production_activation": False,
        "native_q24_equivalence": False,
        "real_task_efficacy_claim": False,
        "comparison_class": "offline_full_derivative_oracle"
        if spec["method"] == "bptt"
        else "local_raw_scalar",
        "comparison_limit": "compare within timing/horizon/coverage; dense has more supervised events; oracle has privileged derivatives",
        "routing_semantics": "unit_L1_frozen_readout_signs_or_shared_positive_scalar",
        "counts": dict(
            gradient_calls_started=0,
            gradient_calls_completed=0,
            training_observations=0,
            supervised_events=0,
            optimizer_updates=0,
            changed_updates=0,
            evaluation_forwards_started=0,
            evaluation_forwards_completed=0,
        ),
        "source_at_import": _IMPORTED_SOURCE,
        "source_at_start": None,
        "source_at_end": None,
        "initial_model_digest": None,
        "final_model_digest": None,
        "training_rows": [],
        "evaluation_rows": [],
        "step_receipts": [],
    }
    stage, model = "source_identity", None
    try:
        record["source_at_start"] = source_inventory(_ROOT, _SOURCES)
        if record["source_at_start"] != _IMPORTED_SOURCE:
            raise RuntimeError("source changed since import")
        stage = "setup"
        initial = model = credit.make_model(spec["seed"])
        kernel, rule = credit_axes_rule(initial, spec["method"], spec["coverage"])
        train, train_manifest = credit_axes_data(
            spec["seed"], spec["horizon"], "train", spec["updates"]
        )
        evaluation, evaluation_manifest = credit_axes_data(
            spec["seed"], spec["horizon"], "evaluation", EVALUATION_EPISODES
        )
        feedback = np.zeros(spec["horizon"])
        feedback[-1] = 1
        if spec["timing"] == "dense":
            feedback.fill(1 / spec["horizon"])
        data_manifest = {"train": train_manifest, "evaluation": evaluation_manifest}
        record.update(
            initial_model_digest=initial.digest,
            rule_digest=rule.digest,
            kernel_method=kernel,
            feedback_weights=feedback.tolist(),
            feedback_mask=rule.feedback_mask.tolist(),
            group_map=rule.group_map.tolist(),
            data_manifest=data_manifest,
            data_digest=canonical_digest(data_manifest),
            supervision_digest=canonical_digest(
                {"data": data_manifest, "feedback": feedback.tolist()}
            ),
        )
        stage = "training"
        for task_id, inputs, targets, messages in train:
            record["counts"]["gradient_calls_started"] += 1
            estimate = credit.gradient(
                model, inputs, targets, feedback, kernel, rule, messages
            )
            record["counts"]["gradient_calls_completed"] += 1
            record["counts"]["training_observations"] += len(inputs)
            record["counts"]["supervised_events"] += int(np.count_nonzero(feedback))
            record["training_rows"].append(
                {
                    "task_id": task_id,
                    "loss": estimate["loss"],
                    "model_digest": model.digest,
                }
            )
            record["credit_transport_digest"] = estimate["credit_transport_digest"]
            model, receipt = credit.propose(model, estimate["gradients"])
            record["counts"]["optimizer_updates"] += 1
            record["counts"]["changed_updates"] += int(not receipt["no_update"])
            record["step_receipts"].append({"task_id": task_id, **receipt})
        stage = "evaluation"
        for task_id, inputs, targets, messages in evaluation:
            row = {"task_id": task_id, "initial_loss": None, "final_loss": None}
            record["evaluation_rows"].append(row)
            for name, evaluated in (("initial", initial), ("final", model)):
                record["counts"]["evaluation_forwards_started"] += 1
                _, outputs = credit.forward(evaluated, inputs, messages)
                loss = float(0.5 * np.sum(feedback[:, None] * (outputs - targets) ** 2))
                if not np.isfinite(loss):
                    raise ArithmeticError("nonfinite evaluation loss")
                row[name + "_loss"] = loss
                record["counts"]["evaluation_forwards_completed"] += 1
        record["mean_evaluation_loss_change"] = float(
            np.mean(
                [
                    row["final_loss"] - row["initial_loss"]
                    for row in record["evaluation_rows"]
                ]
            )
        )
        stage = "source_identity"
        record["source_at_end"] = source_inventory(_ROOT, _SOURCES)
        if record["source_at_end"] != _IMPORTED_SOURCE:
            raise RuntimeError("source changed during attempt")
        record["status"] = "completed"
    except Exception as error:
        record.update(
            status="failed",
            reason=type(error).__name__ + ": " + str(error),
            failure_stage=stage,
        )
    finally:
        record["final_model_digest"] = model.digest if model is not None else None
        record["counts"]["observation_coverage"] = (
            "complete_for_started_gradient_calls"
            if record["counts"]["gradient_calls_started"]
            == record["counts"]["gradient_calls_completed"]
            else "lower_bound_incomplete_gradient_call"
        )
        record["cost"] = {
            "wall_seconds": time.perf_counter() - started,
            "process_cpu_seconds": time.process_time() - cpu_started,
            "energy_joules": None,
            "peak_memory_bytes": None,
        }
    return record
