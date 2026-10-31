"""Source-disjoint fitting of conditional exponential-moment value heads."""

from collections import Counter
import hashlib
import math
from pathlib import Path
import time

import torch

from ..model import tensor_digest


def fit_validate_critics(model, training_results, validation_results, directory, *, updates=100,
                         learning_rate=1e-3, gradient_clip=5.0):
    """Fit only moment critics; untouched original sources assess calibration.

    Hyperparameters are fixed before fitting. Validation never selects updates,
    features, checkpoints or weights. The model is modified in place; all actor
    and generator tensors are checked unchanged. This is not policy training.
    """
    from .diagnostics import GAMMA, _save_tensors, _write_json, certainty_equivalent

    if (type(updates) is not int or updates < 1 or not math.isfinite(learning_rate)
            or learning_rate <= 0 or not math.isfinite(gradient_clip) or gradient_clip <= 0):
        raise ValueError("Fixed positive fitting hyperparameters are required")
    training_results, validation_results = list(training_results), list(validation_results)
    if not training_results or not validation_results:
        raise ValueError("Separate nonempty training and validation cohorts are required")
    source_sets = [{r["source_id"] for r in values} for values in (training_results, validation_results)]
    input_sets = [{r["input_sha256"] for r in values} for values in (training_results, validation_results)]
    if source_sets[0] & source_sets[1] or input_sets[0] & input_sets[1]:
        raise ValueError("Critic validation overlaps an original source or public input")
    model_hash = tensor_digest(model.state_dict())
    all_results = training_results + validation_results
    if any(r["model_sha256"] != model_hash for r in all_results) or len({r["profile_sha256"] for r in all_results}) != 1:
        raise ValueError("Critic fitting requires one frozen behavior model and objective")
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=False)
    protocol = {"updates": updates, "learning_rate": learning_rate, "gradient_clip": gradient_clip,
                "gamma": GAMMA, "loss": "source_uniform_mean(exp(v)-exp(-2*R_suffix)*v)",
                "training_sources": sorted(source_sets[0]), "validation_sources": sorted(source_sets[1]),
                "model_before_sha256": model_hash, "validation_selection": False}
    _write_json(directory / "FROZEN_FIT_PROTOCOL.json", protocol)
    cohorts, exclusions = {}, {}
    for role, results in (("training", training_results), ("validation", validation_results)):
        rows = [row for result in results for row in result["rows"]]
        exclusions[role] = sum(not r["critic_fit_available"] for r in rows)
        counts = Counter(r["source_id"] for r in rows if r["critic_fit_available"])
        if set(counts) != source_sets[0 if role == "training" else 1]:
            raise ValueError("A source has no valid pre-critic observations; do not silently discard it")
        cohorts[role] = {}
        for head in ("critic", "delivery_critic"):
            selected = [r for r in rows if r["critic_fit_available"] and r["critic_fit_head"] == head]
            if not selected:
                continue
            parameter = next(getattr(model, head).parameters())
            x = torch.tensor([r["critic_fit_features"] for r in selected], dtype=parameter.dtype, device=parameter.device)
            y = torch.tensor([r["critic_fit_suffix_return"] for r in selected], dtype=parameter.dtype, device=parameter.device)
            weights = torch.tensor([1 / (len(counts) * counts[r["source_id"]]) for r in selected],
                                   dtype=parameter.dtype, device=parameter.device)
            if not torch.isfinite(x).all() or not torch.isfinite(y).all():
                raise ValueError("Nonfinite critic observations cannot be repaired or clipped")
            cohorts[role][head] = (x, y, weights)
        _save_tensors(directory / f"{role.upper()}_FIT_DATA.npz", cohorts[role])

    def metrics(role):
        report = {}
        with torch.no_grad():
            for head, (x, y, weights) in cohorts[role].items():
                v = getattr(model, head)(x)[:, 0]
                target, prediction = torch.exp(-GAMMA * y), v.exp()
                if not torch.isfinite(target).all() or not torch.isfinite(prediction).all():
                    raise ValueError("Moment overflow; no fitting/evaluation clipping is permitted")
                mass = weights / weights.sum()
                report[head] = {"proper_moment_loss": float((mass * (prediction - target * v)).sum()),
                    "weighted_moment_bias": float((mass * (prediction - target)).sum()), "samples": len(x),
                    "aggregate_ce_error": certainty_equivalent((-v / GAMMA).cpu(), mass.cpu())
                                           - certainty_equivalent(y.cpu(), mass.cpu()),
                    "aggregate_calibration_is_not_a_statewise_guarantee": True}
        return report

    frozen = {n: v.detach().clone() for n, v in model.state_dict().items()
              if not n.startswith(("critic.", "delivery_critic."))}
    parameters = [p for head in cohorts["training"] for p in getattr(model, head).parameters()]
    if not all(p.requires_grad for p in parameters):
        raise ValueError("Critic parameters must be explicitly trainable")
    before = {role: metrics(role) for role in cohorts}
    optimizer = torch.optim.Adam(parameters, lr=learning_rate)
    started, logs = time.perf_counter(), []
    for update in range(updates):
        losses = []
        for head, (x, y, weights) in cohorts["training"].items():
            value = getattr(model, head)(x)[:, 0]
            losses.append((weights * (value.exp() - torch.exp(-GAMMA * y) * value)).sum())
        loss = torch.stack(losses).sum()
        if not torch.isfinite(loss):
            raise ValueError("Nonfinite proper moment objective")
        optimizer.zero_grad(set_to_none=True); loss.backward()
        norm = torch.nn.utils.clip_grad_norm_(parameters, gradient_clip, error_if_nonfinite=True)
        optimizer.step()
        logs.append({"update": update, "loss": float(loss.detach()), "gradient_norm": float(norm)})
    if any(not torch.equal(model.state_dict()[name], value) for name, value in frozen.items()):
        raise ValueError("Moment fitting changed the generator or actor")
    path = directory / "CRITIC_STATE.pt"
    torch.save({n: v.detach().cpu() for n, v in model.state_dict().items()
                if n.startswith(("critic.", "delivery_critic."))}, path)
    result = {"schema": "hepta.joint-generation.critic-fit-validation.v3", "protocol": protocol,
              "before": before, "after": {role: metrics(role) for role in cohorts}, "updates": logs,
              "fitting_wall_seconds": time.perf_counter() - started, "excluded_incomplete_transitions": exclusions,
              "model_after_sha256": tensor_digest(model.state_dict()),
              "critic_checkpoint_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "generator_and_actor_unchanged": True, "heldout_source_overlap": False,
              "evidence_unit": "original_source; paired_or_repeated_continuations_are_not_new_tasks",
              "validation_used_for_selection": False, "policy_improvement_established": False,
              "research_effect_qualified": False}
    _write_json(directory / "FIT_VALIDATION.json", result)
    return result
