"""Measured research costs, never a source of production qualification.

Inclusive envelopes form a tree: training inside writing, or inference inside
reading, is counted once. Missing measurements stay unknown. A future-reuse curve
is an explicitly conditional projection, not a measurement or a speedup claim.
"""

from dataclasses import asdict, dataclass
import math
import re

PHASES = frozenset(
    {"extract", "index", "train", "write", "read", "maintain", "recover"}
)


def nonnegative(value):
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or not 0 <= value <= 1e12
    ):
        raise ValueError("finite bounded nonnegative measurement required")
    return float(value)


@dataclass(frozen=True)
class Envelope:
    identity: str
    phase: str
    seconds: float | None
    receipt_sha256: str
    clock_domain: str
    parent: str | None = None


def summarize_envelopes(items):
    """Count only inclusive roots; validate every child, even unused diagnostics."""
    if not 1 <= len(items) <= 10000:
        raise ValueError("bounded measurement census required")
    by_id = {}
    for item in items:
        if (
            not isinstance(item, Envelope)
            or not isinstance(item.identity, str)
            or not 1 <= len(item.identity) <= 256
            or item.identity in by_id
            or item.phase not in PHASES
            or not isinstance(item.clock_domain, str)
            or not 1 <= len(item.clock_domain) <= 256
            or not re.fullmatch(r"[0-9a-f]{64}", item.receipt_sha256)
        ):
            raise ValueError("duplicate or unbound measurement")
        if item.seconds is not None:
            nonnegative(item.seconds)
        by_id[item.identity] = item
    children = {key: [] for key in by_id}
    for item in items:
        seen, cursor = set(), item
        while cursor.parent is not None:
            if cursor.identity in seen or cursor.parent not in by_id:
                raise ValueError("cyclic or missing envelope parent")
            seen.add(cursor.identity)
            parent = by_id[cursor.parent]
            if parent.clock_domain != cursor.clock_domain:
                raise ValueError("nested measurements must share a clock domain")
            cursor = parent
        if item.parent is not None:
            children[item.parent].append(item)
    for parent in items:
        known_children = sum(
            c.seconds for c in children[parent.identity] if c.seconds is not None
        )
        if parent.seconds is not None and known_children > parent.seconds + 1e-6:
            raise ValueError("disjoint child envelopes exceed inclusive parent")
    roots = [item for item in items if item.parent is None]
    missing = sorted(PHASES - {item.phase for item in items})
    unknown = sorted(item.identity for item in roots if item.seconds is None)
    known = sum(item.seconds for item in roots if item.seconds is not None)
    return dict(
        measurements=[asdict(item) for item in items],
        inclusive_root_ids=[item.identity for item in roots],
        recorded_root_seconds=known,
        missing_phases=missing,
        unknown_root_ids=unknown,
        complete_recorded_seconds=known if not missing and not unknown else None,
        mixed_clock_domains=len({item.clock_domain for item in roots}) != 1,
        is_single_elapsed_wall_clock=False,
        external_measurement_truth_authenticated=False,
        production_lifecycle_cost=None,
    )


def reuse_projection(
    *,
    fixed_seconds,
    read_seconds_per_query,
    maintenance_seconds_per_query,
    recovery_seconds_per_query,
    queries,
):
    """Apply F + N(R + M + D); a caller must explicitly supply every term.

    Zero is accepted only when explicitly supplied. Unknown terms are not silently
    inferred from successful replay or from absent failures in a small sample.
    Per-query recovery/maintenance are amortized workload assumptions, not rates
    learned here. Reference hardware and quality comparability need separate proof.
    """
    if not queries or len(queries) > 100 or len(set(queries)) != len(queries):
        raise ValueError("unique bounded reuse horizon required")
    if any(type(n) is not int or not 1 <= n <= 10_000_000 for n in queries):
        raise ValueError("invalid reuse count")
    inputs = dict(
        fixed=fixed_seconds,
        read=read_seconds_per_query,
        maintenance=maintenance_seconds_per_query,
        recovery=recovery_seconds_per_query,
    )
    for value in inputs.values():
        if value is not None:
            nonnegative(value)
    unknown = [name for name, value in inputs.items() if value is None]
    per_read = sum(
        value for name, value in inputs.items() if name != "fixed" and value is not None
    )
    rows = []
    for n in queries:
        known = (fixed_seconds if fixed_seconds is not None else 0) + n * per_read
        rows.append(
            dict(
                queries=n,
                measured_terms_projection_seconds=known,
                complete_projection_seconds=known if not unknown else None,
                complete_amortized_seconds=known / n if not unknown else None,
            )
        )
    return dict(
        assumptions=inputs,
        unknown_terms=unknown,
        horizons=rows,
        observed_future_queries=0,
        economic_or_quality_advantage_established=False,
    )


def paired_task_contrasts(rows, questions, arms, candidate):
    """Task correctness, not source-ID coverage, decides the observed comparison."""
    if (
        not questions
        or len(set(questions)) != len(questions)
        or len(set(arms)) != len(arms)
        or candidate not in arms
        or len(rows) != len(questions) * len(arms)
        or {(r["question_id"], r["arm"]) for r in rows}
        != {(q, a) for q in questions for a in arms}
    ):
        raise ValueError("exact paired task census required")
    grouped = {q: {} for q in questions}
    for row in rows:
        if row["status"] not in ("succeeded", "failed"):
            raise ValueError("unknown execution status")
        if (
            row["status"] == "succeeded"
            and type(row.get("strict_task_success")) is not bool
        ):
            raise ValueError("missing actual task outcome")
        if row["status"] == "failed" and row.get("strict_task_success") is not None:
            raise ValueError("failure cannot carry a success score")
        grouped[row["question_id"]][row["arm"]] = row
    output = {}
    for baseline in arms:
        if baseline == candidate:
            continue
        wins = losses = missing = changed_without_win = 0
        for group in grouped.values():
            a, b = group[baseline], group[candidate]
            if a["kind"] != b["kind"] or a["candidate_digest"] != b["candidate_digest"]:
                raise ValueError("task or candidate pool drift")
            if a["status"] != "succeeded" or b["status"] != "succeeded":
                missing += 1
                continue
            win = b["strict_task_success"] and not a["strict_task_success"]
            wins += win
            losses += a["strict_task_success"] and not b["strict_task_success"]
            changed_without_win += a["selected"] != b["selected"] and not win
        output[baseline] = dict(
            wins=wins,
            losses=losses,
            missing_pairs=missing,
            changed_selection_without_task_win=changed_without_win,
            all_planned_effect_bounds=[
                (wins - losses - missing) / len(questions),
                (wins - losses + missing) / len(questions),
            ],
            observed_positive_difference=missing == 0 and wins > losses,
            significance_established=False,
        )
    return output
