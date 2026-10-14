"""Finite-horizon stopping on the existing shared Reader, not general NDU/FBSDE.

The objective is externally correct classification minus a declared per-read
utility charge. Backward regression fits continuation under its own later stops;
the matched terminal control assumes continuing to the final observation.
Only current prefix probabilities enter a deployed gate. This is approximate
least-squares policy fitting, not a calibrated bound or an optimality certificate.
"""
from dataclasses import asdict, dataclass
import math

import torch

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell.controls import RecurrentReader, _critic_features, _reader_labels as labels


def sequence(x):
    if (not isinstance(x, torch.Tensor) or x.device.type != 'cpu' or x.dtype != torch.float32
            or x.ndim != 3 or not 1 <= len(x) <= 4096 or not 2 <= x.shape[1] <= 16
            or not 1 <= x.shape[2] <= 256 or x.numel() * 4 > 64 * 1024**2
            or not bool(torch.isfinite(x).all())):
        raise e.InputError('bounded finite CPU observation sequence required')


def probabilities(p):
    sequence(p)
    if (p.shape[2] < 2 or bool(((p < 0) | (p > 1)).any())
            or not torch.allclose(p.sum(-1), torch.ones_like(p[..., 0]), atol=1e-5, rtol=0)):
        raise e.InputError('normalized class probabilities required')



@dataclass(frozen=True)
class StopRule:
    kind: str
    horizon: int
    classes: int
    step_cost: float
    limit: int = 0
    threshold: float = 0.0
    coefficients: tuple = ()

    def validate(self):
        e.integer(self.horizon, 2, 16, 'stopping horizon')
        e.integer(self.classes, 2, 256, 'stopping classes')
        if (type(self.step_cost) not in (int, float) or not math.isfinite(self.step_cost)
                or not 0 <= self.step_cost <= 1):
            raise e.InputError('fixed finite utility charge required')
        if self.kind == 'fixed':
            e.integer(self.limit, 1, self.horizon, 'fixed depth')
        elif self.kind == 'confidence':
            if type(self.threshold) not in (int, float) or not 0 <= self.threshold <= 1:
                raise e.InputError('bounded fixed confidence threshold required')
        elif self.kind in {'terminal_linear', 'backward_linear'}:
            if (type(self.coefficients) is not tuple or len(self.coefficients) != self.horizon - 1
                    or any(type(row) is not tuple or len(row) != 4
                           or any(type(v) not in (int, float) or not math.isfinite(v) for v in row)
                           for row in self.coefficients)):
                raise e.InputError('complete finite per-depth coefficients required')
        else:
            raise e.InputError('unknown stopping rule')
        return self

    def stop(self, p, depth):
        # No target, full trace, later observation, or evaluator callback exists here.
        if depth == self.horizon:
            return torch.ones(len(p), dtype=torch.bool)
        if self.kind == 'fixed':
            return torch.full((len(p),), depth >= self.limit, dtype=torch.bool)
        if self.kind == 'confidence':
            return p.max(-1).values >= self.threshold
        phi = _critic_features(p, depth, self.horizon).double()
        return phi @ torch.tensor(self.coefficients[depth - 1], dtype=torch.float64) <= 0

    def record(self):
        return asdict(self.validate())


@torch.no_grad()
def fit_rules(p, y, *, step_cost, ridge=0.1):
    """Critic-fit fold ONLY; no tuning or holdout rows. All stages keep one fold.

    G_H = correct_H; A_t = E[G_(t+1) - cost - correct_t | prefix_t].
    G_t follows the fitted public-prefix decision, not a clairvoyant per-row max.
    The terminal comparator instead uses correct_H-(H-t)*cost-correct_t.
    Both use the same four features and H-1 ridge fits. In-sample selection bias
    remains possible; independent tuning/holdout evaluation is mandatory.
    """
    probabilities(p)
    n, horizon, classes = p.shape
    labels(y, n, classes)
    StopRule('fixed', horizon, classes, step_cost, limit=1).validate()
    if type(ridge) not in (int, float) or not math.isfinite(ridge) or not 0 < ridge <= 10:
        raise e.InputError('positive finite ridge required')
    correct = (p.argmax(-1) == y[:, None]).double()
    rules, diagnostics = {}, {}
    with e.measured() as timing:
        for kind in ('terminal_linear', 'backward_linear'):
            future = correct[:, -1].clone()
            coefficients, residuals = [None] * (horizon - 1), [None] * (horizon - 1)
            for t in reversed(range(horizon - 1)):
                phi = _critic_features(p[:, t], t + 1, horizon).double()
                target = ((correct[:, -1] - step_cost * (horizon - t - 1))
                          if kind == 'terminal_linear' else future - step_cost) - correct[:, t]
                # Augmented ridge solve: no normal-equation inverse, fixed SVD cutoff.
                a = torch.cat((phi, math.sqrt(ridge) * torch.eye(4, dtype=torch.float64)))
                b = torch.cat((target, torch.zeros(4, dtype=torch.float64)))
                beta = torch.linalg.lstsq(a, b, rcond=1e-12, driver='gelsd').solution
                advantage = phi @ beta
                if not bool(torch.isfinite(beta).all()):
                    raise e.InputError('nonfinite continuation coefficients')
                coefficients[t] = tuple(beta.tolist())
                residuals[t] = float(((advantage - target)**2).mean())
                if kind == 'backward_linear':
                    future = torch.where(advantage > 0, future - step_cost, correct[:, t])
            rules[kind] = StopRule(kind, horizon, classes, step_cost,
                                   coefficients=tuple(coefficients)).validate()
            diagnostics[kind] = {'fit_mse_by_depth': residuals, 'ridge_fits': horizon - 1}
    return rules, {'cost': timing, 'diagnostics': diagnostics, 'critic_rows': n,
                   'ridge': ridge, 'independent_acceptance': False, 'general_fbsde': False}


@torch.no_grad()
def trace_depths(p, rule):
    """Calibration-only replay, not a runtime/latency measurement."""
    probabilities(p)
    rule.validate()
    if tuple(p.shape[1:]) != (rule.horizon, rule.classes):
        raise e.InputError('rule and trace profile mismatch')
    depths = torch.full((len(p),), rule.horizon, dtype=torch.long)
    live = torch.ones(len(p), dtype=torch.bool)
    for t in range(rule.horizon):
        ids = live.nonzero(as_tuple=False).flatten()
        stopped = ids[rule.stop(p[ids, t], t + 1)]
        depths[stopped], live[stopped] = t + 1, False
    return depths


@torch.no_grad()
def tune_simple(p, y, *, step_cost):
    """Tune strong cheap controls on a fold disjoint from critic fitting."""
    probabilities(p)
    n, horizon, classes = p.shape
    labels(y, n, classes)
    candidates = [StopRule('fixed', horizon, classes, step_cost, limit=t) for t in range(1, horizon+1)]
    candidates += [StopRule('confidence', horizon, classes, step_cost, threshold=t)
                   for t in (0.5, 0.7, 0.8, 0.9, 0.95, 1.0)]
    rows = []
    for rule in candidates:
        d = trace_depths(p, rule)
        correct = p[torch.arange(n), d-1].argmax(-1) == y
        rows.append({'rule': rule.record(), 'correct': int(correct.sum()),
                     'transitions': int(d.sum()), 'utility': float(correct.double().mean()-step_cost*d.double().mean())})
    best = lambda ids: min(ids, key=lambda i: (-rows[i]['utility'], rows[i]['transitions'], i))
    fixed, adaptive = best(range(horizon)), best(range(horizon, len(candidates)))
    return candidates[fixed], candidates[adaptive], {'rows': rows, 'tuning_rows': n,
        'selection_rule': 'external_accuracy_minus_declared_charge_then_fewer_transitions_then_fixed_order'}


@torch.no_grad()
def read_trace(model, x):
    """Fully read a fitting/tuning cohort once; this preparation is separately charged."""
    sequence(x)
    model_check(model, x)
    state, trace = torch.zeros(len(x), x.shape[2]), []
    with e.measured() as cost:
        for t in range(x.shape[1]):
            state, logits = model.step(x[:, t], state)
            trace.append(logits.softmax(-1))
    p = torch.stack(trace, 1)
    probabilities(p)
    return p, {**cost, 'cell_transitions': len(x)*x.shape[1], 'forward_calls': x.shape[1]}


def model_check(model, x):
    if (type(model) is not RecurrentReader or model.training or model.core.input_size != x.shape[2]
            or model.core.hidden_size != x.shape[2] or any(p.requires_grad or p.dtype != torch.float32
            or p.device.type != 'cpu' or not bool(torch.isfinite(p).all()) for p in model.parameters())):
        raise e.InputError('frozen existing CPU Reader required')


@torch.no_grad()
def execute(model, x, rule):
    """Real stopped execution: no full-trace precomputation and no gold input.

    Caller already holds the offline feature sequence; input validation scans it.
    Only active current rows enter the Reader/gate. No external sensor/network
    acquisition saving is inferred from avoiding later Reader transitions.
    """
    with e.measured() as cost:
        sequence(x)
        model_check(model, x)
        rule.validate()
        if rule.horizon != x.shape[1] or rule.classes != model.readout.out_features:
            raise e.InputError('execution rule profile mismatch')
        before = e.parameters(model)
        n = len(x)
        state, output = torch.zeros(n, x.shape[2]), torch.zeros(n, rule.classes)
        depths, active = torch.zeros(n, dtype=torch.long), torch.ones(n, dtype=torch.bool)
        reads, gate_rows = [], 0
        for t in range(rule.horizon):
            ids = active.nonzero(as_tuple=False).flatten()
            if not len(ids):
                break
            state[ids], logits = model.step(x[ids, t], state[ids])
            p = logits.softmax(-1)
            if not bool(torch.isfinite(p).all()):
                raise e.InputError('nonfinite streamed prediction')
            output[ids] = p
            depths[ids] += 1
            reads.append(ids.tolist())
            stop = rule.stop(p, t + 1)
            if rule.kind != 'fixed' and t + 1 < rule.horizon:
                gate_rows += len(ids)
            active[ids[stop]] = False
        if bool(active.any()) or e.parameters(model) != before:
            raise e.InputError('incomplete stopping or mutated model')
    return {'probabilities': output.tolist(), 'depths': depths.tolist(), 'read_rows': reads,
        'rule': rule.record(), 'model': before, 'cost': {**cost, 'cell_transitions': int(depths.sum()),
        'forward_calls': len(reads), 'gate_rows': gate_rows}, 'production_accepted': False}


def score(result, targets):
    """Call only on already sealed results; validates full read/stop accounting."""
    from experiments.shared_stem_cell.control_evaluation import probability_rows
    record = result['rule']
    rule = StopRule(**{**record, 'coefficients': tuple(tuple(r) for r in record['coefficients'])}).validate()
    n = len(targets)
    if not 1 <= n <= 4096 or any(type(y) is not int or not 0 <= y < rule.classes for y in targets):
        raise e.InputError('bounded complete score targets required')
    if any(type(result['cost'][k]) is not int or result['cost'][k] < 0 for k in
           ('cell_transitions', 'forward_calls', 'gate_rows', 'wall_ns')):
        raise e.InputError('exact nonnegative work counters required')
    p = probability_rows(result['probabilities'], n, rule.classes)
    d = result['depths']
    if (type(d) is not list or len(d) != n or any(type(t) is not int or not 1 <= t <= rule.horizon for t in d)
            or result['read_rows'] != [[i for i, depth in enumerate(d) if depth >= t]
                                      for t in range(1, max(d)+1)]
            or result['cost']['cell_transitions'] != sum(d)
            or result['cost']['forward_calls'] != max(d)
            or result['cost']['gate_rows'] != (0 if rule.kind == 'fixed' else sum(min(t, rule.horizon-1) for t in d))
            or (rule.kind == 'fixed' and any(t != rule.limit for t in d))):
        raise e.InputError('stopping/read work trace drift')
    correct = sum(max(range(rule.classes), key=row.__getitem__) == y for row,y in zip(p, targets))
    return {'cases': n, 'correct': correct, 'accuracy': correct/n, 'mean_depth': sum(d)/n,
        'net_utility': (correct-rule.step_cost*sum(d))/n,
        'charge_units': 'declared_external_accuracy_units_per_read_not_joules_or_seconds',
        'cell_transitions': sum(d), 'wall_ns': result['cost']['wall_ns'],
        'independent_evaluation': False, 'equal_flops_claim': False}
