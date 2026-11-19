"""Research-only trainable local continuation initializer for E12's finite tree.

Training can use original train-group global E12 solutions; deployment never
reads a solution. All warm starts remain subject to exact whole-tree residual
certification. This is not continuous-time FBSDE, natural reasoning or authority.
"""

from dataclasses import dataclass
from fractions import Fraction as Q
from math import isfinite, tanh
from random import Random
from time import process_time_ns

from e12_nonlinear_cert import Law, rat
from e12_local_cell_solver import _candidate_trace, _local_sweep, _paths, _round_even

DIM = 10
WIDTH = 12
EPOCHS = 80
RATE = 0.018


@dataclass(frozen=True)
class TrainingRow:
    features: tuple[float, ...]
    target: float


@dataclass(frozen=True)
class FrozenHead:
    kind: str
    hidden: tuple[tuple[float, ...], ...]
    hidden_bias: tuple[float, ...]
    readout: tuple[float, ...]
    out_bias: float
    train_rows: int
    updates: int
    fit_cpu_ns: int
    authority: str = 'DENY_ALL'

    def validate(self) -> None:
        if self.kind not in ('neural', 'linear', 'constant') or self.authority != 'DENY_ALL':
            raise ValueError('wrong model kind or policy')
        if (type(self.train_rows) is not int or self.train_rows < 1 or
            type(self.updates) is not int or self.updates < 0 or
            type(self.fit_cpu_ns) is not int or self.fit_cpu_ns < 0):
            raise ValueError('missing fit work')
        width = WIDTH if self.kind == 'neural' else 0
        if (len(self.hidden) != width or len(self.hidden_bias) != width or
            len(self.readout) != (width if width else DIM if self.kind == 'linear' else 0)):
            raise ValueError('wrong tensor shape')
        if any(len(row) != DIM for row in self.hidden):
            raise ValueError('wrong input representation')
        scalar = (self.out_bias, *self.hidden_bias, *self.readout,
                  *(v for row in self.hidden for v in row))
        if any(not isfinite(v) or abs(v) > 64 for v in scalar):
            raise ValueError('nonfinite/unbounded head coefficient')


def features(law: Law, path: str) -> tuple[float, ...]:
    """Only public root/coefficients and past random signs; no future leaf."""
    p = law.values()
    if (type(path) is not str or len(path) >= law.depth or
        any(letter not in 'LR' for letter in path)):
        raise ValueError('invalid current public prefix')
    signed = path.count('R') - path.count('L')
    x = float(p['x0'] + p['sigma'] * p['s'] * signed)
    t = len(path) / law.depth
    a = float(p['a'])
    return (x / 2.5, x * x / 6.25, x * x * x / 15.625,
            t, 1.0 - t, a, a * x / 2.5,
            signed / 3.0, law.depth / 3.0, float(p['x0']) / 2.0)


def training_rows(law: Law, interior_y: tuple[Q, ...]) -> tuple[TrainingRow, ...]:
    """Labels must be supplied by the train-only owner; no solver is called."""
    interior, _ = _paths(law.depth)
    p = law.values()
    if len(interior_y) != len(interior):
        raise ValueError('incomplete train labels')
    return tuple(TrainingRow(features(law, path), float(y / p['M']))
                 for path, y in zip(interior, interior_y))


def _checked_rows(rows: tuple[TrainingRow, ...]) -> None:
    if (type(rows) is not tuple or not rows or len(rows) > 8192 or
        any(type(r) is not TrainingRow or len(r.features) != DIM or
            any(not isfinite(v) or abs(v) > 8 for v in r.features) or
            not isfinite(r.target) or abs(r.target) > 1 for r in rows)):
        raise ValueError('invalid bounded training snapshot')


def fit_head(rows: tuple[TrainingRow, ...], kind: str) -> FrozenHead:
    """Real deterministic SGD; frozen parameters and full optimizer cost.

    Both learned arms see identical rows and epochs. A constant control is an
    analytic mean, while linear and neural perform actual per-row updates.
    """
    _checked_rows(rows)
    if kind not in ('neural', 'linear', 'constant'):
        raise ValueError('unsupported learned arm')
    start = process_time_ns()
    if kind == 'constant':
        bias = sum(r.target for r in rows) / len(rows)
        model = FrozenHead(kind, (), (), (), bias, len(rows), 0,
                           max(1, process_time_ns() - start))
        model.validate()
        return model

    rng = Random(1729)
    w1 = [[rng.uniform(-0.16, 0.16) for _ in range(DIM)] for _ in range(WIDTH)] if kind == 'neural' else []
    b1 = [0.0] * WIDTH if kind == 'neural' else []
    w2 = [rng.uniform(-0.16, 0.16) for _ in range(WIDTH)] if kind == 'neural' else [0.0] * DIM
    b2 = 0.0
    order = list(range(len(rows)))
    for _ in range(EPOCHS):
        rng.shuffle(order)
        for i in order:
            row = rows[i]
            f, target = row.features, row.target
            if kind == 'neural':
                hidden = [tanh(b1[j] + sum(w1[j][k] * f[k] for k in range(DIM)))
                          for j in range(WIDTH)]
                z = b2 + sum(w2[j] * hidden[j] for j in range(WIDTH))
                pred = tanh(z)
                grad = max(-2.0, min(2.0, (pred - target) * (1 - pred * pred)))
                old_w2 = w2[:]
                for j in range(WIDTH):
                    w2[j] -= RATE * grad * hidden[j]
                b2 -= RATE * grad
                for j in range(WIDTH):
                    g = grad * old_w2[j] * (1 - hidden[j] ** 2)
                    for k in range(DIM):
                        w1[j][k] -= RATE * g * f[k]
                    b1[j] -= RATE * g
            else:
                pred = tanh(b2 + sum(w2[k] * f[k] for k in range(DIM)))
                grad = max(-2.0, min(2.0, (pred - target) * (1 - pred * pred)))
                for k in range(DIM):
                    w2[k] -= RATE * grad * f[k]
                b2 -= RATE * grad
    model = FrozenHead(kind, tuple(tuple(r) for r in w1), tuple(b1), tuple(w2),
                       b2, len(rows), EPOCHS * len(rows),
                       max(1, process_time_ns() - start))
    model.validate()
    return model


def predict(head: FrozenHead, f: tuple[float, ...]) -> float:
    head.validate()
    if (type(f) is not tuple or len(f) != DIM or
        any(not isfinite(v) or abs(v) > 8 for v in f)):
        raise ValueError('invalid pre-boundary feature')
    if head.kind == 'neural':
        h = [tanh(b + sum(w[k] * f[k] for k in range(DIM)))
             for w, b in zip(head.hidden, head.hidden_bias)]
        raw = head.out_bias + sum(a * b for a, b in zip(head.readout, h))
    else:
        raw = head.out_bias + (sum(a * b for a, b in zip(head.readout, f))
                               if head.kind == 'linear' else 0.0)
    return tanh(raw)


def initial_y(law: Law, head: FrozenHead | None) -> tuple[Q, ...]:
    p = law.values()
    interior, _ = _paths(law.depth)
    if head is None:
        return (Q(0),) * len(interior)
    head.validate()
    return tuple(_round_even(Q(str(predict(head, features(law, path)) * float(p['M']))), 16)
                 for path in interior)


@dataclass(frozen=True)
class WarmResult:
    law: dict
    trace: object
    initial_y: tuple[str, ...]
    final_y: tuple[str, ...]
    residual: str
    rigorous_error_bound: str
    contraction_q: str
    iterations: int
    node_updates: int
    cpu_ns: int
    policy: str = 'DENY_ALL'


def solve_warm(law: Law, guess: tuple[Q, ...], *, max_calls: int = 24) -> WarmResult:
    """Run local Cell sweeps only. Every arm uses the same exact certificate.

    The old zero-initialization E12 replay is NOT a valid reviewer for this
    warm start; a separate reviewer must replay the declared initial state.
    """
    from dataclasses import asdict
    if type(law) is not Law or type(max_calls) is not int or not 1 <= max_calls <= 24:
        raise ValueError('invalid local run')
    p = law.values()
    interior, _ = _paths(law.depth)
    if (type(guess) is not tuple or len(guess) != len(interior) or
        any(type(v) is not Q or abs(v) > p['M'] for v in guess)):
        raise ValueError('invalid initial continuation projection')
    start = process_time_ns()
    y = guess
    for k in range(1, max_calls + 1):
        sweep = _local_sweep(law, y, p)
        residual = max(abs(a - b) for a, b in zip(y, sweep.mapped_y))
        bound = residual / (1 - p['q'])
        if bound <= Q(1, 10000):
            return WarmResult(asdict(law), _candidate_trace(law, y, sweep, p),
                              tuple(str(v) for v in guess), tuple(str(v) for v in y),
                              str(residual), str(bound), str(p['q']), k,
                              k * len(interior) * 2,
                              max(1, process_time_ns() - start))
        y = tuple(_round_even(v, 16) for v in sweep.mapped_y)
    raise ValueError('no global certificate before budget exhaustion')
