"""Online one-step bilevel learning of three surrogate hyperparameters.

The support pass is hard-spiking and uses an explicit SG weight update. The
outer query objective uses a fixed logistic-soft network and ordinary BCE. Raw
surrogate parameters do not enter that query objective directly: their gradient
passes through the actual support update. This is not MAML initialization
learning, nor a claim that a hard threshold has a classical derivative.
"""

import itertools
import time

import numpy as np

from .kernel import PARAMETER_NAMES, RAW_LIMIT, initial_raw, physical
from .network import initialize, loss_gradient, parameter_digest
from .task import make_batch


ARMS = ("standard", "fixed_theta", "meta_theta")
ADAM_BETA1, ADAM_BETA2, ADAM_EPSILON = 0.9, 0.999, 1e-8


def adapt(parameters, gradient, tangent, learning_rate, *, clip=5.0):
    """The actual projected SGD map and its derivative in the three raw inputs."""
    norm = float(np.sqrt(sum(np.sum(value**2) for value in gradient.values())))
    if not np.isfinite(norm) or not 0 < learning_rate <= 1 or clip <= 0:
        raise ValueError("finite gradient and bounded positive update required")
    scale = min(1.0, clip / max(norm, 1e-300))
    if tangent is not None:
        contraction = sum(
            np.sum(gradient[key][..., None] * value, axis=tuple(range(value.ndim - 1)))
            for key, value in tangent.items()
        )
    updated, sensitivity, projections = {}, {} if tangent is not None else None, 0
    for key, value in parameters.items():
        direction = gradient[key] * scale
        limit = 6.0 if key == "bias" else 3.0
        candidate = value - learning_rate * direction
        updated[key] = np.clip(candidate, -limit, limit)
        active = (candidate > -limit) & (candidate < limit)
        projections += int(np.sum(~active))
        if tangent is not None:
            derivative = scale * tangent[key]
            if norm > clip:
                derivative -= scale * gradient[key][..., None] * contraction / norm**2
            sensitivity[key] = -learning_rate * derivative * active[..., None]
    return (
        updated,
        sensitivity,
        {
            "gradient_norm": norm,
            "gradient_clipped": norm > clip,
            "projected_scalars": projections,
        },
    )


def bilevel_step(
    parameters,
    raw,
    support,
    query,
    *,
    family="first_passage",
    inner_rate=0.05,
    clip=5.0,
    learn_theta=True,
    query_weight_rate=0.0,
):
    support_loss, gradient, mixed, support_work = loss_gradient(
        parameters, support, raw, family, mixed=learn_theta
    )
    adapted, tangent, update = adapt(parameters, gradient, mixed, inner_rate, clip=clip)
    query_loss, query_gradient, _, query_work = loss_gradient(
        adapted, query, raw, "standard", soft=True
    )
    hyper = np.zeros(3)
    if learn_theta:
        for key, value in tangent.items():
            hyper += np.sum(
                query_gradient[key][..., None] * value,
                axis=tuple(range(value.ndim - 1)),
            )
    if not np.all(np.isfinite(hyper)):
        raise FloatingPointError("nonfinite outer hypergradient")
    query_update = None
    if query_weight_rate:
        adapted, _, query_update = adapt(
            adapted, query_gradient, None, query_weight_rate, clip=clip
        )
    return (
        adapted,
        hyper,
        {
            "support_hard_bce": support_loss,
            "query_fixed_soft_bce": query_loss,
            "support_work": support_work,
            "query_work": query_work,
            "support_dataset_sha256": support.digest,
            "query_dataset_sha256": query.digest,
            "inner_update": update,
            "query_weight_update": query_update,
            "query_weight_learning_rate": query_weight_rate,
        },
    )


def check_hypergradient(
    parameters, raw, support, query, *, epsilon=1e-4, inner_rate=0.05, clip=5.0
):
    """Independent whole-update finite differences of the actual soft outer loss."""
    _, analytic, _ = bilevel_step(
        parameters, raw, support, query, inner_rate=inner_rate, clip=clip
    )
    finite = np.zeros(3)
    for index in range(3):
        direction = np.zeros(3)
        direction[index] = epsilon
        losses = []
        for perturbed in (raw + direction, raw - direction):
            _, _, info = bilevel_step(
                parameters,
                perturbed,
                support,
                query,
                inner_rate=inner_rate,
                clip=clip,
                learn_theta=False,
            )
            losses.append(info["query_fixed_soft_bce"])
        finite[index] = (losses[0] - losses[1]) / (2 * epsilon)
    return {
        "epsilon": epsilon,
        "analytic": analytic.tolist(),
        "full_update_difference": finite.tolist(),
        "max_scaled_error": float(
            np.max(np.abs(analytic - finite) / (1 + np.abs(finite)))
        ),
        "analytic_chain_evaluations": 1,
        "full_update_evaluations": 6,
        "actual_neural_cell_updates": 7
        * (
            support.features.shape[0] * support.features.shape[1]
            + query.features.shape[0] * query.features.shape[1]
        )
        * 8,
    }


def train(seed, arm, protocol, *, progress=None):
    """One paired task schedule; no test selection or scientific I/O here."""
    if arm not in ARMS:
        raise ValueError("unknown registered training arm")
    config = protocol["training"]
    contexts = list(
        itertools.product(
            protocol["datasets"]["train_reliability"],
            protocol["datasets"]["train_cost"],
            protocol["datasets"]["train_deadline"],
        )
    )
    schedule = np.random.default_rng(np.random.SeedSequence([seed, 1703]))
    parameters, raw = initialize(seed), initial_raw()
    initial_parameters = {key: value.copy() for key, value in parameters.items()}
    initial_theta, _ = physical(raw)
    family = "standard" if arm == "standard" else "first_passage"
    history, cell_updates, surrogate_evaluations = [], 0, 0
    first_moment, second_moment = np.zeros(3), np.zeros(3)
    started, cpu_started = time.perf_counter(), time.process_time()
    for step_index in range(config["outer_steps"]):
        context = contexts[int(schedule.integers(len(contexts)))]
        support = make_batch(
            seed, step_index, "support", context, config["support_episodes"]
        )
        query = make_batch(seed, step_index, "query", context, config["query_episodes"])
        before_raw = raw.copy()
        parameters, hyper, information = bilevel_step(
            parameters,
            raw,
            support,
            query,
            family=family,
            inner_rate=config["inner_learning_rate"],
            clip=config["gradient_norm_clip"],
            learn_theta=arm == "meta_theta",
            query_weight_rate=config["query_weight_learning_rate"],
        )
        norm = float(np.linalg.norm(hyper))
        scale = min(1.0, config["hypergradient_norm_clip"] / max(norm, 1e-300))
        projected = 0
        outer_direction = np.zeros(3)
        if arm == "meta_theta":
            clipped_hyper = hyper * scale
            first_moment = ADAM_BETA1 * first_moment + (1 - ADAM_BETA1) * clipped_hyper
            second_moment = (
                ADAM_BETA2 * second_moment + (1 - ADAM_BETA2) * clipped_hyper**2
            )
            corrected_first = first_moment / (1 - ADAM_BETA1 ** (step_index + 1))
            corrected_second = second_moment / (1 - ADAM_BETA2 ** (step_index + 1))
            outer_direction = corrected_first / (
                np.sqrt(corrected_second) + ADAM_EPSILON
            )
            proposed = raw - config["outer_learning_rate"] * outer_direction
            projected = int(np.sum(np.abs(proposed) >= RAW_LIMIT))
            raw = np.clip(proposed, -RAW_LIMIT, RAW_LIMIT)
        theta, jacobian = physical(raw)
        delta = float(np.hypot(theta[0], np.sqrt(2 * theta[2]) * theta[1]))
        row = {
            "step": step_index + 1,
            "context": list(context),
            "hypergradient": hyper.tolist(),
            "hypergradient_norm": norm,
            "hypergradient_clipped": norm > config["hypergradient_norm_clip"],
            "raw_before": before_raw.tolist(),
            "raw_after": raw.tolist(),
            "raw_projected_scalars": projected,
            "outer_first_moment": first_moment.tolist(),
            "outer_second_moment": second_moment.tolist(),
            "outer_bias_corrected_direction": outer_direction.tolist(),
            "physical_after": dict(zip(PARAMETER_NAMES, theta.tolist())),
            "minimum_parameterization_jacobian": float(np.min(jacobian)),
            "inverse_diffusion_discriminant": 1 / delta,
            **information,
        }
        history.append(row)
        for part in (information["support_work"], information["query_work"]):
            cell_updates += part["cell_updates"]
            surrogate_evaluations += part["surrogate_scalar_evaluations"]
        if progress is not None:
            progress(step_index + 1, parameters, raw, row)
    final_theta, _ = physical(raw)
    stats = {
        "training_wall_seconds": time.perf_counter() - started,
        "training_cpu_seconds": time.process_time() - cpu_started,
        "outer_steps": config["outer_steps"],
        "support_updates": config["outer_steps"],
        "query_weight_updates": config["outer_steps"],
        "query_weight_learning_rate": config["query_weight_learning_rate"],
        "outer_optimizer": {
            "kind": "adam",
            "beta1": ADAM_BETA1,
            "beta2": ADAM_BETA2,
            "epsilon": ADAM_EPSILON,
            "learning_rate": config["outer_learning_rate"],
        },
        "actual_neural_cell_updates": cell_updates,
        "surrogate_scalar_evaluations": surrogate_evaluations,
        "parameter_count": sum(value.size for value in parameters.values()),
        "neural_parameter_count": sum(value.size for value in parameters.values()),
        "trainable_surrogate_parameters": 3 if arm == "meta_theta" else 0,
        "total_trainable_scalars": sum(value.size for value in parameters.values())
        + (3 if arm == "meta_theta" else 0),
        "initial_theta": dict(zip(PARAMETER_NAMES, initial_theta.tolist())),
        "final_theta": dict(zip(PARAMETER_NAMES, final_theta.tolist())),
        "physical_theta_change": dict(
            zip(PARAMETER_NAMES, (final_theta - initial_theta).tolist())
        ),
        "weight_change_l2": float(
            np.sqrt(
                sum(
                    np.sum((parameters[key] - initial_parameters[key]) ** 2)
                    for key in parameters
                )
            )
        ),
        "parameter_sha256": parameter_digest(parameters),
        "history": history,
        "outer_objective": "Independent-query fixed logistic-soft BCE after one hard-SNN SG support step; no direct theta term.",
    }
    return parameters, raw, stats
