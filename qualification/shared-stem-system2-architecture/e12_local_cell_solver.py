"""Oracle-free local-message solver for the registered E12 finite nonlinear law.

Every forward Cell sees only its local X/Y and public coefficients. Every
backward Cell sees only local X plus its two successor continuation messages.
No pretrained model, global-solution input, original E12 operator/solver,
production selection or general continuous-time FBSDE theorem is involved.
"""

from dataclasses import asdict, dataclass
from fractions import Fraction as Q
from time import perf_counter_ns, process_time_ns

from e12_nonlinear_cert import Law, Solve, State, Trace, rat


@dataclass(frozen=True)
class ForwardMessage:
    path: str
    x: Q
    y_guess: Q
    x_left: Q
    x_right: Q


@dataclass(frozen=True)
class BackwardMessage:
    path: str
    x: Q
    y_left: Q
    y_right: Q
    continuation: Q
    z: Q


@dataclass(frozen=True)
class CellSweep:
    forwards: tuple[ForwardMessage, ...]
    backwards: tuple[BackwardMessage, ...]
    terminal_y: tuple[Q, ...]
    mapped_y: tuple[Q, ...]


@dataclass(frozen=True)
class LocalIteration:
    index: int
    residual: str
    global_bound: str
    forward_cells: int
    backward_cells: int
    accepted: bool


@dataclass(frozen=True)
class LocalCellRun:
    result: Solve
    iterations: tuple[LocalIteration, ...]
    forward_cell_invocations: int
    backward_cell_invocations: int
    reference_operator_calls: int = 0
    pretrained_model_forwards: int = 0
    continuous_time_fbsde_proven: bool = False
    natural_reasoning_gain_proven: bool = False
    production_accepted: bool = False
    authority: str = "DENY_ALL"


def _nonlinear(x: Q) -> Q:
    # Independent expression: no original E12 phi/operator call.
    return Q(x.numerator * x.denominator,
             x.numerator * x.numerator + x.denominator * x.denominator)


def _cell_forward(path: str, x: Q, y_guess: Q, p: dict) -> ForwardMessage:
    middle = x + p["a"] * p["h"] * _nonlinear(y_guess)
    return ForwardMessage(path, x, y_guess,
                          middle - p["sigma"] * p["s"],
                          middle + p["sigma"] * p["s"])


def _cell_backward(path: str, x: Q, yl: Q, yr: Q, p: dict) -> BackwardMessage:
    continuation = ((yl + yr) / 2 + p["beta"] * p["h"] * _nonlinear(x)) / (
        1 + p["lam"] * p["h"])
    z = (yr - yl) / (2 * p["s"])
    return BackwardMessage(path, x, yl, yr, continuation, z)


def _round_even(x: Q, bits: int) -> Q:
    # Round signed rationals to registered Q bits; no original E12 helper.
    target = x * (1 << bits)
    floor = target.numerator // target.denominator
    fraction = target - floor
    if fraction > Q(1, 2) or (fraction == Q(1, 2) and floor % 2):
        floor += 1
    return Q(floor, 1 << bits)


def _paths(depth: int) -> tuple[tuple[str, ...], tuple[str, ...]]:
    interior = []
    frontier = ("",)
    for _ in range(depth):
        interior.extend(frontier)
        frontier = tuple(p + sign for p in frontier for sign in ("L", "R"))
    return tuple(interior), frontier


def _local_sweep(law: Law, y_guess: tuple[Q, ...], p: dict) -> CellSweep:
    internal, terminal = _paths(law.depth)
    if (type(y_guess) is not tuple or len(y_guess) != len(internal) or
        any(type(y) is not Q or abs(y) > p["M"] for y in y_guess)):
        raise ValueError("wrong public-prefix candidate or invariant domain")

    x_nodes = {"": p["x0"]}
    forward = []
    for path, y in zip(internal, y_guess):
        msg = _cell_forward(path, x_nodes[path], y, p)
        forward.append(msg)
        x_nodes[path + "L"] = msg.x_left
        x_nodes[path + "R"] = msg.x_right

    backward_values = {path: p["g"] * _nonlinear(x_nodes[path]) for path in terminal}
    backward = []
    for path in reversed(internal):
        msg = _cell_backward(path, x_nodes[path], backward_values[path + "L"],
                             backward_values[path + "R"], p)
        backward_values[path] = msg.continuation
        backward.append(msg)
    return CellSweep(tuple(forward), tuple(backward),
                     tuple(backward_values[path] for path in terminal),
                     tuple(backward_values[path] for path in internal))


def _candidate_trace(law: Law, y_guess: tuple[Q, ...], sweep: CellSweep, p: dict) -> Trace:
    internal, terminal = _paths(law.depth)
    x = {"": p["x0"]}
    for msg in sweep.forwards:
        x[msg.path + "L"] = msg.x_left
        x[msg.path + "R"] = msg.x_right
    # These are the CANDIDATE interior Y, not the mapped continuation values.
    y = dict(zip(internal, y_guess))
    y.update(zip(terminal, sweep.terminal_y))
    z = tuple(str((y[path + "R"] - y[path + "L"]) / (2 * p["s"]))
              for path in internal)
    states = tuple(State(str(x[path]), str(y[path])) for path in internal + terminal)
    return Trace(states, z)


def solve_local_cells(law: Law, *, tolerance: str = "1/10000", bits: int = 16,
                      max_calls: int = 24) -> LocalCellRun:
    """Iterate bounded per-prefix Cell messages; never read a precomputed solution.

    This is synchronous spatial message passing with chronological X propagation
    and backward continuation reduction, not parallel-in-time execution.
    All work counters count actual mathematical Cell calls, not GPU time.
    """
    if type(law) is not Law:
        raise ValueError("law must be the registered exact E12 profile")
    p = law.values()  # Global contraction admission is mandatory.
    eps = rat(tolerance)
    if (not Q(0) < eps <= Q(1, 100) or type(bits) is not int or
        not 12 <= bits <= 22 or type(max_calls) is not int or
        not 1 <= max_calls <= 24):
        raise ValueError("invalid exact precision, budget or target error")
    count = (1 << law.depth) - 1
    y_guess = (Q(0),) * count
    iterations = []
    cpu = process_time_ns()
    wall = perf_counter_ns()
    for index in range(1, max_calls + 1):
        sweep = _local_sweep(law, y_guess, p)
        residual = max(abs(a - b) for a, b in zip(y_guess, sweep.mapped_y))
        bound = residual / (1 - p["q"])
        accepted = bound <= eps
        iterations.append(LocalIteration(index, str(residual), str(bound),
                                         len(sweep.forwards), len(sweep.backwards),
                                         accepted))
        if accepted:
            result = Solve(
                asdict(law), _candidate_trace(law, y_guess, sweep, p),
                str(residual), str(bound), str(p["q"]), str(eps),
                index, index - 1, bits, process_time_ns() - cpu,
                perf_counter_ns() - wall, True,
            )
            if result.cpu_ns <= 0 or result.wall_ns <= 0:
                raise ValueError("unmeasurable local computation")
            return LocalCellRun(result, tuple(iterations), index * count,
                                index * count)
        y_guess = tuple(_round_even(y, bits) for y in sweep.mapped_y)
    raise ValueError("local-Cell iteration budget exhausted: NO CERTIFICATE")
