"""Small FP64 NDU training diagnostic for one exportable v4 checkpoint.

All tasks, weights and uncalibrated critics are numerical fixtures. The report
proves local gradient/update wiring, not semantic quality or NDU efficacy.
"""

from copy import deepcopy
import hashlib

import torch

from scripts.joint_generation_v4_io import DeliveryObservation
from scripts.joint_generation_v4_model import JointGeneratorV4
from scripts.joint_generation_v4_ndu import choose, live_state, loss_terms, policy_improvement_loss


GROUPS = {
    "core": ("core.",),
    "ordered_text_shared_recurrence": ("text_recurrent.",),
    "token_embedding": ("token_encoder.",),
    "text_decoder_condition": ("text_condition.",),
    "text_emission_head": ("emissions.text.",),
    "actor": ("actor.",),
    "critics": ("critic.", "delivery_critic."),
}


def fixture():
    with torch.random.fork_rng():
        torch.manual_seed(811)
        # The admitted native generation bridge supports this exact selected
        # profile; a smaller tensor kernel is not a deployable checkpoint.
        generator = JointGeneratorV4(width=32, depth=1)
    public = {name: torch.zeros(shape, dtype=torch.float64) for name, shape in (
        ("image", (1, 3, 16, 16)), ("image_mask", (1, 3, 16, 16)),
        ("audio", (1, 1024)), ("audio_mask", (1, 1024)),
        ("video", (1, 4, 3, 16, 16)), ("video_mask", (1, 4, 3, 16, 16)))}
    public["tokens"] = torch.tensor([list("ab世界".encode("utf-8"))], dtype=torch.float64)
    owner = DeliveryObservation(15, 0, 1_000_000, 998_000, b"\x09" * 32)
    return generator, public, owner


def checkpoint_hash(generator):
    return hashlib.sha256(generator.export_weights()).hexdigest()


def frozen_copy(generator):
    reference = deepcopy(generator).eval()
    reference.requires_grad_(False)
    return reference


def group_statistics(tensors):
    result = {}
    for group, prefixes in GROUPS.items():
        values = [tensor.detach().flatten() for name, tensor in tensors.items()
                  if name.startswith(prefixes) and tensor is not None]
        values = torch.cat(values) if values else torch.zeros(1, dtype=torch.float64)
        if not bool(torch.isfinite(values).all()):
            raise AssertionError(f"Nonfinite derivative/update in {group}")
        result[group] = {"max_abs": float(values.abs().max()), "l2": float(values.norm()),
                         "nonzero_elements": int(torch.count_nonzero(values))}
    return result


def _gradients(generator, losses):
    named = dict(generator.named_parameters())
    result = {}
    for name, loss in losses.items():
        values = torch.autograd.grad(loss, tuple(named.values()), allow_unused=True, retain_graph=True)
        result[name] = {key: None if value is None else value.detach().clone()
                        for key, value in zip(named, values, strict=True)}
    return result


def _require_ndu_paths(statistics, loss):
    required = ["core", "ordered_text_shared_recurrence", "token_embedding"]
    if loss == "policy":
        required.append("actor")
    for group in required:
        if statistics[group]["max_abs"] <= 1e-12:
            raise AssertionError(f"{loss} did not reach {group}")
    # Current hard byte emission has no derivative to these exclusive heads.
    for group in ("text_decoder_condition", "text_emission_head", "critics"):
        if statistics[group]["max_abs"] != 0:
            raise AssertionError(f"Unexpected {loss} derivative into {group}")


def finite_differences(generator, reference, public, owner, gradients, base_plan):
    """Check a fixed smooth branch, never differentiate moving detached Q."""
    target_scores, scored = base_plan.scores.detach().clone(), base_plan.scored
    checks = []
    coordinates = (
        ("recursive", "core.layers.0.drift_bias"),
        ("recursive", "text_recurrent.weight"),
        ("policy", "core.layers.0.drift_bias"),
        ("policy", "text_recurrent.weight"),
        ("policy", "actor.2.weight"),
        ("teacher_forced", "emissions.text.weight"),
    )
    named = dict(generator.named_parameters())
    for loss_name, parameter_name in coordinates:
        derivative = gradients[loss_name][parameter_name]
        if derivative is None or float(derivative.abs().max()) <= 1e-12:
            raise AssertionError(f"No diagnostic derivative: {loss_name}/{parameter_name}")
        index = int(derivative.abs().argmax())
        analytic = float(derivative.flatten()[index])
        parameter = named[parameter_name]
        original = float(parameter.detach().flatten()[index])

        def evaluate():
            state = live_state(generator, public)
            if loss_name == "recursive":
                plan = choose(reference, state, owner, public)
                return float(-plan.scores[plan.action]), plan.trace_sha256
            if loss_name == "policy":
                value = policy_improvement_loss(generator, state, owner, target_scores, scored)
            else:
                value = generator.text_loss(state, "Hepta🙂")[0]
            return float(value), None

        stable = False
        try:
            with torch.no_grad():
                for epsilon in (1e-6, 1e-7, 1e-8):
                    parameter.view(-1)[index] = original + epsilon
                    plus, plus_trace = evaluate()
                    parameter.view(-1)[index] = original - epsilon
                    minus, minus_trace = evaluate()
                    parameter.view(-1)[index] = original
                    stable = (loss_name != "recursive"
                              or plus_trace == minus_trace == base_plan.trace_sha256)
                    if stable:
                        break
        finally:
            with torch.no_grad():
                parameter.view(-1)[index] = original
        if not stable:
            raise AssertionError(f"No stable local discrete branch for {parameter_name}")
        numerical = (plus - minus) / (2 * epsilon)
        error = abs(analytic - numerical)
        tolerance = 2e-8 + 2e-5 * max(abs(analytic), abs(numerical))
        if error > tolerance:
            raise AssertionError(f"Central difference mismatch for {loss_name}/{parameter_name}: "
                                 f"autograd={analytic}, finite_difference={numerical}, error={error}")
        checks.append({"loss": loss_name, "parameter": parameter_name, "flat_index": index,
                       "epsilon": epsilon, "autograd": analytic, "central_difference": numerical,
                       "absolute_error": error, "tolerance": tolerance, "branch_stable": stable,
                       "policy_q_held_fixed": loss_name == "policy"})
    return checks


def train_fixture():
    generator, public, owner = fixture()
    reference = frozen_copy(generator)
    initial_hash, reference_hash = checkpoint_hash(generator), checkpoint_hash(reference)
    losses, plan = loss_terms(generator, reference, public, owner)
    derivatives = _gradients(generator, losses)
    statistics = {name: group_statistics(values) for name, values in derivatives.items()}
    for name in ("recursive", "policy"):
        _require_ndu_paths(statistics[name], name)
    checks = finite_differences(generator, reference, public, owner, derivatives, plan)
    initial_losses = {name: float(value.detach()) for name, value in losses.items()}
    del losses, derivatives, plan
    updates = []
    # Isolated real optimizer steps make NDU-induced updates distinguishable
    # from teacher forcing; all three affect the same final exportable model.
    for loss_name, learning_rate in (("recursive", 0.02), ("policy", 0.02), ("teacher_forced", 0.01)):
        before = {name: parameter.detach().clone() for name, parameter in generator.named_parameters()}
        optimizer = torch.optim.SGD(generator.parameters(), lr=learning_rate)
        optimizer.zero_grad(set_to_none=True)
        terms, current_plan = loss_terms(generator, reference, public, owner)
        terms[loss_name].backward()
        applied = group_statistics({name: parameter.grad for name, parameter in generator.named_parameters()})
        if loss_name != "teacher_forced":
            _require_ndu_paths(applied, loss_name)
        optimizer.step()
        deltas = group_statistics({name: parameter.detach() - before[name]
                                  for name, parameter in generator.named_parameters()})
        if loss_name != "teacher_forced":
            for group in ("core", "ordered_text_shared_recurrence", "token_embedding"):
                if deltas[group]["max_abs"] <= 1e-14:
                    raise AssertionError(f"No actual optimizer update for {loss_name}/{group}")
        updates.append({"loss": loss_name, "learning_rate": learning_rate,
                        "loss_before_update": float(terms[loss_name].detach()),
                        "reference_selected_action": current_plan.action,
                        "applied_gradients": applied, "parameter_updates": deltas})
    generator.zero_grad(set_to_none=True)
    if (checkpoint_hash(reference) != reference_hash
            or any(parameter.grad is not None or parameter.requires_grad for parameter in reference.parameters())):
        raise AssertionError("The frozen evaluator changed during training")
    final_hash = checkpoint_hash(generator)
    if final_hash == initial_hash:
        raise AssertionError("No checkpoint update")
    report = {
        "initial_checkpoint_sha256": initial_hash, "trained_checkpoint_sha256": final_hash,
        "frozen_reference_sha256_before": reference_hash, "frozen_reference_sha256_after": checkpoint_hash(reference),
        "frozen_reference_gradients_absent": True, "initial_losses": initial_losses,
        "per_loss_gradient_groups": statistics, "central_differences": checks, "optimizer_steps": updates,
        "recursive_objective": "-max_a Q_frozen_reference(z_live,a)",
        "policy_objective": "-sum_a pi_live(a|z_live,owner)*stop_gradient(Q_frozen_reference(z_live,a))",
        "live_state": "ordered-input encoding followed by persistent shared and text content actions",
        "text_gradient_path": "token embedding and text_recurrent are shared with the ordered input encoder",
        "discrete_emission_gradient": "none through quantization/UTF-8 argmax; exclusive text heads use teacher forcing",
        "critic_calibration": "untrained synthetic predictions; no external quality calibration",
    }
    return generator, public, owner, report
