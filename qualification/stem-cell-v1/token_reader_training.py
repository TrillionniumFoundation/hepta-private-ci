"""Measured CPU training of token Readers; annotations never enter inference.

An optional synthetic intervention dataset supplies its own explicit labels.
Removing real evidence does not create a negative label. Formula work is unknown
here; receipts report actual process CPU, wall time, updates and tensor storage.
"""
import copy
from dataclasses import dataclass
import hashlib
import json
import math
import random
import time

import torch
from torch.nn import functional as F


@dataclass(frozen=True)
class TokenBatch:
    facts: torch.Tensor
    question: torch.Tensor
    candidate: torch.Tensor
    fact_mask: torch.Tensor
    question_mask: torch.Tensor
    candidate_mask: torch.Tensor
    targets: torch.Tensor
    source_groups: tuple = ()
    evidence_targets: torch.Tensor = None
    evidence_supervision: torch.Tensor = None

    def features(self):
        return (self.facts, self.question, self.candidate, self.fact_mask,
                self.question_mask, self.candidate_mask)

    def model_args(self):
        return self.features()

    def validate(self, input_dim, allow_empty=False):
        size = len(self.targets)
        if (not size and not allow_empty) or self.targets.shape != (size,) or self.targets.dtype != torch.long:
            raise ValueError("nonempty binary token Reader labels required")
        if self.facts.ndim != 4 or self.question.ndim != 3 or self.candidate.ndim != 3:
            raise ValueError("distinct evidence, question and candidate tokens required")
        for value, mask in ((self.facts, self.fact_mask), (self.question, self.question_mask),
                            (self.candidate, self.candidate_mask)):
            if (value.shape[0] != size or value.shape[-1] != input_dim or mask.shape != value.shape[:-1]
                    or mask.dtype != torch.bool or value.dtype != torch.float32
                    or value.device.type != "cpu" or mask.device.type != "cpu" or value.requires_grad
                    or not torch.isfinite(value).all()):
                raise ValueError("detached finite CPU FP32 tokens and boolean masks required")
        if (self.targets.device.type != "cpu" or self.targets.requires_grad
                or not ((self.targets == 0) | (self.targets == 1)).all()
                or (self.source_groups and (len(self.source_groups) != size
                    or any(not isinstance(group, str) or not group for group in self.source_groups)))):
            raise ValueError("binary detached labels and aligned source groups required")
        if (self.evidence_targets is None) != (self.evidence_supervision is None):
            raise ValueError("evidence targets require an explicit supervision mask")
        if self.evidence_targets is not None:
            target, supervised = self.evidence_targets, self.evidence_supervision
            if (target.shape != self.facts.shape[:2] or supervised.shape != (size,)
                    or supervised.dtype != torch.bool or target.dtype != torch.float32
                    or target.device.type != "cpu" or supervised.device.type != "cpu"
                    or target.requires_grad or not torch.isfinite(target).all() or (target < 0).any()
                    or (target.masked_select(~self.fact_mask.any(-1)) != 0).any()
                    or not torch.allclose(target.sum(-1)[supervised], torch.ones_like(target.sum(-1)[supervised]))):
                raise ValueError("normalized, valid training-only evidence targets required")

    def take(self, indices):
        index = torch.tensor(indices, dtype=torch.long)
        groups = tuple(self.source_groups[i] for i in indices) if self.source_groups else ()
        return TokenBatch(*(value[index] for value in self.features()), self.targets[index], groups,
            None if self.evidence_targets is None else self.evidence_targets[index],
            None if self.evidence_supervision is None else self.evidence_supervision[index])


def parameter_digest(model):
    digest = hashlib.sha256()
    for name, value in sorted(model.state_dict().items()):
        digest.update(name.encode())
        digest.update(str(tuple(value.shape)).encode())
        digest.update(value.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def _tensor_bytes(values):
    return sum(value.numel() * value.element_size() for value in values)


def _source_digest(groups):
    return hashlib.sha256(json.dumps(sorted(set(groups)), separators=(",", ":")).encode()).hexdigest()


def _evidence_loss(attention, batch):
    if batch.evidence_targets is None or not batch.evidence_supervision.any():
        return attention.sum() * 0
    selected = batch.evidence_supervision
    return -(batch.evidence_targets[selected] * attention[selected].clamp(min=1e-9).log()).sum(-1).mean()


def _fit_token_reader(model, train, validation=None, *, steps, seed, batch_size=16,
                     max_depth=1, learning_rate=.003, counterfactual_train=None,
                     counterfactual_fraction=.25, evidence_weight=0., diagnostic_interval=100,
                     wall_time_ns=180_000_000_000, progress=None):
    """Fit a copy using lazy ``take(indices)`` batches, then freeze its parameters.

    Training and diagnostic data must have disjoint source groups. Synthetic
    intervention sources are separately declared and cannot overlap diagnostics.
    Optimizer updates alternate natural and intervention minibatches, retaining
    dynamic padding and counting both sources' actual exposures. No validation
    labels or annotations enter an update, and validation never sets a threshold.
    """
    train.validate(model.input_dim)
    if validation is not None:
        validation.validate(model.input_dim)
    if counterfactual_train is not None:
        counterfactual_train.validate(model.input_dim)
    if (type(steps) is not int or not 1 <= steps <= 10000 or not 1 <= batch_size <= 4096
            or type(max_depth) is not int or not 1 <= max_depth <= model.max_hops
            or not 0 < learning_rate <= 1 or not 0 <= counterfactual_fraction < 1
            or not 0 <= evidence_weight <= 100 or type(diagnostic_interval) is not int
            or not 1 <= diagnostic_interval <= 10000 or type(wall_time_ns) is not int or wall_time_ns <= 0):
        raise ValueError("bounded token training schedule required")
    train_groups = set(train.source_groups)
    val_groups = set(validation.source_groups) if validation is not None else set()
    cf_groups = set(counterfactual_train.source_groups) if counterfactual_train is not None else set()
    if not train_groups or (validation is not None and not val_groups) or (counterfactual_train is not None and not cf_groups):
        raise ValueError("source ownership required for every dataset")
    if (train_groups | cf_groups) & val_groups:
        raise ValueError("fit and diagnostic source groups overlap")
    started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
    trained = copy.deepcopy(model).train()
    for parameter in trained.parameters():
        parameter.requires_grad_(True)
    opt = torch.optim.Adam(trained.parameters(), lr=learning_rate, foreach=False)
    rng, sample_digest = random.Random(seed), hashlib.sha256()
    updates, diagnostics, natural_exposures, intervention_exposures = [], [], 0, 0
    completed, status = 0, "completed"
    if progress is not None:
        progress.update(updates=updates, diagnostics=diagnostics)

    def evaluate(data):
        if data is None:
            return None
        before_wall, before_cpu = time.perf_counter_ns(), time.process_time_ns()
        correct, loss_sum, size = 0, 0., len(data.targets)
        with torch.no_grad():
            for start in range(0, size, batch_size):
                batch = data.take(list(range(start, min(size, start + batch_size))))
                logits = trained(*batch.features(), steps=max_depth)
                loss_sum += F.cross_entropy(logits, batch.targets).item() * len(batch.targets)
                correct += logits.argmax(-1).eq(batch.targets).sum().item()
        return dict(n=size, binary_cross_entropy=loss_sum / size, accuracy=correct / size,
                    cpu_ns=time.process_time_ns() - before_cpu, wall_ns=time.perf_counter_ns() - before_wall)

    diagnostics.append(dict(optimizer_step=0, train=evaluate(train), validation=evaluate(validation)))
    for update in range(steps):
        if time.perf_counter_ns() - started_wall >= wall_time_ns:
            status = "budget_stopped"
            break
        intervention = counterfactual_train is not None and rng.random() < counterfactual_fraction
        data = counterfactual_train if intervention else train
        indices = rng.sample(range(len(data.targets)), min(batch_size, len(data.targets)))
        depth = rng.randint(1, max_depth)
        sample_digest.update(repr((intervention, indices, depth)).encode())
        before_wall, before_cpu = time.perf_counter_ns(), time.process_time_ns()
        if progress is not None:
            progress["attempted_step"] = update + 1
        batch = data.take(indices)
        opt.zero_grad(set_to_none=True)
        trace = trained(*batch.features(), steps=depth, return_attention=True)
        losses = [F.cross_entropy(logits, batch.targets) for logits in trace["step_logits"]]
        evidence_losses = [_evidence_loss(attention, batch) for attention in trace["attentions"]]
        loss = torch.stack(losses).mean() + evidence_weight * torch.stack(evidence_losses).mean()
        if not torch.isfinite(loss):
            raise FloatingPointError("nonfinite token Reader training loss")
        for state in trace["states"]:
            state.retain_grad()
        loss.backward()
        if any(not torch.isfinite(p.grad).all() for p in trained.parameters() if p.grad is not None):
            raise FloatingPointError("nonfinite token Reader parameter gradient")
        grad_l2 = math.sqrt(sum((p.grad * p.grad).sum().item() for p in trained.parameters() if p.grad is not None))
        state_gradients = [math.sqrt((s.grad * s.grad).sum().item()) for s in trace["states"]]
        opt.step()
        completed += 1
        natural_exposures += len(indices) if not intervention else 0
        intervention_exposures += len(indices) if intervention else 0
        updates.append(dict(step=completed, depth=depth, intervention=intervention, exposures=len(indices),
            hop_binary_losses=[value.detach().item() for value in losses],
            hop_evidence_losses=[value.detach().item() for value in evidence_losses],
            parameter_gradient_l2=grad_l2, hop_state_gradient_l2=state_gradients,
            cpu_ns=time.process_time_ns() - before_cpu, wall_ns=time.perf_counter_ns() - before_wall))
        if progress is not None:
            progress.update(completed_steps=completed, actual_training_exposures=natural_exposures,
                            actual_intervention_exposures=intervention_exposures)
        if completed % diagnostic_interval == 0 and completed < steps:
            diagnostics.append(dict(optimizer_step=completed, train=evaluate(train), validation=evaluate(validation)))
    diagnostics.append(dict(optimizer_step=completed, train=evaluate(train), validation=evaluate(validation)))
    optimizer_bytes = sum(_tensor_bytes(value for value in state.values() if isinstance(value, torch.Tensor))
                          for state in opt.state.values())
    gradient_bytes = _tensor_bytes(p.grad for p in trained.parameters() if p.grad is not None)
    opt.zero_grad(set_to_none=True)
    trained.eval()
    for parameter in trained.parameters():
        parameter.requires_grad_(False)
    trained.training_source_groups = tuple(sorted(train_groups | cf_groups))
    receipt = dict(schema="hepta.token-reader.cpu-fit.v1", status=status, seed=seed,
        requested_steps=steps, completed_steps=completed, batch_size=batch_size, max_depth=max_depth,
        actual_training_exposures=natural_exposures, actual_intervention_exposures=intervention_exposures,
        actual_total_exposures=natural_exposures + intervention_exposures,
        sample_and_depth_sha256=sample_digest.hexdigest(), updates=updates, diagnostics=diagnostics,
        parameter_count=sum(p.numel() for p in trained.parameters()),
        parameter_bytes=_tensor_bytes(trained.parameters()), optimizer_tensor_bytes=optimizer_bytes,
        last_gradient_tensor_bytes=gradient_bytes, optimizer="Adam_foreach_false", learning_rate=learning_rate,
        model_sha256=parameter_digest(trained), interaction=trained.interaction,
        evidence_weight=evidence_weight,
        configured_intervention_update_probability=counterfactual_fraction,
        intervention_update_probability=counterfactual_fraction if counterfactual_train is not None else 0.,
        train_unique_sources=len(train_groups), validation_unique_sources=len(val_groups),
        intervention_unique_sources=len(cf_groups), train_validation_sources_verified=True,
        training_sources_sha256=_source_digest(train_groups),
        validation_sources_sha256=_source_digest(val_groups),
        intervention_sources_sha256=_source_digest(cf_groups),
        training_label_order_sha256=hashlib.sha256(torch.as_tensor(train.targets, dtype=torch.long).numpy().tobytes()).hexdigest(),
        validation_gradient_updates=0, annotations_enter_inference=False,
        depth_supervision="mean_binary_CE_plus_explicit_evidence_CE_all_executed_hops",
        cpu_ns=time.process_time_ns() - started_cpu, wall_ns=time.perf_counter_ns() - started_wall,
        formula_flops=None, formula_reason="token_alignment_and_autograd_formula_not_instrumented",
        timing_scope="copy_optimizer_fit_batch_materialization_diagnostics_and_receipt_preparation",
        excluded_costs=["caller_model_initialization", "frozen_encoder_preparation"],
        wall_time_budget_ns=wall_time_ns, budget_check_boundary="before_optimizer_update",
        budget_overrun_ns=max(0, time.perf_counter_ns() - started_wall - wall_time_ns),
        strict_equal_compute=False, frozen=True, natural_task_gain_established=False)
    return trained, receipt


class TokenTrainingFailure(RuntimeError):
    """An interrupted fit with measured attempted work and completed update receipts."""

    def __init__(self, receipt):
        super().__init__(receipt["error_type"] + ": " + receipt["error"])
        self.receipt = receipt


def fit_token_reader(model, train, validation=None, *, failure_receipt_fn=None, **schedule):
    """Persist partial costs before propagating any failed training attempt.

    ``failure_receipt_fn`` receives JSON-compatible data, including actual time
    through the failed attempt. Successful fits retain the ordinary return API.
    """
    wall, cpu, progress = time.perf_counter_ns(), time.process_time_ns(), {}
    try:
        trained, receipt = _fit_token_reader(model, train, validation, progress=progress, **schedule)
        receipt.update(cpu_ns=time.process_time_ns() - cpu, wall_ns=time.perf_counter_ns() - wall,
                       timing_scope="complete_fit_call_including_input_validation_and_receipt_preparation")
        return trained, receipt
    except Exception as error:
        receipt = dict(schema="hepta.token-reader.cpu-fit-failure.v1", status="failed",
            requested_steps=schedule.get("steps"), seed=schedule.get("seed"),
            completed_steps=progress.get("completed_steps", 0),
            actual_training_exposures=progress.get("actual_training_exposures", 0),
            actual_intervention_exposures=progress.get("actual_intervention_exposures", 0),
            attempted_step=progress.get("attempted_step"), updates=progress.get("updates", []),
            diagnostics=progress.get("diagnostics", []), error_type=type(error).__name__, error=str(error),
            cpu_ns=time.process_time_ns() - cpu, wall_ns=time.perf_counter_ns() - wall,
            failed_attempt_time_included=True, failed_update_may_have_mutated_parameters=True,
            formula_flops=None, final_evaluation_authorized=False)
        if failure_receipt_fn is not None:
            try:
                failure_receipt_fn(receipt)
            except Exception as sink_error:
                error.add_note("Failure receipt sink also failed: " + str(sink_error))
        raise TokenTrainingFailure(receipt) from error
