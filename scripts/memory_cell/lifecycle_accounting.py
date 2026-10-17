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


# Money and physical retained bytes are separate dimensions; never add byte
# counts to CPU seconds or dollar amounts.
COST_ONCE = ("extraction", "indexing", "training")
COST_PER_QUERY = ("retrieval", "reader", "tools", "diagnostics")
COST_PER_WINDOW = ("maintenance", "revocation", "recovery")


def _usd(value):
    if value is None:
        return None
    if (
        type(value) not in (float, int)
        or not math.isfinite(value)
        or not 0 <= value <= 1e12
    ):
        raise ValueError("nonnegative finite USD cost or explicit unknown required")
    return float(value)


def complete_lifecycle_scenario(
    arms, *, queries, retention_days, price_usd_per_gib_day
):
    """Compare alternatives under explicitly supplied identical USD assumptions.

    Fixed costs are paid ONCE, per-read costs N times, and maintenance/revocation/
    recovery once per stated retention window. Raw evidence and derived snapshots
    are charged by stored GiB-days. This is algebra on caller supplied records,
    NOT a claim that those bills, quality, source rights or workload were observed.
    """
    if (
        not isinstance(arms, dict)
        or set(arms) != {"strong_rag", "candidate"}
        or not isinstance(queries, (list, tuple))
        or not 1 <= len(queries) <= 100
        or any(type(n) is not int or not 1 <= n <= 10_000_000 for n in queries)
        or len(set(queries)) != len(queries)
        or type(retention_days) is not int
        or not 1 <= retention_days <= 36500
    ):
        raise ValueError("two exact arms and bounded reuse/retention horizons required")
    price = _usd(price_usd_per_gib_day)
    inputs = {}
    for name, arm in arms.items():
        if (
            not isinstance(arm, dict)
            or set(arm)
            != {
                "fixed_usd",
                "per_query_usd",
                "per_window_usd",
                "raw_evidence_bytes",
                "snapshot_and_index_bytes",
                "receipt_sha256",
            }
            or not isinstance(arm["receipt_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", arm["receipt_sha256"])
        ):
            raise ValueError("bounded source-bound cost receipt required")
        mapped = {}
        for key, names in (
            ("fixed_usd", COST_ONCE),
            ("per_query_usd", COST_PER_QUERY),
            ("per_window_usd", COST_PER_WINDOW),
        ):
            values = arm[key]
            if not isinstance(values, dict) or set(values) != set(names):
                raise ValueError("exactly declared cost components required")
            mapped[key] = {k: _usd(values[k]) for k in names}
        raw = arm["raw_evidence_bytes"]
        extra = arm["snapshot_and_index_bytes"]
        if (
            type(raw) is not int
            or not 0 < raw <= 10**15
            or type(extra) is not int
            or not 0 <= extra <= 10**15
        ):
            raise ValueError("raw evidence and snapshot bytes must be retained")
        inputs[name] = (mapped, raw, extra, arm["receipt_sha256"])
    output = []
    for n in queries:
        both = {}
        for name in ("strong_rag", "candidate"):
            categories, raw, extra, pin = inputs[name]
            known = 0.0
            missing = []
            for section, multiplier in (
                ("fixed_usd", 1),
                ("per_query_usd", n),
                ("per_window_usd", 1),
            ):
                for k, value in categories[section].items():
                    if value is None:
                        missing.append(f"{section}.{k}")
                    else:
                        known += multiplier * value
            storage = (
                None
                if price is None
                else (raw + extra) / 1024**3 * retention_days * price
            )
            if storage is None:
                missing.append("storage_rate_usd_per_gib_day")
            else:
                known += storage
            both[name] = {
                "receipt_sha256": pin,
                "raw_evidence_bytes_retained": raw,
                "derived_bytes_retained": extra,
                "storage_usd_for_horizon": storage,
                "known_nonnegative_lower_bound_usd": known,
                "unknown_cost_components": sorted(missing),
                "complete_projected_cost_usd": known if not missing else None,
                "complete_projected_usd_per_query": (
                    known / n if not missing else None
                ),
            }
        a = both["strong_rag"]["complete_projected_cost_usd"]
        b = both["candidate"]["complete_projected_cost_usd"]
        both["candidate_minus_strong_rag_usd"] = (
            b - a if a is not None and b is not None else None
        )
        both["candidate_cheaper_on_supplied_assumptions"] = (
            b < a if a is not None and b is not None else None
        )
        output.append({"queries": n, "arms": both})
    return {
        "schema": "hepta.memory-cell.full-tco-reuse-scenario.v1",
        "currency": "USD",
        "retention_days": retention_days,
        "storage_price_usd_per_gib_day": price,
        "horizons": output,
        "observed_future_queries": 0,
        "real_program_quality_and_tool_parity_authenticated": False,
        "billing_and_nonoverlap_independently_authenticated": False,
        "operational_recovery_and_revocation_qualified": False,
        "economic_superiority_established": False,
        "production_accepted": False,
    }


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
