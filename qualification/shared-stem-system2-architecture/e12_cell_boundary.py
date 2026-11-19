"""Research-only E12 nonlinear stochastic Cell boundary handoff audit.

Every cell is a separate one-step local message. The independently validated
whole-tree numerical candidate is reconstructed only when ALL forward/backward
interfaces, terminal values and martingale Z coefficients match. This does not
solve general continuous-time FBSDEs or authorize production execution.
"""

from dataclasses import asdict, dataclass
from fractions import Fraction as Q
from hashlib import sha256
import json
import re

from e12_nonlinear_cert import Law, Solve
from e12_independent_audit import audit

_CANONICAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _exact(raw: str) -> Q:
    if type(raw) is not str or not 1 <= len(raw) <= 2500 or not _CANONICAL.fullmatch(raw):
        raise ValueError("noncanonical/oversized rational boundary")
    value = Q(raw)
    if str(value) != raw or max(value.numerator.bit_length(), value.denominator.bit_length()) > 7200:
        raise ValueError("unbounded rational boundary")
    return value


def _nonlinear(v: Q) -> Q:
    n, d = v.numerator, v.denominator
    return Q(n * d, n * n + d * d)


def _keys(depth: int) -> tuple[tuple[str, ...], tuple[str, ...]]:
    frontier = ("",)
    interiors = []
    for _ in range(depth):
        interiors.extend(frontier)
        frontier = tuple(child for key in frontier for child in (key + "L", key + "R"))
    return tuple(interiors), frontier


def _receipt_sha256(result: Solve) -> str:
    return sha256(json.dumps(asdict(result), sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CellSegment:
    path: str
    scope_digest: str
    x_start: str
    y_start: str
    x_left: str
    x_right: str
    y_left: str
    y_right: str
    z: str


@dataclass(frozen=True)
class TerminalCell:
    path: str
    scope_digest: str
    x: str
    y: str


@dataclass(frozen=True)
class SegmentBundle:
    law: dict
    scope_digest: str
    original_receipt_sha256: str
    claimed_residual: str
    claimed_global_error_bound: str
    claimed_contraction: str
    segments: tuple[CellSegment, ...]
    terminals: tuple[TerminalCell, ...]
    authority: str = "DENY_ALL"
    production_accepted: bool = False
    general_fbsde_wellposedness_proven: bool = False
    natural_reasoning_gain_proven: bool = False


@dataclass(frozen=True)
class SegmentReview:
    checked_internal_cells: int
    checked_terminal_cells: int
    exact_forward_interfaces: bool
    exact_backward_interfaces: bool
    exact_terminal_law: bool
    exact_conditional_martingale_z: bool
    maximum_local_backward_residual: str
    entire_tree_fixed_point_residual: str
    certified_discrete_global_error_bound: str
    continuous_time_fbsde_proven: bool = False
    natural_reasoning_gain_proven: bool = False
    independent_source_owner_authenticated: bool = False
    production_accepted: bool = False
    authority: str = "DENY_ALL"


def split_result(law: Law, result: Solve, scope_digest: str) -> SegmentBundle:
    """Serialize E12's frozen public-prefix tree into per-Cell local messages."""
    if (type(law) is not Law or type(result) is not Solve or
        type(scope_digest) is not str or not _DIGEST.fullmatch(scope_digest) or
        result.law != asdict(law) or result.authority != "DENY_ALL" or
        result.production_accepted is not False or
        result.real_pretrained_forwards != 0 or
        result.qualified_discrete_bound is not True):
        raise ValueError("nonadmitted original research candidate/scope")
    law.values()
    paths, leaves = _keys(law.depth)
    states = result.trace.states
    if len(states) != len(paths) + len(leaves) or len(result.trace.z) != len(paths):
        raise ValueError("incomplete original public-prefix trace")
    segments = tuple(
        CellSegment(path, scope_digest, states[k].x, states[k].y,
                    states[2 * k + 1].x, states[2 * k + 2].x,
                    states[2 * k + 1].y, states[2 * k + 2].y,
                    result.trace.z[k])
        for k, path in enumerate(paths)
    )
    terminals = tuple(
        TerminalCell(path, scope_digest, states[len(paths) + j].x,
                     states[len(paths) + j].y)
        for j, path in enumerate(leaves)
    )
    return SegmentBundle(asdict(law), scope_digest, _receipt_sha256(result),
                         result.mapped_residual, result.fixed_point_error_bound,
                         result.contraction_q, segments, terminals)


def review_segments(law: Law, result: Solve, bundle: SegmentBundle,
                    expected_scope_digest: str) -> SegmentReview:
    """Reject locally plausible but globally incompatible Cell boundary claims."""
    if (type(law) is not Law or type(result) is not Solve or type(bundle) is not SegmentBundle or
        type(expected_scope_digest) is not str or not _DIGEST.fullmatch(expected_scope_digest) or
        bundle.law != asdict(law) or bundle.scope_digest != expected_scope_digest or
        bundle.original_receipt_sha256 != _receipt_sha256(result) or
        bundle.authority != "DENY_ALL" or bundle.production_accepted is not False or
        bundle.general_fbsde_wellposedness_proven is not False or
        bundle.natural_reasoning_gain_proven is not False or
        result.authority != "DENY_ALL" or result.production_accepted is not False):
        raise ValueError("scope, source or forbidden authority claim")
    params = law.values()
    paths, leaves = _keys(law.depth)
    if (type(bundle.segments) is not tuple or type(bundle.terminals) is not tuple or
        len(bundle.segments) != len(paths) or len(bundle.terminals) != len(leaves) or
        any(type(s) is not CellSegment or s.path != key or
            s.scope_digest != expected_scope_digest
            for s, key in zip(bundle.segments, paths)) or
        any(type(s) is not TerminalCell or s.path != key or
            s.scope_digest != expected_scope_digest
            for s, key in zip(bundle.terminals, leaves))):
        raise ValueError("missing, repeated, reordered or cross-scope Cells")

    # Verify the numeric source independently BEFORE trusting its reported bound.
    if audit(law, result).certified is not True:
        raise ValueError("original whole-tree certificate rejected")
    if (bundle.claimed_residual != result.mapped_residual or
        bundle.claimed_global_error_bound != result.fixed_point_error_bound or
        bundle.claimed_contraction != result.contraction_q):
        raise ValueError("published Cell boundary result disagrees with source")

    n = len(paths)
    nodes: dict[str, tuple[Q, Q]] = {}
    backward_local = Q(0)
    for segment in bundle.segments:
        x, y = _exact(segment.x_start), _exact(segment.y_start)
        xl, xr = _exact(segment.x_left), _exact(segment.x_right)
        yl, yr = _exact(segment.y_left), _exact(segment.y_right)
        z = _exact(segment.z)
        center = x + params["a"] * params["h"] * _nonlinear(y)
        if (abs(y) > params["M"] or
            xl != center - params["sigma"] * params["s"] or
            xr != center + params["sigma"] * params["s"]):
            raise ValueError("local forward equation or invariant region violated")
        if z * (2 * params["s"]) != yr - yl:
            raise ValueError("incorrect conditional martingale coefficient Z")
        # On a two-support driver, this also checks the conditional covariance
        # regression and both zero orthogonal-martingale residuals.
        mean = (yl + yr) / 2
        if (yl - mean != -z * params["s"] or
            yr - mean != z * params["s"]):
            raise ValueError("conditional martingale representation failed")
        predicted_y = (mean + params["beta"] * params["h"] * _nonlinear(x)) / (
            1 + params["lam"] * params["h"])
        backward_local = max(backward_local, abs(y - predicted_y))
        nodes[segment.path] = (x, y)
        nodes[segment.path + "L"] = (xl, yl)  # confirmed at next interface
        nodes[segment.path + "R"] = (xr, yr)

    # Independent boundary match: do NOT overwrite a parent continuation value
    # with a child start value. A mismatch invalidates the assembled graph.
    for segment in bundle.segments:
        for child_path, x_raw, y_raw in (
            (segment.path + "L", segment.x_left, segment.y_left),
            (segment.path + "R", segment.x_right, segment.y_right),
        ):
            if child_path in paths:
                child = bundle.segments[paths.index(child_path)]
                target = (child.x_start, child.y_start)
            else:
                child = bundle.terminals[leaves.index(child_path)]
                target = (child.x, child.y)
            if (x_raw, y_raw) != target:
                raise ValueError("nonzero parent/child X or continuation-Y interface jump")

    for terminal in bundle.terminals:
        x, y = _exact(terminal.x), _exact(terminal.y)
        if y != params["g"] * _nonlinear(x):
            raise ValueError("terminal condition is not the registered objective")
        nodes[terminal.path] = (x, y)
    if nodes[""][0] != params["x0"]:
        raise ValueError("wrong global initial condition")

    # Independently reconstruct complete backward map from terminal leaves,
    # not from the proposed interior Y or the potentially misleading local
    # backward residual. Only this residual admits the global q certificate.
    mapped = {path: nodes[path][1] for path in leaves}
    for key in reversed(paths):
        mean = (mapped[key + "L"] + mapped[key + "R"]) / 2
        mapped[key] = (mean + params["beta"] * params["h"] * _nonlinear(nodes[key][0])) / (
            1 + params["lam"] * params["h"])
    residual = max(abs(nodes[key][1] - mapped[key]) for key in paths)
    global_bound = residual / (1 - params["q"])
    if (str(residual) != bundle.claimed_residual or
        str(global_bound) != bundle.claimed_global_error_bound or
        str(params["q"]) != bundle.claimed_contraction or
        global_bound > _exact(result.requested_tolerance)):
        raise ValueError("global exact residual/bound is not certified")
    # Exact original provenance, not just an equal scalar bound.
    for k, key in enumerate(paths + leaves):
        original = result.trace.states[k]
        if nodes[key] != (_exact(original.x), _exact(original.y)):
            raise ValueError("Cell reconstruction not equal to original source path")
    return SegmentReview(n, len(leaves), True, True, True, True,
                         str(backward_local), str(residual), str(global_bound))
