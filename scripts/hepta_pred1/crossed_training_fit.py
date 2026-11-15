"""One crossed train/dev fit, with independently seeded initialization and order.

This stage retains fixed-budget optimization, full Adam checkpoint state, both
resource panels and failed attempts. It never generates confirmation material.
"""

import copy
from dataclasses import replace
from hashlib import sha256
import os
from pathlib import Path
from time import perf_counter, process_time

import numpy as np

from .crossed_design import canonical, transform_inputs
from .evaluation import evaluate
from .models import Model, matched_hidden_dim
from .preparation import PreparationTariff, evaluate_development_preparations
from .simulator import ACTION_DIM, INPUT_DIM


def _write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())


def model_digest(model, optimizer=False):
    """Hash numerical state, independent of ZIP timestamps or checkpoint paths."""
    digest = sha256()
    groups = {"parameters": model.params}
    if optimizer:
        groups.update(first_moment=model.m, second_moment=model.v)
        digest.update(
            canonical({"config": model.config, "steps": model.steps}).encode()
        )
    for group, values in sorted(groups.items()):
        for name, value in sorted(values.items()):
            array = np.asarray(value, dtype="<f8", order="C")
            digest.update(
                canonical([group, name, list(array.shape), array.dtype.str]).encode()
            )
            digest.update(array.tobytes())
    return digest.hexdigest()


def fit(config, variant, seeds, train, dev, directory):
    """Train one immutable cell, retaining all epochs and selected Adam state."""
    data_seed, init_seed, order_seed = seeds
    name = f"{variant}-d{data_seed}-i{init_seed}-o{order_seed}"
    out = Path(directory)
    identity = dict(
        variant=variant, data_seed=data_seed, init_seed=init_seed, order_seed=order_seed
    )
    _write(out / f"{name}.started.json", identity)
    started_wall, started_cpu = perf_counter(), process_time()
    model, curve, calls, examples = None, [], 0, 0
    try:
        kind = (
            variant
            if variant in ("single_step", "gru", "diag_ssm", "dual_timescale")
            else "gru"
        )
        hidden = matched_hidden_dim(
            kind, INPUT_DIM, ACTION_DIM, 32, config["target_parameters"]
        )
        model = Model(kind, INPUT_DIM, ACTION_DIM, 32, hidden, init_seed)
        initial_digest = model_digest(model)
        x, query, reset = transform_inputs(train.x, train.query, variant)
        dx, dq, dev_reset = transform_inputs(dev.x, dev.query, variant)
        if reset != dev_reset:
            raise AssertionError("training and development ablation disagree")
        visible_dev = replace(dev, x=dx, query=dq)
        order_rng, order_hash = np.random.default_rng(order_seed), sha256()
        selected, best_loss, best_epoch = None, np.inf, None
        wall, cpu = perf_counter(), process_time()
        for epoch in range(config["epochs"]):
            order = order_rng.permutation(len(x)).astype("<i8")
            order_hash.update(order.tobytes())
            total_loss = 0.0
            for start in range(0, len(order), config["batch_size"]):
                batch = order[start : start + config["batch_size"]]
                loss = model.fit_step(
                    x[batch],
                    query[batch],
                    train.allowed[batch],
                    lr=config["learning_rate"],
                    reset=reset,
                )
                calls += 1
                examples += len(batch)
                total_loss += loss * len(batch)
            logits = model.forward(dx, dq, reset=reset)
            nll = float(
                (
                    np.logaddexp.reduce(logits, axis=1)
                    - np.logaddexp.reduce(
                        np.where(dev.allowed, logits, -np.inf), axis=1
                    )
                ).mean()
            )
            if not np.isfinite(nll):
                raise FloatingPointError("nonfinite development NLL")
            curve.append(
                dict(
                    epoch=epoch + 1, train_nll=total_loss / len(x), dev_observed_nll=nll
                )
            )
            if nll < best_loss:
                selected, best_loss, best_epoch = copy.deepcopy(model), nll, epoch + 1
        train_wall, train_cpu = perf_counter() - wall, process_time() - cpu
        checkpoint = out / f"{name}.npz"
        checksum = selected.save(checkpoint)
        reloaded = Model.load(checkpoint)
        if model_digest(selected, optimizer=True) != model_digest(
            reloaded, optimizer=True
        ):
            raise AssertionError("checkpoint numerical state failed roundtrip")
        legacy, _ = evaluate(
            reloaded,
            visible_dev,
            reset=reset,
            mask_candidate_action=variant == "gru_no_action",
        )
        legacy["oracle_information"] = (
            "original full-history simulator posterior; common reference, "
            "not an information-matched oracle for ablated inputs"
        )
        tariff = PreparationTariff(**config["cost_profile"])
        expanded = replace(
            visible_dev,
            remaining_budget=np.full(len(dx), config["expanded_budget"]),
            deadline=np.full(len(dx), config["expanded_deadline"]),
        )
        panels = {}
        for panel, dataset in (
            ("original_resources", visible_dev),
            ("expanded_resources", expanded),
        ):
            panels[panel] = evaluate_development_preparations(
                reloaded,
                dataset,
                fixed1_tariff=tariff,
                reset=reset,
                mask_candidate_action=variant == "gru_no_action",
            )
        panels["expanded_resources"]["resource_intervention"] = {
            "remaining_budget": config["expanded_budget"],
            "deadline": config["expanded_deadline"],
            "scope": "same development outcomes with declared enlarged resources; no new independent task",
        }
        record = {
            **identity,
            "status": "COMPLETE",
            "hidden_dim": hidden,
            "parameters": model.parameter_count,
            "initial_parameter_sha256": initial_digest,
            "batch_order_sha256": order_hash.hexdigest(),
            "selected_parameter_sha256": model_digest(reloaded),
            "selected_optimizer_state_sha256": model_digest(reloaded, optimizer=True),
            "checkpoint": checkpoint.name,
            "checkpoint_sha256": checksum,
            "best_epoch": best_epoch,
            "dev_observed_nll": best_loss,
            "curve": curve,
            "epochs_consumed": config["epochs"],
            "fit_step_calls_consumed": calls,
            "optimizer_steps_consumed": model.steps,
            "selected_checkpoint_steps": reloaded.steps,
            "training_examples_consumed": examples,
            "train_wall_seconds": train_wall,
            "train_process_cpu_seconds": train_cpu,
            "train_timing_scope": "optimization plus each epoch's observed-label dev NLL and best-state copy",
            "dev": legacy,
            "resource_panels": panels,
            "metering": {
                "fit_total_wall_seconds": perf_counter() - started_wall,
                "fit_total_process_cpu_seconds": process_time() - started_cpu,
                "physical_cost_complete": False,
                "energy_joules": None,
                "financial_cost": None,
            },
        }
        _write(out / f"{name}.json", record)
        return record
    except Exception as error:
        failure = {
            **identity,
            "status": "FAILED",
            "error_type": type(error).__name__,
            "error": str(error),
            "curve": curve,
            "fit_step_calls_completed": calls,
            "examples_completed": examples,
            "optimizer_steps_observed": None if model is None else model.steps,
            "failed_fit_wall_seconds": perf_counter() - started_wall,
            "failed_fit_process_cpu_seconds": process_time() - started_cpu,
            "partial_failing_step_accounting": "unknown; completed counters are lower bounds",
        }
        _write(out / f"{name}.failed.json", failure)
        return failure
