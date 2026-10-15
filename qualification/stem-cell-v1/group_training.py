"""Actual CPU fitting and resource-observed controls for Group qualification.

Initialization, feature production and hyperparameter search have separate owners.
The returned receipt describes this fitting call, never equal-budget equivalence.
"""
import copy
import hashlib
import random
import time

import torch
from torch import nn
from torch.nn import functional as F

from execution_meter import BudgetStop, POLICY_SCHEMA, WorkLedger
from group_core import Core
from paired_execution import PHASES


def _pool(tokens, mask=None):
    if mask is None:
        return tokens.mean(dim=1)
    if mask.shape != tokens.shape[:2] or mask.dtype != torch.bool or not mask.any(dim=1).all():
        raise ValueError("nonempty public evidence mask required")
    weights = mask.to(tokens.dtype).unsqueeze(-1)
    return (tokens * weights).sum(dim=1) / weights.sum(dim=1)


class StaticHead(nn.Module):
    """One actual mean-pool/MLP pass, independent of requested recurrent depth."""

    def __init__(self, input_dim, hidden_dim, classes=8):
        super().__init__()
        if not 1 <= hidden_dim <= 4096:
            raise ValueError("bounded static head width required")
        self.input_dim, self.hidden_dim, self.classes = input_dim, hidden_dim, classes
        self.project = nn.Linear(input_dim, hidden_dim)
        self.head = nn.Linear(hidden_dim, classes)

    def step(self, tokens, state=None, feedback=None, mask=None):
        hidden = F.gelu(self.project(_pool(tokens, mask)))
        return hidden, self.head(hidden)

    def forward(self, tokens, steps=1, mask=None, feedback=None, reset_state=False):
        return self.step(tokens, mask=mask)[1]


def matched_static(core, input_dim=None):
    """Choose the nearest integer MLP width and disclose the actual mismatch."""
    input_dim = core.input_dim if input_dim is None else input_dim
    target = sum(p.numel() for p in core.parameters())
    width = min(range(1, 4097), key=lambda h: abs(h * (input_dim + core.classes + 1) + core.classes - target))
    model = StaticHead(input_dim, width, core.classes)
    actual = sum(p.numel() for p in model.parameters())
    return model, {"target_parameters": target, "actual_parameters": actual,
                   "parameter_difference": actual - target, "hidden_dim": width,
                   "matching_basis": "parameter_count_only_not_work_or_latency"}


class SplitCore(nn.Module):
    """One copied shared trunk, two independent readouts, actual sparse top-1."""

    def __init__(self, parent):
        super().__init__()
        if not isinstance(parent, Core):
            raise ValueError("a trained unsplit Core is required")
        self.input_dim, self.hidden_dim, self.classes = parent.input_dim, parent.hidden_dim, parent.classes
        self.core = copy.deepcopy(parent)
        self.readouts = nn.ModuleList([copy.deepcopy(parent.head), copy.deepcopy(parent.head)])
        self.core.head = nn.Identity()
        self.router = nn.Sequential(nn.Linear(self.input_dim, 8), nn.GELU(), nn.Linear(8, 2))
        self.routing_executions = [0, 0]

    def route_logits(self, tokens, mask=None):
        return self.router(_pool(tokens, mask))

    def step(self, tokens, state=None, feedback=None, mask=None):
        state, _ = self.core.step(tokens, state, feedback, mask)
        routes = self.route_logits(tokens, mask).argmax(dim=-1)
        selected_logits, selected_indices = [], []
        for cell, readout in enumerate(self.readouts):
            indices = routes.eq(cell).nonzero().flatten()
            if indices.numel():
                selected_logits.append(readout(state.index_select(0, indices)))
                selected_indices.append(indices)
                self.routing_executions[cell] += indices.numel()
        # Concatenate active expert results, then restore original batch order.
        # Chained index_copy backward emits index_fill on mixed routes, outside
        # the frozen arithmetic profile. Sorting/index_select keeps exact sparse
        # execution and has a fully covered backward without widening that profile.
        order = torch.cat(selected_indices).argsort(stable=True)
        logits = torch.cat(selected_logits).index_select(0, order)
        return state, logits

    def forward(self, tokens, steps=1, mask=None, feedback=None, reset_state=False):
        if type(steps) is not int or not 1 <= steps <= 64:
            raise ValueError("bounded recurrence depth required")
        state = None
        for _ in range(steps):
            state, logits = self.step(tokens, None if reset_state else state, feedback, mask)
        return logits


def fit_model(model, features, masks, targets, *, steps, seed, feedback=None,
              route_targets=None, max_depth=4, learning_rate=.05, batch_size=32,
              feedback_fn=None, attention_targets=None, attention_weight=0.1):
    """Train only supplied fitting labels, then freeze an independent model.

    Route labels are optional, train-only family supervision. They never enter
    inference. Targets and feedback are never synthesized from evaluation data.
    All eager forward/backward/SGD operations in this call are strictly metered.
    """
    if (type(steps) is not int or not 1 <= steps <= 10000 or not 1 <= max_depth <= 64
            or features.ndim != 3 or not len(features) or targets.shape != (features.shape[0],)
            or features.device.type != "cpu" or features.requires_grad
            or not 1 <= batch_size <= 4096 or not 0 < learning_rate <= 1):
        raise ValueError("bounded CPU fitting data, steps and optimizer settings required")
    if route_targets is not None and (not hasattr(model, "route_logits") or route_targets.shape != targets.shape):
        raise ValueError("router and aligned training route labels required")
    if attention_targets is not None:
        if (type(model) is not Core or type(attention_weight) not in (int, float)
                or not 0 < attention_weight <= 1
                or not isinstance(attention_targets, torch.Tensor)
                or attention_targets.shape != (len(targets), max_depth, features.shape[1])
                or attention_targets.dtype != torch.float32
                or attention_targets.device.type != "cpu" or attention_targets.requires_grad
                or masks is None or masks.shape != features.shape[:2]
                or masks.dtype != torch.bool
                or not torch.isfinite(attention_targets).all()
                or not ((attention_targets == 0) | (attention_targets == 1)).all()
                or (attention_targets * (~masks).unsqueeze(1)).any()
                or not attention_targets.sum().gt(0)):
            raise ValueError("source-bound binary attention masks and Core required")
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    trained = copy.deepcopy(model).train()
    for parameter in trained.parameters():
        parameter.requires_grad_(True)
    optimizer = torch.optim.SGD(trained.parameters(), lr=learning_rate)
    policy = {"schema": POLICY_SCHEMA, "mode": "strict", "wall_time_ns": 180_000_000_000,
              "max_process_rss_bytes": None, "rapl_zone": None, "rapl_max_power_watts": None}
    meter = WorkLedger(policy, dict.fromkeys(PHASES, 10**15))
    generator, losses, depths, completed, status = random.Random(seed), [], {}, 0, "completed"
    sampling_digest, attempted_exposures = hashlib.sha256(), 0
    feedback_calls, nonzero_feedback_batches = 0, 0
    attention_supervised_examples = 0

    def diagnostic():
        with meter.scope("evaluation", "bank"), torch.no_grad():
            return F.cross_entropy(trained(features, steps=max_depth, mask=masks, feedback=feedback), targets).item()

    loss_before, loss_after = None, None
    try:
        loss_before = diagnostic()
        for _ in range(steps):
            indices = generator.sample(range(len(targets)), min(batch_size, len(targets)))
            depth = generator.randint(1, max_depth)
            sampling_digest.update(repr((indices, depth)).encode())
            attempted_exposures += len(indices)
            with meter.scope("train", "bank"):
                batch = torch.tensor(indices, dtype=torch.long)
                x, y = features[batch], targets[batch]
                mask = masks[batch] if masks is not None else None
                fb = feedback[batch] if feedback is not None else None
                optimizer.zero_grad(set_to_none=True)
                if (feedback_fn is not None or attention_targets is not None) and not isinstance(trained, StaticHead):
                    state, step_losses = None, []
                    for level in range(depth):
                        if attention_targets is not None:
                            state, logits, attention = trained.step(
                                x, state, fb, mask, return_attention=True)
                            chosen = attention_targets[batch, level]
                            active = chosen.sum(dim=1).gt(0).to(attention.dtype)
                            mass = (attention * chosen).sum(dim=1)
                            pointer_loss = (-(mass.clamp_min(1e-8).log()) * active).sum() / active.sum().clamp_min(1)
                            step_loss = F.cross_entropy(logits, y) + attention_weight * pointer_loss
                            attention_supervised_examples += int(active.sum().item())
                        else:
                            state, logits = trained.step(x, state, fb, mask)
                            step_loss = F.cross_entropy(logits, y)
                        step_losses.append(step_loss)
                        if feedback_fn is not None and level + 1 < depth:
                            fb = feedback_fn(indices, logits.detach().argmax(-1).tolist())
                            if (not isinstance(fb, torch.Tensor) or fb.shape != (len(indices), 4)
                                    or fb.device.type != "cpu" or fb.requires_grad):
                                raise ValueError("checker returns detached train-only status features")
                            fb = fb.to(features.dtype)
                            feedback_calls += 1
                            nonzero_feedback_batches += int(fb.ne(0).any().item())
                    loss = step_losses[0] * (1. / depth)
                    for step_loss in step_losses[1:]:
                        loss = loss + step_loss * (1. / depth)
                else:
                    logits = trained(x, steps=depth, mask=mask, feedback=fb)
                    loss = F.cross_entropy(logits, y)
                if route_targets is not None:
                    loss = loss + F.cross_entropy(trained.route_logits(x, mask), route_targets[batch])
                loss.backward()
                optimizer.step()
                losses.append(loss.detach().item())
            completed += 1
            depths[str(depth)] = depths.get(str(depth), 0) + 1
        loss_after = diagnostic()
    except BudgetStop:
        status = "budget_stopped"
    parameter_bytes = sum(p.numel() * p.element_size() for p in trained.parameters())
    optimizer_bytes = sum(v.numel() * v.element_size() for state in optimizer.state.values()
                          for v in state.values() if isinstance(v, torch.Tensor))
    gradient_bytes = sum(p.grad.numel() * p.grad.element_size() for p in trained.parameters() if p.grad is not None)
    optimizer.zero_grad(set_to_none=True)
    trained.eval()
    for parameter in trained.parameters():
        parameter.requires_grad_(False)
    receipt = {"schema": "hepta.group.cpu-fit.v1", "status": status, "seed": seed,
               "requested_steps": steps, "completed_steps": completed, "steps": completed,
               "batch_size": min(batch_size, len(targets)),
               "actual_completed_training_exposures": completed * min(batch_size, len(targets)),
               "attempted_training_exposures": attempted_exposures,
               "sample_and_depth_sha256": sampling_digest.hexdigest(),
               "depth_counts": depths, "loss_before": loss_before, "loss_after": loss_after,
               "last_objective_loss": losses[-1] if losses else None,
               "parameter_count": sum(p.numel() for p in trained.parameters()),
               "parameter_bytes": parameter_bytes, "optimizer_bytes": optimizer_bytes,
               "last_gradient_tensor_bytes": gradient_bytes, "optimizer": "SGD_without_momentum",
               "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
               "work_observation": meter.report(), "route_supervision": route_targets is not None,
               "training_feedback_callback": feedback_fn is not None,
               "attention_supervision_enabled": attention_targets is not None,
               "attention_loss_weight": float(attention_weight) if attention_targets is not None else 0.,
               "attention_supervised_step_examples": attention_supervised_examples,
               "attention_target_sha256": (hashlib.sha256(attention_targets.contiguous().numpy().tobytes()).hexdigest()
                                           if attention_targets is not None else None),
               "training_feedback_calls": feedback_calls,
               "nonzero_feedback_batches": nonzero_feedback_batches,
               "feedback_interface": "fitting_batch_indices_and_detached_guesses_only",
               "depth_supervision": "mean_all_steps" if (feedback_fn is not None or attention_targets is not None) and not isinstance(trained, StaticHead) else "final_step",
               "diagnostic_loss_profile": "fitting_labels_max_depth_without_dynamic_feedback",
               "budget_comparison": "actual_consumption_reported_unequal_budgets",
               "excluded_formula_work": ["caller_initialization", "feature_production", "Python_integer_sampling",
                                          "Python_symbolic_checker_arithmetic_wall_time_included"],
               "frozen": True}
    if isinstance(trained, SplitCore):
        receipt["routing_executions"] = list(trained.routing_executions)
        receipt["readout_parameter_bytes"] = [sum(p.numel() * p.element_size() for p in h.parameters())
                                                for h in trained.readouts]
        receipt["readouts_share_parameter_storage"] = any(a.data_ptr() == b.data_ptr()
                                                          for a, b in zip(*[list(h.parameters()) for h in trained.readouts]))
        receipt["readout_parameters_equal"] = all(torch.equal(a, b)
                                                  for a, b in zip(*[list(h.parameters()) for h in trained.readouts]))
    return trained, receipt
