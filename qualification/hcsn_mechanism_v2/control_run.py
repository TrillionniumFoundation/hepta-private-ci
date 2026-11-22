"""Pure fit/final records for the common-review-clock study.

The outer campaign owns source admission, independent namespaces, selection
hash binding and the single-use final marker. Importing this module runs nothing.
No training oracle is used as a target, gradient, stopping rule or final selector.
"""

import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
import torch

from .control import enumerate_review_policies, fit_lookup_gate, return_affine
from .control import review_model, solve_review_control


def _digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _source_hashes():
    root = Path(__file__).parent
    return {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in ("control.py", "control_run.py")
    }


def _array_hash(value):
    return hashlib.sha256(
        str((value.shape, value.dtype)).encode() + value.tobytes()
    ).hexdigest()


def _json(value):
    if isinstance(value, torch.Tensor):
        return value.detach().cpu().tolist()
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


def _configuration(seed, cfg):
    options = cfg["control"]
    namespace = cfg["namespace"]
    if (
        type(seed) is not int
        or seed < 0
        or not isinstance(namespace, str)
        or len(namespace) < 32
        or namespace.startswith("hcsn-boundary-confirmatory-v1/")
    ):
        raise ValueError(
            "new root-assigned namespace and nonnegative integer seed required"
        )
    for field in ("intervals", "logit_limits"):
        values = options[field]
        if (
            not values
            or len(values) > 8
            or len(set(values)) != len(values)
            or any(not math.isfinite(x) or x <= 0 for x in values)
        ):
            raise ValueError("distinct positive finite clock/box grid required")
    if any(x > 30 for x in options["logit_limits"]):
        raise ValueError("logit limit exceeds the declared numerical range")
    for field in ("train_count", "dev_count", "final_count"):
        if type(options[field]) is not int or not 2 <= options[field] <= 100_000:
            raise ValueError("bounded independent observation counts required")
    if (
        type(options["max_steps"]) is not int
        or not 0 <= options["max_steps"] <= 131_072
        or options["checkpoints"] != sorted(set(options["checkpoints"]))
        or any(
            type(x) is not int or not 0 <= x <= options["max_steps"]
            for x in options["checkpoints"]
        )
    ):
        raise ValueError("bounded update budget and ordered fixed checkpoints required")
    for field in ("learning_rate", "value_tolerance", "arm_wall_seconds"):
        if not math.isfinite(options[field]) or options[field] <= 0:
            raise ValueError("positive finite optimization and wall limits required")
    return options, _digest({"namespace": namespace, "control": options})


def process():
    """The old known six-state plant; the review-time action law is new and explicit."""
    generator = torch.zeros(6, 6, dtype=torch.float64)
    for i in range(5):
        if i > 0:
            generator[i, i - 1] = 0.45 + 0.1 * (4 - i)
        if i < 4:
            generator[i, i + 1] = 0.65 + 0.05 * i
        generator[i, 5] = (0.6, 0.3, 0.1, 0.05, 0.02)[i]
    generator[5, 2] = 2.0
    generator -= torch.diag(generator.sum(1))
    return (
        generator,
        generator.new_tensor([-0.12, -0.10, -0.08, -0.10, -0.12]),
        0.3,
        generator.new_tensor([0.2, 0.2, 0.2, 0.2, 0.1, 0.1]),
    )


def observations(namespace, seed, split, count):
    """Separate state-probe noise for each split; no QVI or policy-derived reward."""
    if split not in ("train", "dev", "final"):
        raise ValueError("named independent split required")

    def generator(label):
        raw = hashlib.sha256(
            f"{namespace}/review-control/{seed}/{label}".encode()
        ).digest()[:8]
        return np.random.default_rng(int.from_bytes(raw, "little"))

    plant = np.array([-0.8, 0.25, -0.25, 0.7, 0.35, -0.04]) + generator("plant").normal(
        0, 0.08, 6
    )
    return plant[None] + generator(split).normal(0, 0.2, (count, 6))


def _method_record(result, model, initial, train_mean, dev_mean, baseline):
    started = time.perf_counter()
    coefficient, offset = return_affine(model, result["probability"], initial)
    training_return = float(coefficient @ train_mean + offset)
    development_return = float(coefficient @ dev_mean + offset)
    accepted = development_return > baseline["dev_return"]
    chosen = (
        result["probability"] if accepted else torch.zeros_like(result["probability"])
    )
    return {
        "candidate_probability": result["probability"].tolist(),
        "selected_probability": chosen.tolist(),
        "selection_status": "selected" if accepted else "no_update",
        "candidate_train_return": training_return,
        "candidate_dev_return": development_return,
        "selected_dev_return": development_return
        if accepted
        else baseline["dev_return"],
        "solver": _json(result),
        "selection_adjoint_solves": 1,
        "selection_wall_seconds": time.perf_counter() - started,
    }


def fit_case(seed, cfg):
    """Fit using train only; retain each candidate and fixed checkpoint before final."""
    started = time.perf_counter()
    options, identity = _configuration(seed, cfg)
    source = _source_hashes()
    generator, payoff, discount, initial = process()
    train = observations(cfg["namespace"], seed, "train", options["train_count"])
    dev = observations(cfg["namespace"], seed, "dev", options["dev_count"])
    train_mean, dev_mean = (
        torch.from_numpy(train.mean(0)),
        torch.from_numpy(dev.mean(0)),
    )
    shared = time.perf_counter() - started
    record = {
        "schema": "hcsn-review-control-v2",
        "seed": seed,
        "config_sha256": identity,
        "source_sha256": source,
        "namespace": cfg["namespace"],
        "process": {
            "G": generator.tolist(),
            "payoff": payoff.tolist(),
            "discount": discount,
            "initial": initial.tolist(),
            "reset_entry": 5,
        },
        "clock": "fixed_review_epochs_with_complete_post_action_interval",
        "train_sha256": _array_hash(train),
        "dev_sha256": _array_hash(dev),
        "train_observations": train.tolist(),
        "dev_observations": dev.tolist(),
        "train_mean": train_mean.tolist(),
        "dev_mean": dev_mean.tolist(),
        "clocks": [],
    }
    costs = {
        "common_setup_seconds": shared,
        "kernel_wall_seconds": 0.0,
        "kernel_linear_solves": 0,
        "kernel_matrix_exponentials": 0,
        "oracle_linear_solves": 0,
        "oracle_wall_seconds": 0.0,
        "method_linear_solves": 0,
        "backward_passes": 0,
        "selection_adjoint_solves": 0,
    }
    solver_options = {
        "value_tolerance": options["value_tolerance"],
        "max_evaluations": options["max_steps"] + 1,
        "wall_seconds": options["arm_wall_seconds"],
    }
    for interval in options["intervals"]:
        clock_start = time.perf_counter()
        model = review_model(
            generator,
            payoff,
            discount=discount,
            interval=interval,
            active_count=5,
            reset_entry=5,
        )
        kernel_seconds = time.perf_counter() - clock_start
        costs["kernel_wall_seconds"] += kernel_seconds
        costs["kernel_linear_solves"] += 1
        costs["kernel_matrix_exponentials"] += 1
        coefficient, offset = return_affine(model, generator.new_zeros(5), initial)
        baseline = {
            "train_return": float(coefficient @ train_mean + offset),
            "dev_return": float(coefficient @ dev_mean + offset),
            "probability": [0.0] * 5,
        }
        costs["selection_adjoint_solves"] += 1
        hard = solve_review_control(model, train_mean, **solver_options)
        hard_record = _method_record(
            hard, model, initial, train_mean, dev_mean, baseline
        )
        hard_oracle = enumerate_review_policies(model, train_mean, initial)
        clock = {
            "interval": interval,
            "beta": model.beta,
            "never_reset": baseline,
            "hard_review": hard_record,
            "hard_oracle": _json(hard_oracle),
            "boxes": [],
        }
        costs["method_linear_solves"] += hard["linear_solves"]
        costs["selection_adjoint_solves"] += 1
        costs["oracle_linear_solves"] += hard_oracle["linear_solves"]
        costs["oracle_wall_seconds"] += hard_oracle["wall_seconds"]
        for limit in options["logit_limits"]:
            floor = torch.sigmoid(generator.new_tensor(-limit)).item()
            bounded = solve_review_control(
                model, train_mean, probability_floor=floor, **solver_options
            )
            gate = fit_lookup_gate(
                model,
                train_mean,
                initial,
                logit_limit=limit,
                max_steps=options["max_steps"],
                learning_rate=options["learning_rate"],
                value_tolerance=options["value_tolerance"],
                wall_seconds=options["arm_wall_seconds"],
                checkpoints=options["checkpoints"],
            )
            oracle = enumerate_review_policies(
                model, train_mean, initial, probability_floor=floor
            )
            methods = {
                name: _method_record(
                    result, model, initial, train_mean, dev_mean, baseline
                )
                for name, result in (
                    ("bounded_review", bounded),
                    ("lookup_gate_bp", gate),
                )
            }
            hard_return, bounded_return = (
                initial @ hard_oracle["value"],
                initial @ oracle["value"],
            )
            gate_return = initial @ gate["value"]
            clock["boxes"].append(
                {
                    "logit_limit": limit,
                    "probability_floor": floor,
                    "methods": methods,
                    "bounded_oracle": _json(oracle),
                    "training_gap_decomposition": {
                        "hard_minus_bounded_optimum": float(
                            hard_return - bounded_return
                        ),
                        "bounded_optimum_minus_bp": float(bounded_return - gate_return),
                        "hard_optimum_minus_bp": float(hard_return - gate_return),
                        "hard_howard_oracle_sup_error": float(
                            (hard["value"] - hard_oracle["value"]).abs().max()
                        ),
                        "bounded_howard_oracle_sup_error": float(
                            (bounded["value"] - oracle["value"]).abs().max()
                        ),
                    },
                }
            )
            costs["method_linear_solves"] += (
                bounded["linear_solves"] + gate["linear_solves"]
            )
            costs["backward_passes"] += gate["backward_passes"]
            costs["selection_adjoint_solves"] += 2
            costs["oracle_linear_solves"] += oracle["linear_solves"]
            costs["oracle_wall_seconds"] += oracle["wall_seconds"]
        record["clocks"].append(clock)
    costs["case_wall_seconds"] = time.perf_counter() - started
    record["cost"] = costs
    return record


def final_case(record, seed, cfg):
    """Evaluate locked candidates/selected policies/checkpoints; never choose using final.

    Variation over final rows is reward-measurement uncertainty, not independent
    retraining. The training optimum decomposition is NOT a final generalization
    decomposition. The outer coordinator must consume its marker before calling.
    """
    started = time.perf_counter()
    options, identity = _configuration(seed, cfg)
    if (
        record["schema"] != "hcsn-review-control-v2"
        or record["seed"] != seed
        or record["config_sha256"] != identity
        or record["source_sha256"] != _source_hashes()
        or record["namespace"] != cfg["namespace"]
    ):
        raise ValueError(
            "final requires the original bound fit record and unchanged source/config"
        )
    samples = observations(cfg["namespace"], seed, "final", options["final_count"])
    generator, payoff, discount, initial = process()
    output = {
        "schema": "hcsn-review-control-final-v2",
        "seed": seed,
        "config_sha256": identity,
        "source_sha256": record["source_sha256"],
        "reward_sha256": _array_hash(samples),
        "reward_observations": samples.tolist(),
        "clocks": [],
        "claim_scope": "fixed policies, common review clock, independent reward probes",
    }
    solves, cache_hits = 0, 0
    for fitted in record["clocks"]:
        model = review_model(
            generator,
            payoff,
            discount=discount,
            interval=fitted["interval"],
            active_count=5,
            reset_entry=5,
        )
        cache = {}

        def measure(probability):
            nonlocal solves, cache_hits
            key = tuple(probability)
            if key in cache:
                cache_hits += 1
                return cache[key]
            coefficient, offset = return_affine(
                model, generator.new_tensor(probability), initial
            )
            values = samples @ coefficient.numpy() + float(offset)
            result = {
                "probability": list(probability),
                "mean_full_return": float(values.mean()),
                "measured_returns": values.tolist(),
                "affine_reward_coefficient": coefficient.tolist(),
                "affine_offset": float(offset),
                "policy_sha256": _digest(list(probability)),
            }
            cache[key], solves = result, solves + 1
            return result

        def evaluate_method(arm):
            return {
                "selection_status": arm["selection_status"],
                "solver_status": arm["solver"]["status"],
                "candidate": measure(arm["candidate_probability"]),
                "selected": measure(arm["selected_probability"]),
            }

        baseline = measure([0.0] * 5)
        clock = {
            "interval": fitted["interval"],
            "beta": fitted["beta"],
            "never_reset": baseline,
            "hard_review": evaluate_method(fitted["hard_review"]),
            "boxes": [],
        }
        for box in fitted["boxes"]:
            methods = {
                name: evaluate_method(arm) for name, arm in box["methods"].items()
            }
            curve = [
                {
                    "steps": row["steps"],
                    "training_residual_bound": row["residual_bound"],
                    "training_wall_seconds": row["wall_seconds"],
                    "measurement": measure(row["probability"]),
                }
                for row in box["methods"]["lookup_gate_bp"]["solver"]["trace"]
            ]
            clock["boxes"].append(
                {
                    "logit_limit": box["logit_limit"],
                    "methods": methods,
                    "frozen_budget_curve": curve,
                }
            )
        output["clocks"].append(clock)
    output["cost"] = {
        "final_policy_adjoint_solves": solves,
        "identical_policy_cache_hits": cache_hits,
        "kernel_matrix_exponentials": len(output["clocks"]),
        "kernel_linear_solves": len(output["clocks"]),
        "reward_vector_evaluations": solves * len(samples),
        "case_wall_seconds": time.perf_counter() - started,
    }
    return output
