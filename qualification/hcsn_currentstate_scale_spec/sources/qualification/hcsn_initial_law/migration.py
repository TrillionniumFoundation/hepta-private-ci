"""Conservative initial-law migration for the frozen joint DDE research model.

Source laws are uniform spatial cells, a shifted exponential tail, and uniform
remaining delay cells. Spatial lift is linear nodal rounding except x<h is
clamped to the first interior node. This avoids inventing an initial lower hit;
its unavoidable near-boundary mean bias is reported. Upper overshoot maps to
the explicit permanently active escape coordinate. No law is renormalized.
"""

from dataclasses import dataclass
from bisect import bisect_right
from decimal import Decimal, localcontext
from fractions import Fraction as F
import math

import numpy as np

from qualification.hcsn_boundary_audit.refractory_transport import Packet


def exact(value):
    """Pin decimal round-trip values of supplied finite JSON/FP64 scalars."""
    if isinstance(value, (bool, np.bool_)):
        raise ValueError("boolean is not a law coefficient")
    if isinstance(value, F):
        return value
    if isinstance(value, (int, np.integer)):
        return F(int(value))
    if isinstance(value, (float, np.floating)) and math.isfinite(float(value)):
        return F(str(float(value)))
    raise ValueError("finite rational/int/float required")


def _decimal(value):
    return Decimal(value.numerator) / Decimal(value.denominator)


def _at(x, nodes):
    result = [F(0)] * len(nodes)
    x = min(nodes[-1], max(nodes[1], x))
    left = min(bisect_right(nodes, x) - 1, len(nodes) - 2)
    ratio = (x - nodes[left]) / (nodes[left + 1] - nodes[left])
    result[left], result[left + 1] = 1 - ratio, ratio
    return result


@dataclass(frozen=True)
class MigrationBasis:
    original_endpoint: F
    active_cells: int
    tail_rate: F
    delay: F
    phase_cells: int
    target_endpoint: F
    intervals: int
    actual_nodes: tuple | None = None

    def __post_init__(self):
        for name in ("original_endpoint", "tail_rate", "delay", "target_endpoint"):
            object.__setattr__(self, name, exact(getattr(self, name)))
        if (
            type(self.active_cells) is not int
            or not 1 <= self.active_cells <= 256
            or type(self.phase_cells) is not int
            or not 1 <= self.phase_cells <= 128
            or type(self.intervals) is not int
            or not 4 <= self.intervals <= 512
            or not 0 < self.original_endpoint <= self.target_endpoint <= 8
            or self.tail_rate <= 0
            or not 0 < self.delay <= 2
        ):
            raise ValueError("invalid source or target reconstruction basis")
        nodes = (
            tuple(
                self.target_endpoint * j / self.intervals
                for j in range(self.intervals + 1)
            )
            if self.actual_nodes is None
            else tuple(map(exact, self.actual_nodes))
        )
        if (
            len(nodes) != self.intervals + 1
            or nodes[0] != 0
            or nodes[-1] != self.target_endpoint
            or any(b <= a for a, b in zip(nodes, nodes[1:]))
        ):
            raise ValueError("actual nodes must strictly span zero to target endpoint")
        object.__setattr__(self, "actual_nodes", nodes)

    @property
    def spacing(self):
        """Mean grid spacing; lift uses actual_nodes on every segment."""
        return self.target_endpoint / self.intervals

    def lift(self):
        """Return exact mass-conservative rows plus separate approximation data."""
        nodes, n = self.actual_nodes, self.intervals
        h = nodes[1]
        max_width = max(b - a for a, b in zip(nodes, nodes[1:]))
        rows, diagnostics = [], []
        for cell in range(self.active_cells):
            lo = self.original_endpoint * cell / self.active_cells
            hi = self.original_endpoint * (cell + 1) / self.active_cells
            cuts = sorted({lo, hi, *(x for x in nodes[1:-1] if lo < x < hi)})
            row = [F(0)] * (n + 1)
            for left, right in zip(cuts[:-1], cuts[1:]):
                a, b = _at(left, nodes), _at(right, nodes)
                for j in range(n + 1):
                    row[j] += (right - left) * (a[j] + b[j]) / (2 * (hi - lo))
            lower_bias = max(F(0), min(hi, h) - lo)
            lower_bias = lower_bias * (h - (lo + min(hi, h)) / 2) / (hi - lo)
            diagnostics.append(
                {
                    "kind": "uniform",
                    "lower_mean_shift": float(lower_bias),
                    "mapped_mean": float(sum(x * w for x, w in zip(nodes, row))),
                    "original_mean": float((lo + hi) / 2),
                    "w1_upper_bound": float(max_width / 2 + lower_bias),
                    "upper_overshoot_probability": 0.0,
                }
            )
            rows.append(tuple(row))
        # Integrate exp density times each linear hat at high precision. The
        # final upper coordinate receives the explicitly reported tiny decimal
        # closure remainder, so rationalized row sums are EXACTLY one.
        with localcontext() as ctx:
            ctx.prec = 80
            rate, origin = _decimal(self.tail_rate), _decimal(self.original_endpoint)
            endpoint = _decimal(self.target_endpoint)
            tail = [Decimal(0)] * (n + 1)
            cuts = sorted(
                {
                    self.original_endpoint,
                    self.target_endpoint,
                    *(
                        x
                        for x in nodes[1:-1]
                        if self.original_endpoint < x < self.target_endpoint
                    ),
                }
            )
            for left, right in zip(cuts[:-1], cuts[1:]):
                width = _decimal(right - left)
                first = (-rate * (_decimal(left) - origin)).exp()
                decay = (-rate * width).exp()
                zeroth = first * (1 - decay)
                moment = first * ((1 - decay) / rate - width * decay)
                a, b = _at(left, nodes), _at(right, nodes)
                for j in range(n + 1):
                    tail[j] += (
                        _decimal(a[j]) * zeroth + _decimal(b[j] - a[j]) * moment / width
                    )
            overshoot = (-rate * (endpoint - origin)).exp()
            tail[-1] += overshoot
            row = [F(x) for x in tail]
            correction = 1 - sum(row)
            row[-1] += correction
            if any(x < 0 for x in row) or abs(correction) > F(1, 10**70):
                raise ArithmeticError("tail integration/closure unresolved")
            lower_bias = Decimal(0)
            if self.original_endpoint < h:
                width = _decimal(h - self.original_endpoint)
                lower_bias = width - (1 - (-rate * width).exp()) / rate
            diagnostics.append(
                {
                    "kind": "shifted_exponential",
                    "lower_mean_shift": float(lower_bias),
                    "original_mean": float(self.original_endpoint + 1 / self.tail_rate),
                    "mapped_mean": float(sum(x * w for x, w in zip(nodes, row))),
                    "upper_overshoot_probability": float(overshoot),
                    "upper_expected_overshoot": float(overshoot / rate),
                    "w1_upper_bound": float(
                        _decimal(max_width / 2) + lower_bias + overshoot / rate
                    ),
                    "decimal_precision": 80,
                    "upper_row_closure_correction": str(correction),
                }
            )
            rows.append(tuple(row))
        if any(sum(row) != 1 or row[0] != 0 or min(row) < 0 for row in rows):
            raise ArithmeticError(
                "lift must be conservative, nonnegative and have no lower atom"
            )
        return Lift(self, tuple(rows), tuple(diagnostics))


@dataclass(frozen=True)
class Lift:
    basis: MigrationBasis
    weights: tuple[tuple[F, ...], ...]
    diagnostics: tuple[dict, ...]


@dataclass(frozen=True)
class MigratedLaw:
    active: tuple[F, ...]
    content: tuple[tuple[F, ...], ...]
    phase: tuple[Packet, ...]
    report: dict

    def solve_inputs(self):
        """One explicit FP64 conversion; phase Packet retains rational support."""
        return (
            np.asarray(self.active, dtype=np.float64),
            np.asarray(self.content, dtype=np.float64),
            self.phase,
        )


def migrate(basis, probability, content, *, identity="migration", lift=None):
    """Lift one law and signed marks with the SAME nonnegative linear map.

    Exact totals refer to decimal round-trip rationalized input coefficients;
    final FP64 solve input has separately measured conversion residuals. The
    source law need not sum to one, and is never normalized by this adapter.
    """
    if (
        not isinstance(basis, MigrationBasis)
        or not isinstance(identity, str)
        or not identity
    ):
        raise ValueError("validated basis and nonempty identity required")
    expected = basis.active_cells + 1 + basis.phase_cells
    p = tuple(map(exact, probability))
    marked = tuple(tuple(map(exact, row)) for row in content)
    if (
        len(p) != expected
        or len(marked) != expected
        or min(p) < 0
        or not marked
        or not 1 <= len(marked[0]) <= 16
        or any(len(row) != len(marked[0]) for row in marked)
    ):
        raise ValueError("source law/content shape or probability sign mismatch")
    lift = basis.lift() if lift is None else lift
    if not isinstance(lift, Lift) or lift.basis != basis:
        raise ValueError("lift cache must bind the identical source/target basis")
    weights, diagnostics = lift.weights, lift.diagnostics
    if len(weights) != basis.active_cells + 1:
        raise ValueError("lift does not match source basis")
    # Recheck supplied cache entries: never trust row-normalized or lower-hit
    # cache data merely because its dimensions match.
    if any(
        len(row) != basis.intervals + 1 or row[0] != 0 or min(row) < 0 or sum(row) != 1
        for row in weights
    ):
        raise ValueError("invalid conservative lift cache")
    channels = len(marked[0])
    active = tuple(
        sum((p[i] * row[j] for i, row in enumerate(weights)), F(0))
        for j in range(basis.intervals + 1)
    )
    moved = tuple(
        tuple(
            sum((marked[i][k] * row[j] for i, row in enumerate(weights)), F(0))
            for k in range(channels)
        )
        for j in range(basis.intervals + 1)
    )
    phase = []
    for j in range(basis.phase_cells):
        i = basis.active_cells + 1 + j
        if p[i] == 0:
            if any(marked[i]):
                raise ValueError(
                    "zero-probability phase with nonzero signed measure unsupported by Packet"
                )
            continue
        phase.append(
            Packet(
                f"{identity}-phase-{j}",
                basis.delay * j / basis.phase_cells,
                basis.delay * (j + 1) / basis.phase_cells,
                p[i],
                marked[i],
            )
        )
    output_mass = sum(active) + sum((x.mass for x in phase), F(0))
    input_content = tuple(sum(row[k] for row in marked) for k in range(channels))
    output_content = tuple(
        sum(row[k] for row in moved) + sum((x.content[k] for x in phase), F(0))
        for k in range(channels)
    )
    if output_mass != sum(p) or output_content != input_content:
        raise ArithmeticError("exact migration mass or content changed")
    active_fp = np.asarray(active, dtype=np.float64)
    content_fp = np.asarray(moved, dtype=np.float64)
    if not np.isfinite(active_fp).all() or not np.isfinite(content_fp).all():
        raise ArithmeticError("FP64 conversion overflow")
    report = {
        "kind": "interior_clamped_linear_hat_initial_law_migration",
        "exact_input_mass": str(sum(p)),
        "exact_output_mass": str(output_mass),
        "exact_input_content": list(map(str, input_content)),
        "exact_output_content": list(map(str, output_content)),
        "lower_atom": str(active[0]),
        "upper_escape_mass": float(active[-1]),
        "source_tail_mass": float(p[basis.active_cells]),
        "weighted_w1_upper_bound": sum(
            float(p[i]) * diagnostics[i]["w1_upper_bound"] for i in range(len(weights))
        ),
        "fp64_active_mass_conversion_residual": float(
            active_fp.sum() - float(sum(active))
        ),
        "fp64_content_conversion_residual": (
            content_fp.sum(0)
            - np.asarray([float(sum(row[k] for row in moved)) for k in range(channels)])
        ).tolist(),
        "basis_diagnostics": diagnostics,
        "actual_node_fractions": list(map(str, basis.actual_nodes)),
        "limitations": "Initial law only. Lower clipping, nodal rounding, upper escape, decimal-tail integration and FP64 solve errors remain separate. No filtering, training, gradients or all-domain rollout admission.",
    }
    return MigratedLaw(active, moved, tuple(phase), report)
