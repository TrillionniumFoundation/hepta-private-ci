"""Bounded learning/structure/reasoning experiments, not an execution owner.

Inputs are frozen feature tensors. This module never claims that constructing
features ran an Encoder. Call existing development_trial for actual Stem work.
Caller supplies approved folds; group/time validation is structural, not signed
provenance. Every fit returns a next-snapshot copy; selected modules stay intact.
"""

from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
import math
import time

import torch
from torch import nn
from torch.nn import functional as F

from development_composition import SharedCellRecurrence
from development_tensors import checked_tensor, parameter_digest, split_candidate


@dataclass(frozen=True)
class FoldIdentity:
    """Episode/source-family group must be shared by all correlated examples."""

    scope: str
    groups: tuple[str, ...]
    observed_at: tuple[int, ...]

    def validate(self, rows: int) -> None:
        if (type(self.scope) is not str or not 0 < len(self.scope) <= 128
                or type(self.groups) is not tuple or len(self.groups) != rows
                or type(self.observed_at) is not tuple or len(self.observed_at) != rows
                or any(type(g) is not str or not 0 < len(g) <= 128 for g in self.groups)
                or any(type(t) is not int or t < 0 for t in self.observed_at)):
            raise ValueError("invalid fold identity")


def validate_folds(train: FoldIdentity, holdout: FoldIdentity, n: int, m: int) -> None:
    if type(train) is not FoldIdentity or type(holdout) is not FoldIdentity or min(n, m) < 1:
        raise ValueError("invalid paired folds")
    train.validate(n)
    holdout.validate(m)
    if (train.scope != holdout.scope or set(train.groups) & set(holdout.groups)
            or max(train.observed_at) >= min(holdout.observed_at)):
        raise ValueError("scope, group or chronological leakage")


class PhaseClock:
    """Process CPU and monotonic wall; neither is independent host attestation."""

    def __init__(self):
        self.cpu, self.wall = time.process_time_ns(), time.perf_counter_ns()

    def finish(self) -> dict:
        return {"cpu_ns": time.process_time_ns() - self.cpu,
                "wall_ns": time.perf_counter_ns() - self.wall}


def labels_checked(y, rows, classes):
    if (not isinstance(y, torch.Tensor) or y.device.type != "cpu" or y.dtype != torch.long
            or y.shape != (rows,) or bool(((y < 0) | (y >= classes)).any())):
        raise ValueError("invalid training labels")


def fit_candidate(model, features, labels, *, steps=80, seed=13, batch_size=32, lr=0.02):
    """Real SGD on a private candidate with a reproducible minibatch stream."""
    checked_tensor(features, features.ndim, "training features")
    if (features.ndim not in (2, 3) or type(steps) is not int or not 1 <= steps <= 1000
            or type(batch_size) is not int or not 1 <= batch_size <= 32 or type(seed) is not int
            or type(lr) not in (float, int) or not math.isfinite(lr) or not 0 < lr <= 1):
        raise ValueError("invalid optimizer envelope")
    parameters = sum(p.numel() for p in model.parameters())
    if parameters > 4_194_304:
        raise ValueError("candidate too large")
    with torch.no_grad():
        preview = deepcopy(model).eval()(features[:1].detach())
    if preview.ndim != 2 or not 2 <= preview.shape[1] <= 128:
        raise ValueError("classifier output required")
    labels_checked(labels, len(features), preview.shape[1])
    clock = PhaseClock()
    out = deepcopy(model)
    params = [p for p in out.parameters() if p.requires_grad]
    if not params:
        raise ValueError("no trainable parameters")
    optimizer = torch.optim.SGD(params, lr=lr)
    rng = torch.Generator(device="cpu").manual_seed(seed)
    out.train()
    processed = 0
    last_loss = None
    for _ in range(steps):
        ids = torch.randperm(len(features), generator=rng)[:batch_size]
        logits = out(features[ids].detach().clone())
        loss = F.cross_entropy(logits, labels[ids])
        if not torch.isfinite(loss):
            raise ValueError("nonfinite learning loss")
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        nn.utils.clip_grad_norm_(params, 1.0, error_if_nonfinite=True)
        optimizer.step()
        processed += len(ids)
        last_loss = float(loss.detach())
    out.eval()
    if any(not torch.isfinite(v).all() for v in out.state_dict().values()):
        raise ValueError("nonfinite learned model")
    receipt = clock.finish()
    receipt.update({"steps": steps, "examples_processed": processed,
                    "trainable_parameters": sum(p.numel() for p in params),
                    "parameter_bytes": sum(p.numel() * p.element_size() for p in out.parameters()),
                    "last_training_loss": last_loss, "production_authorized": False})
    return out, receipt


def paired_predictions(initial, x, labels, heldout, *, steps=80, seed=13):
    """Gold holdout labels are intentionally absent from this API."""
    before = parameter_digest(initial)
    trained, fit = fit_candidate(initial, x, labels, steps=steps, seed=seed)
    clock = PhaseClock()
    with torch.no_grad():
        frozen_logits = deepcopy(initial).eval()(heldout.detach()).clone()
        trained_logits = trained(heldout.detach()).clone()
    if parameter_digest(initial) != before:
        raise RuntimeError("selected source parameters mutated")
    return trained, {"frozen_logits": frozen_logits, "trained_logits": trained_logits,
                     "fit": fit, "paired_inference": clock.finish(),
                     "initial_digest": before, "candidate_digest": parameter_digest(trained),
                     "encoder_execution_observed": False, "production_authorized": False}


class RoutedBasis(nn.Module):
    """Last feature is an explicitly observed route bit, also seen by controls."""

    def __init__(self, bank, *, split):
        super().__init__()
        self.bank, self.split = bank, split

    def forward(self, x):
        checked_tensor(x, 2, "observed route features")
        route = x[:, -1]
        if not bool(((route == 0) | (route == 1)).all()):
            raise ValueError("route must be observed binary input, not hidden label")
        ids = route.long() if self.split else torch.zeros(len(x), dtype=torch.long)
        return self.bank(x[:, :-1], ids)


class RouteAwareUnsplit(nn.Module):
    """Single route-conditioned model with the split's exact parameter budget.

    Binary routing is public input to ALL controls. This model has no Cell IDs,
    births or topology: it interpolates private coefficients/gates in one Head.
    At routes 0/1 it contains the two-specialist function as an exact control.
    Equal functions are intentional: a Cell identity alone is not new capacity.
    """

    def __init__(self, bank):
        super().__init__()
        if len(bank.cell_ids) != 1 or not bank.awake[0]:
            raise ValueError("single awake parent required")
        self.width, self.classes = bank.width, bank.classes
        self.base = deepcopy(bank.base).requires_grad_(False)
        self.basis = nn.Parameter(bank.basis.detach().clone(), requires_grad=False)
        self.register_buffer("gate_axes", bank.gate_axes.detach().clone())
        self.coefficients = nn.Parameter(bank.coefficients.detach().repeat(2, 1))
        self.gates = nn.Parameter(bank.gates.detach().repeat(2, 1))

    def forward(self, x):
        checked_tensor(x, 2, "observed route features")
        if x.shape[1] != self.width + 1 or x.dtype != self.base.weight.dtype:
            raise ValueError("route-inclusive feature width/dtype mismatch")
        route = x[:, -1:]
        if not bool(((route == 0) | (route == 1)).all()):
            raise ValueError("public binary route required")
        features = x[:, :-1]
        coefficients = (1 - route) * self.coefficients[0] + route * self.coefficients[1]
        gates = (1 - route) * self.gates[0] + route * self.gates[1]
        activation = torch.sigmoid((features @ self.gate_axes.T * gates[:, :-1]).sum(1) + gates[:, -1])
        residual = torch.einsum("bd,rdk,br->bk", features, self.basis, coefficients)
        return self.base(features) + activation[:, None] * residual



def structural_arms(bank, x, labels, heldout, *, train_fold, holdout_fold, steps=80, seed=13):
    """Split vs frozen parent, same parent, equal-local-budget wide Head and data.

    All arms see the same public route feature. The larger-data arm sees twice
    the rows of the smaller-data arms, at the same SGD update count; actual
    example counts are recorded. It is not a claim of equal upstream data cost.
    """
    if len(bank.cell_ids) != 1 or len(x) < 8 or len(x) % 2:
        raise ValueError("single parent and even >=8-row training fold required")
    checked_tensor(x, 2, "structural features")
    checked_tensor(heldout, 2, "structural holdout")
    if x.shape[1] != bank.width + 1 or heldout.shape[1] != x.shape[1]:
        raise ValueError("route-inclusive feature width mismatch")
    labels_checked(labels, len(x), bank.classes)
    validate_folds(train_fold, holdout_fold, len(x), len(heldout))
    split = split_candidate(bank, bank.cell_ids[0], "candidate-child",
                            maximum_local_parameters=2 * (2 * bank.rank + 1))
    budget = split.parameter_counts()["cell_local"]
    # At most the split's trainable local budget; unused budget is not padded.
    per_hidden = x.shape[1] + bank.classes + 1
    hidden = (budget - bank.classes) // per_hidden
    if hidden < 1:
        raise ValueError("no valid wide-Head control at this local budget")
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        wide = nn.Sequential(nn.Linear(x.shape[1], hidden), nn.Tanh(), nn.Linear(hidden, bank.classes))
    assert sum(p.numel() for p in wide.parameters()) <= budget
    arms = {"parent": RoutedBasis(bank, split=False), "split": RoutedBasis(split, split=True),
            "wide_head": wide, "more_data": RoutedBasis(bank, split=False),
            "route_aware_unsplit": RouteAwareUnsplit(bank),
            "route_aware_more_data": RouteAwareUnsplit(bank)}
    initial_identity = parameter_digest(bank)
    out = {}
    for name, model in arms.items():
        n = len(x) if name in ("more_data", "route_aware_more_data") else len(x) // 2
        _, receipt = paired_predictions(model, x[:n], labels[:n], heldout, steps=steps, seed=seed)
        receipt["training_rows_available"] = n
        receipt["all_parameter_count"] = sum(p.numel() for p in model.parameters())
        receipt["shared_basis_counted"] = name != "wide_head"
        receipt["state_tensor_bytes"] = sum(v.numel() * v.element_size() for v in model.state_dict().values())
        receipt["public_route_used"] = name not in ("parent", "more_data")
        receipt["logical_cells"] = 2 if name == "split" else 1
        receipt["fold_isolation_checked"] = True
        receipt["fold_provenance_authenticated"] = False
        out[name] = receipt
    if parameter_digest(bank) != initial_identity:
        raise RuntimeError("structural experiment mutated selected parent")
    return out


class RecurrentClassifier(nn.Module):
    """Actual shared recurrent core; depth controls sequential state transitions."""

    def __init__(self, width, classes, *, depth):
        super().__init__()
        self.recurrence = SharedCellRecurrence(width)
        self.output = nn.Linear(width, classes)
        self.depth = depth

    def forward(self, x, *, depth=None):
        checked_tensor(x, 3, "observed recurrent features")
        valid = torch.ones(x.shape[:2], dtype=torch.bool)
        initial = torch.zeros(len(x), x.shape[-1], dtype=x.dtype)
        state, _ = self.recurrence(x, valid, initial, depth=self.depth if depth is None else depth)
        return self.output(state)


def run_depth_candidates(model, x, *, depths=(1, 2, 4)):
    """Independent fixed-depth controls, each charged its full actual work."""
    if (type(depths) is not tuple or not depths or len(set(depths)) != len(depths)
            or any(type(d) is not int or not 1 <= d <= 32 for d in depths)):
        raise ValueError("invalid depth controls")
    out = {}
    for depth in depths:
        clock = PhaseClock()
        with torch.no_grad():
            logits = model(x, depth=depth).clone()
        out[depth] = {"logits": logits, "sequential_depth": depth,
                      "cell_transitions": len(x) * depth, **clock.finish()}
    return out


@torch.no_grad()
def incremental_depth_candidates(model, x, *, depths=(1, 2, 4)):
    """Pay for shared recurrence prefixes once, retain each depth's own readout.

    All input tokens must already be observed. No label, reward, future outcome
    or stopping policy is accepted. This reuses computation within ONE arm only;
    it does not borrow intermediate states from the independent fixed controls.
    """
    checked_tensor(x, 3, "observed recurrent features")
    if (type(depths) is not tuple or not depths or len(set(depths)) != len(depths)
            or any(type(d) is not int or not 1 <= d <= 32 for d in depths)):
        raise ValueError("invalid depth controls")
    clock = PhaseClock()
    state = torch.zeros(len(x), x.shape[-1], dtype=x.dtype)
    valid = torch.ones(x.shape[:2], dtype=torch.bool)
    outputs = {}
    for depth in range(1, max(depths) + 1):
        state, _ = model.recurrence(x, valid, state, depth=1)
        if depth in depths:
            outputs[depth] = model.output(state).clone()
    return {"depths": outputs, "cell_transitions": len(x) * max(depths),
            "readout_calls": len(depths), "maximum_depth": max(depths),
            **clock.finish(), "production_authorized": False}


@dataclass(frozen=True)
class ChanceEdge:
    probability: float
    child: str


@dataclass(frozen=True)
class ComputeOption:
    name: str
    cost: float
    outcomes: tuple[ChanceEdge, ...]


@dataclass(frozen=True)
class InformationState:
    """One key per public history, never one key per unobserved hidden world."""

    key: str
    stop_value: float
    options: tuple[ComputeOption, ...]


def finite_compute_allocation(states, root, *, budget):
    """Full finite-depth conditional-expected utility minus cost SPECIAL CASE.

    This closes the one-step complementarity gap: a paid observation may be
    useful only together with a later paid observation. No general FBSDE claim,
    no world-state argument, no live effects, and no independent efficacy claim.
    Values/probabilities are caller estimates from public history, not outcomes.
    """
    if (type(states) is not tuple or not 1 <= len(states) <= 512
            or type(budget) not in (int, float) or not math.isfinite(budget) or not 0 <= budget <= 1e6):
        raise ValueError("invalid allocation envelope")
    by_key = {}
    def finite(x):
        return type(x) in (int, float) and math.isfinite(x)
    for state in states:
        if (type(state) is not InformationState or type(state.key) is not str
                or not 0 < len(state.key) <= 128 or state.key in by_key
                or not finite(state.stop_value) or abs(state.stop_value) > 1e6
                or type(state.options) is not tuple or len(state.options) > 16):
            raise ValueError("invalid public information state")
        names = set()
        for option in state.options:
            if (type(option) is not ComputeOption or type(option.name) is not str
                    or not 0 < len(option.name) <= 128 or option.name == "stop" or option.name in names
                    or not finite(option.cost) or not 0 <= option.cost <= 1e6
                    or type(option.outcomes) is not tuple or not 1 <= len(option.outcomes) <= 16):
                raise ValueError("invalid computation option")
            names.add(option.name)
            children = set()
            for edge in option.outcomes:
                if (type(edge) is not ChanceEdge or not finite(edge.probability)
                        or not 0 < edge.probability <= 1 or type(edge.child) is not str
                        or edge.child in children):
                    raise ValueError("invalid conditional law")
                children.add(edge.child)
            if abs(sum(e.probability for e in option.outcomes) - 1) > 1e-12:
                raise ValueError("conditional probabilities must sum to one")
        by_key[state.key] = state
    if type(root) is not str or root not in by_key:
        raise ValueError("unknown root")
    # Validate the entire supplied graph, including unaffordable/unreachable nodes.
    heights, stack = {}, set()
    def visit(key):
        if key not in by_key or key in stack:
            raise ValueError("missing state or cycle")
        if key in heights:
            return heights[key]
        if len(stack) > 32:
            raise ValueError("excessive planning depth")
        stack.add(key)
        height = 0
        for option in by_key[key].options:
            for edge in option.outcomes:
                height = max(height, 1 + visit(edge.child))
        stack.remove(key)
        if height > 32:
            raise ValueError("excessive planning depth")
        heights[key] = height
        return height
    for key in by_key:
        visit(key)
    clock, cache, entered = PhaseClock(), {}, set()
    def solve(key, remaining):
        cache_key = (key, remaining)
        if cache_key in cache:
            return cache[cache_key]
        if len(entered) >= 8192:
            raise ValueError("planning state budget exhausted")
        entered.add(cache_key)
        best, action = by_key[key].stop_value, "stop"
        for option in sorted(by_key[key].options, key=lambda o: o.name):
            exact_cost = Fraction(str(option.cost))
            if exact_cost > remaining:
                continue
            value = sum(edge.probability * solve(edge.child, remaining - exact_cost)[0]
                        for edge in option.outcomes) - option.cost
            if value > best:
                best, action = value, option.name
        cache[cache_key] = best, action
        return best, action
    # Declared resource decimals are exact; .3-.1 must still afford .2.
    value, action = solve(root, Fraction(str(budget)))
    return {"action": action, "value": value, "evaluated_state_budgets": len(cache),
            "profile": "finite_expected_utility_minus_cost", **clock.finish(),
            "production_authorized": False, "independent_efficacy_established": False}
