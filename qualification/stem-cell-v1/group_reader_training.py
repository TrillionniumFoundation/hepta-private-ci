"""Source-separated CPU training of the evidence Reader, with actual receipts.

Binary cross entropy is implemented as two-class cross entropy, equivalently
BCE(logit[1]-logit[0]); this retains the existing strict arithmetic profile.
Validation labels appear only in no-gradient diagnostics. Counterfactual labels
must be supplied explicitly and belong to source groups already in training.
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

from execution_meter import BudgetStop, POLICY_SCHEMA, WorkLedger
from paired_execution import PHASES


@dataclass(frozen=True)
class ReaderBatch:
    facts: torch.Tensor
    query: torch.Tensor
    mask: torch.Tensor
    targets: torch.Tensor
    source_groups: tuple = ()

    def validate(self, input_dim, allow_empty=False):
        size = len(self.targets)
        if ((not size and not allow_empty) or self.facts.ndim != 3 or self.facts.shape[0] != size
                or self.facts.shape[2] != input_dim or self.query.shape != (size, input_dim)
                or self.mask.shape != self.facts.shape[:2] or self.mask.dtype != torch.bool
                or self.targets.shape != (size,) or self.targets.dtype != torch.long
                or any(t.device.type != "cpu" or t.requires_grad
                       for t in (self.facts, self.query, self.mask, self.targets))
                or not ((self.targets == 0) | (self.targets == 1)).all()
                or (self.source_groups and (len(self.source_groups) != size
                    or any(not isinstance(g, str) or not g or len(g) > 256 for g in self.source_groups)))):
            raise ValueError("aligned detached CPU reader examples and binary labels required")

    def take(self, indices):
        index = torch.tensor(indices, dtype=torch.long)
        groups = tuple(self.source_groups[i] for i in indices) if self.source_groups else ()
        return ReaderBatch(self.facts[index], self.query[index], self.mask[index], self.targets[index], groups)


def _combine(left, right):
    width = max(left.facts.shape[1], right.facts.shape[1])
    padded = []
    for batch in (left, right):
        count = width - batch.facts.shape[1]
        facts = torch.cat((batch.facts, batch.facts.new_zeros(len(batch.targets), count, batch.facts.shape[2])), 1)
        mask = torch.cat((batch.mask, torch.zeros(len(batch.targets), count, dtype=torch.bool)), 1)
        padded.append((facts, mask))
    return ReaderBatch(torch.cat([p[0] for p in padded]), torch.cat((left.query, right.query)),
                       torch.cat([p[1] for p in padded]), torch.cat((left.targets, right.targets)),
                       left.source_groups + right.source_groups)


def _bytes(parameters):
    return sum(p.numel() * p.element_size() for p in parameters)


def _parameter_digest(model):
    result = hashlib.sha256()
    for name, value in sorted(model.state_dict().items()):
        result.update(name.encode())
        result.update(str(tuple(value.shape)).encode())
        result.update(value.detach().cpu().contiguous().numpy().tobytes())
    return result.hexdigest()


def fit_reader(model, train, validation=None, *, steps, seed, batch_size=32, max_depth=3,
               learning_rate=.01, counterfactual_train=None, counterfactual_fraction=.25,
               feedback_fn=None, wall_time_ns=180_000_000_000, optimizer="Adam",
               diagnostic_interval=100):
    """Fit an independent copy, observe each update, then freeze every parameter.

    feedback_fn receives only the sampled training ReaderBatch and detached
    guesses. It must return four status features per row, never a corrected
    answer embedding. It is never called for validation or future inference.
    """
    train.validate(model.input_dim)
    if validation is not None:
        validation.validate(model.input_dim, allow_empty=True)
        if not len(validation.targets):
            validation = None
    if (type(steps) is not int or not 1 <= steps <= 10000 or not 1 <= batch_size <= 4096
            or type(max_depth) is not int or not 1 <= max_depth <= model.max_hops
            or not 0 < learning_rate <= 1 or not 0 <= counterfactual_fraction < 1
            or optimizer not in ("Adam", "SGD") or type(diagnostic_interval) is not int
            or not 1 <= diagnostic_interval <= 10000):
        raise ValueError("bounded training schedule required")
    train_groups = set(train.source_groups)
    validation_groups = set(validation.source_groups) if validation is not None else set()
    if train_groups & validation_groups:
        raise ValueError("training and validation sources overlap")
    if counterfactual_train is not None:
        counterfactual_train.validate(model.input_dim)
        if (not train_groups or not counterfactual_train.source_groups
                or not set(counterfactual_train.source_groups) <= train_groups):
            raise ValueError("counterfactual labels must be owned by training source groups")
    started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
    trained = copy.deepcopy(model).train()
    for parameter in trained.parameters():
        parameter.requires_grad_(True)
    optimizer_name = optimizer
    opt = (torch.optim.Adam(trained.parameters(), lr=learning_rate, foreach=False)
           if optimizer_name == "Adam" else torch.optim.SGD(trained.parameters(), lr=learning_rate))
    policy = dict(schema=POLICY_SCHEMA, mode="strict", wall_time_ns=wall_time_ns,
                  max_process_rss_bytes=None, rapl_zone=None, rapl_max_power_watts=None)
    meter = WorkLedger(policy, dict.fromkeys(PHASES, 10**16))
    rng, sample_digest = random.Random(seed), hashlib.sha256()
    updates, diagnostics, completed, exposures, cf_exposures, feedback_calls = [], [], 0, 0, 0, 0
    status = "completed"

    def evaluate(data):
        if data is None:
            return None
        loss_sum, correct, size = 0., 0, len(data.targets)
        with meter.scope("evaluation", "bank"), torch.no_grad():
            for start in range(0, size, batch_size):
                batch = data.take(list(range(start, min(size, start + batch_size))))
                logits = trained(batch.facts, batch.query, steps=max_depth, mask=batch.mask)
                loss_sum += F.cross_entropy(logits, batch.targets).item() * len(batch.targets)
                correct += logits.argmax(-1).eq(batch.targets).sum().item()
        return dict(n=size, binary_cross_entropy=loss_sum / size, correct=correct, accuracy=correct / size)

    try:
        diagnostics.append(dict(optimizer_step=0, train=evaluate(train), validation=evaluate(validation)))
        for update in range(steps):
            cf_count = (min(len(counterfactual_train.targets), max(1, int(batch_size * counterfactual_fraction)),
                            batch_size - 1) if counterfactual_train is not None and counterfactual_fraction else 0)
            indices = rng.sample(range(len(train.targets)), min(batch_size - cf_count, len(train.targets)))
            cf_indices = rng.sample(range(len(counterfactual_train.targets)), cf_count) if cf_count else []
            depth = rng.randint(1, max_depth)
            sample_digest.update(repr((indices, cf_indices, depth)).encode())
            before = time.perf_counter_ns()
            with meter.scope("train", "bank"):
                batch = train.take(indices)
                if cf_indices:
                    batch = _combine(batch, counterfactual_train.take(cf_indices))
                opt.zero_grad(set_to_none=True)
                state, feedback, states, losses = None, None, [], []
                for hop in range(depth):
                    state, logits, _ = trained.step_with_attention(batch.facts, batch.query, state, feedback, batch.mask)
                    state.retain_grad()
                    states.append(state)
                    losses.append(F.cross_entropy(logits, batch.targets))
                    if feedback_fn is not None and hop + 1 < depth:
                        feedback = feedback_fn(batch, logits.detach().argmax(-1).tolist())
                        if (not isinstance(feedback, torch.Tensor) or feedback.shape != (len(batch.targets), 4)
                                or feedback.device.type != "cpu" or feedback.requires_grad):
                            raise ValueError("detached training status feedback required")
                        feedback_calls += 1
                loss = losses[0] * (1. / depth)
                for extra in losses[1:]:
                    loss = loss + extra * (1. / depth)
                loss.backward()
                gradient_sq = sum((p.grad * p.grad).sum().item() for p in trained.parameters() if p.grad is not None)
                hop_gradients = [math.sqrt((s.grad * s.grad).sum().item()) for s in states]
                hop_losses = [value.detach().item() for value in losses]
                opt.step()
            completed += 1
            exposures += len(indices)
            cf_exposures += cf_count
            updates.append(dict(step=update + 1, depth=depth, original_exposures=len(indices),
                                counterfactual_exposures=cf_count, hop_binary_losses=hop_losses,
                                parameter_gradient_l2=math.sqrt(gradient_sq),
                                hop_state_gradient_l2=hop_gradients, wall_ns=time.perf_counter_ns() - before))
            if completed % diagnostic_interval == 0 and completed < steps:
                diagnostics.append(dict(optimizer_step=completed, train=evaluate(train), validation=evaluate(validation)))
        diagnostics.append(dict(optimizer_step=completed, train=evaluate(train), validation=evaluate(validation)))
    except BudgetStop:
        status = "budget_stopped"
    optimizer_bytes = sum(_bytes(v for v in state.values() if isinstance(v, torch.Tensor))
                          for state in opt.state.values())
    parameter_bytes = _bytes(trained.parameters())
    gradient_bytes = _bytes(p.grad for p in trained.parameters() if p.grad is not None)
    opt.zero_grad(set_to_none=True)
    trained.eval()
    for parameter in trained.parameters():
        parameter.requires_grad_(False)
    receipt = dict(schema="hepta.query-reader.cpu-fit.v1", status=status, seed=seed,
        requested_steps=steps, completed_steps=completed, actual_training_exposures=exposures,
        actual_counterfactual_exposures=cf_exposures, batch_size=batch_size,
        sample_and_depth_sha256=sample_digest.hexdigest(), updates=updates, diagnostics=diagnostics,
        parameter_count=sum(p.numel() for p in trained.parameters()), parameter_bytes=parameter_bytes,
        optimizer_tensor_bytes=optimizer_bytes, last_gradient_tensor_bytes=gradient_bytes,
        optimizer="Adam_foreach_false" if optimizer_name == "Adam" else "SGD_without_momentum",
        learning_rate=learning_rate, diagnostic_interval=diagnostic_interval,
        model_sha256=_parameter_digest(trained), wall_ns=time.perf_counter_ns() - started_wall,
        cpu_ns=time.process_time_ns() - started_cpu, work_observation=meter.report(),
        validation_gradient_updates=0, train_validation_sources_verified=bool(train_groups and validation_groups),
        train_unique_sources=len(train_groups), validation_unique_sources=len(validation_groups),
        counterfactual_labels_training_only=True, training_feedback_calls=feedback_calls,
        depth_supervision="mean_binary_cross_entropy_all_executed_hops",
        loss_implementation="two_class_CE_equals_BCE_of_logit_difference",
        diagnostic_feedback="none_on_train_and_validation", candidate_cardinality_fixed=False,
        excluded_formula_work=["caller_initialization", "feature_encoding", "Python_sampling_and_scalar_metrics",
                               "Python_training_checker_arithmetic_wall_time_included"],
        strict_equal_compute=False, frozen=True, natural_task_gain_established=False)
    return trained, receipt
