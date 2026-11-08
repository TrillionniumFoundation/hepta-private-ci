"""Metered fits with episode-local unrolls and a frozen recursive reference."""

from collections import Counter
import copy
import json
import math
import random
import time

from .controllers import ControlPlan
from .objective import utility_profile
from .trajectory import V2_SCHEMA, episode_groups, grouped_batches


def train_epochs(
    model,
    rows,
    config,
    *,
    phase,
    seed,
    regime,
    controller,
    meter,
    output,
    deadline,
    plan=None,
):
    import torch
    from .recursive_objective import observed_states, recursive_terms
    from .training import control_terms, parameter_sha, supervised_terms, _save_weights

    plan = plan or ControlPlan(latency_weight=config.latency_weight)
    selected = (
        [r for r in rows if r["first_content"]]
        if phase == "content" and plan.memory_mode == "reset"
        else rows
    )
    sequences = episode_groups(selected, plan.memory_mode)
    content = [p for p in model.content_parameters() if p.requires_grad]
    content_ids = {id(p) for p in model.content_parameters()}
    heads = (
        []
        if phase == "content"
        else [
            p
            for p in model.parameters()
            if p.requires_grad and id(p) not in content_ids
        ]
    )
    groups = ([{"params": content, "lr": config.content_lr}] if content else []) + (
        [{"params": heads, "lr": config.lr}] if heads else []
    )
    optimizer = torch.optim.Adam(groups)
    epoch_count = config.content_epochs if phase == "content" else config.fit_epochs
    recursive = (
        phase == "fit"
        and regime == "joint"
        and controller in {"ndu", "ndu_policy"}
        and all(row["schema"] == V2_SCHEMA for row in selected)
    )
    if recursive and epoch_count < 2:
        raise ValueError(
            "Recursive fit needs an observed-reference warmup and at least one improvement epoch"
        )
    if controller == "ndu_policy" and phase == "fit" and not recursive:
        raise ValueError("NDU policy deployment requires v2 recursive joint training")
    generator = random.Random(seed ^ (0xC017E17 if phase == "content" else 0xF17))
    audit = {
        "control_gradient_into_content": None,
        "optimizer_steps": 0,
        "epochs": [],
        "memory_mode": plan.memory_mode,
        "utility_profile": utility_profile(plan),
        "recursive_objective_applied": recursive,
        "estimator": "frozen_model_recursive_gradient_and_exact_frozen_Q_policy_improvement"
        if recursive
        else "observed_auxiliary_losses",
        "environment_unbiased_policy_gradient": False,
    }
    reference = None
    for epoch in range(epoch_count):
        if recursive and epoch == 1:
            with meter.stage(
                "critic",
                "fit residuals and freeze observed reference for remaining epochs",
            ):
                reference = copy.deepcopy(model).eval()
                audit["reference_residuals"] = estimate_residuals(
                    reference, rows, deadline, plan=plan
                )
                for parameter in reference.parameters():
                    parameter.requires_grad_(False)
                    parameter.grad = None
                audit["reference_parameter_sha256"] = parameter_sha(reference)
                audit["reference_weights_sha256"] = _save_weights(
                    reference, output / "recursive-reference-weights.pt"
                )
                audit["reference_warmup_epochs"] = 1
                audit["truncation"] = {
                    "horizon": plan.horizon,
                    "max_forecasts": plan.max_forecasts,
                    "particles": plan.particles,
                    "piecewise_fixed_legal_support": True,
                }
        order = list(range(len(sequences)))
        generator.shuffle(order)
        totals = Counter()
        for batch_groups in grouped_batches(sequences, order, config.batch_size):
            if time.perf_counter() > deadline:
                raise TimeoutError("Original finite fit budget exhausted")
            optimizer.zero_grad(set_to_none=True)
            with meter.stage(
                "shared", phase + " ordered current and observed-successor content"
            ):
                observed = observed_states(
                    model,
                    batch_groups,
                    plan.memory_mode,
                    include_successors=phase == "fit",
                )
            with meter.stage("decoder", phase + " train-only field and box loss"):
                task = [
                    supervised_terms(row, state[1], state[2])
                    for row, state, _ in observed
                ]
                loss = sum(ce + 4 * box for ce, box in task) / len(observed)
            controlled, probes = [], {}
            if phase == "fit":
                with meter.stage(
                    "critic",
                    "observed utility transition duration and light auxiliary losses",
                ):
                    auxiliary_controller = (
                        "shared" if recursive and reference is None else controller
                    )
                    head_losses = [
                        control_terms(
                            model,
                            row,
                            state[0],
                            following,
                            regime=regime,
                            controller=auxiliary_controller,
                            latency_weight=config.latency_weight,
                        )
                        for row, state, following in observed
                    ]
                    loss = loss + sum(item[0] for item in head_losses) / len(observed)
                    controlled = [
                        item[1] for item in head_losses if item[1] is not None
                    ]
                    for _, _, values in head_losses:
                        for name, value in values.items():
                            totals[name] += float(value.detach())
            if reference is not None:
                with meter.stage(
                    "planning",
                    "differentiable finite recursion against frozen fitted reference",
                ):
                    terms = [
                        recursive_terms(model, reference, state[0], row, plan, seed)
                        for row, state, _ in observed
                    ]
                    for index, name in enumerate(("recursive", "policy")):
                        term = sum(item[index] for item in terms) / len(observed)
                        probes[name + "_gradient_into_content"] = term
                        loss = loss + term
                        totals[name] += float(term.detach()) * len(observed)
                    totals["forecast_calls"] += sum(
                        item[2]["forecast_calls"] for item in terms
                    )
                    totals["planner_cap_hits"] += sum(
                        item[2]["planner_budget_exhausted"] for item in terms
                    )
            if controlled:
                probes["control_gradient_into_content"] = sum(controlled) / len(
                    controlled
                )
            for name, term in probes.items():
                if audit.get(name) is None:
                    with meter.stage("critic", "audit " + name):
                        gradients = torch.autograd.grad(
                            term, content, retain_graph=True, allow_unused=True
                        )
                        norm = (
                            sum(
                                float(g.detach().square().sum())
                                for g in gradients
                                if g is not None
                            )
                            ** 0.5
                        )
                        if not math.isfinite(norm) or norm <= 0:
                            raise ValueError(
                                name + " did not reach actual content parameters"
                            )
                        audit[name] = norm
            with meter.stage(
                "shared", phase + " single combined backward and optimizer step"
            ):
                if not bool(torch.isfinite(loss)):
                    raise ValueError("Nonfinite observed training objective")
                loss.backward()
                norms = [
                    float(
                        torch.nn.utils.clip_grad_norm_(
                            g["params"], 1.0, error_if_nonfinite=True
                        )
                    )
                    for g in groups
                ]
                gradient_norm = math.sqrt(sum(n * n for n in norms))
                optimizer.step()
            totals["objective"] += float(loss.detach()) * len(observed)
            totals["text_ce"] += sum(float(ce.detach()) for ce, _ in task)
            totals["bbox"] += sum(float(box.detach()) for _, box in task)
            totals["gradient_norm"] += gradient_norm * len(observed)
            audit["optimizer_steps"] += 1
        summary = {
            "phase": phase,
            "epoch": epoch,
            "examples": len(selected),
            "losses": {k: v / len(selected) for k, v in totals.items()},
            "content_parameter_sha256": parameter_sha(model, content_only=True),
        }
        audit["epochs"].append(summary)
        with (output / "epochs.jsonl").open("a") as stream:
            stream.write(json.dumps(summary, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
    if reference is not None:
        audit["frozen_reference_unchanged"] = (
            parameter_sha(reference) == audit["reference_parameter_sha256"]
        )
        if not audit["frozen_reference_unchanged"] or any(
            p.grad is not None for p in reference.parameters()
        ):
            raise ValueError("Recursive reference was updated")
    return audit


def estimate_residuals(model, rows, deadline, *, plan=None):
    import torch
    from .recursive_objective import observed_states

    plan = plan or ControlPlan()
    errors = []
    with torch.no_grad():
        for group in episode_groups(rows, plan.memory_mode):
            if time.perf_counter() > deadline:
                raise TimeoutError(
                    "Original finite fit budget exhausted during residual estimation"
                )
            for row, current, following in observed_states(
                model, [group], plan.memory_mode
            ):
                if following is not None:
                    predicted, _ = model.predict_transition(
                        current[0][None],
                        torch.tensor([row["action"]], device=current[0].device),
                    )
                    errors.append((predicted[0] - following).square())
        if not errors:
            raise ValueError(
                "No observed successors support a learned forecast residual"
            )
        scale = torch.stack(errors).mean(0).sqrt()
        model.residual_std.copy_(scale.clamp(0.001, 1.0))
    return {
        "observed_successors": len(errors),
        "method": "train residual RMS, not a coverage guarantee",
        "memory_mode": plan.memory_mode,
        "scale": model.residual_std.tolist(),
        "clipped_dimensions": int(((scale < 0.001) | (scale > 1)).sum()),
    }
