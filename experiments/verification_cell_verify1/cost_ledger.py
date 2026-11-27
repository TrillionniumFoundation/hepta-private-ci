"""Declared exclusive resource charges; completeness is not physical coverage.

Resource IDs must name disjoint attribution scopes. A host must not charge the
same parent/child CPU twice under different IDs. Hashes bind supplied receipts,
not their truth. Peak RSS is a maximum, never an additive resource cost.
"""

from dataclasses import asdict, dataclass
import math

from .contracts import _require, _sha, _text, digest


METRICS = ("wall_seconds", "process_cpu_seconds", "energy_joules", "external_charge")
STAGES = ("risk", "training", "fit", "checker", "repair", "evaluation", "other")
STATUSES = ("completed", "failed", "cancelled", "not_run")


def _number(value, name):
    _require(type(value) in (int, float), f"invalid {name}")
    try:
        value = float(value)
    except OverflowError as error:
        raise ValueError(f"nonfinite {name}") from error
    _require(math.isfinite(value) and 0 <= value <= 1e18, f"invalid {name}")
    return value


@dataclass(frozen=True)
class CostItem:
    operation_id: str
    attempt_id: str
    stage: str
    resource_id: str
    clock_id: str

    def __post_init__(self):
        for name in ("operation_id", "attempt_id", "resource_id", "clock_id"):
            _text(getattr(self, name), name)
            _require(len(getattr(self, name)) <= 256, "cost identity too long")
        _require(type(self.stage) is str and self.stage in STAGES, "invalid cost stage")


@dataclass(frozen=True)
class CostReceipt:
    item: CostItem
    status: str
    started_ns: int
    finished_ns: int
    process_cpu_seconds: float | None
    peak_rss_bytes: int | None
    energy_joules: float | None
    external_charge: float | None
    evidence_sha256: str
    measurement_gaps: tuple[str, ...]
    published: bool = True

    def __post_init__(self):
        _require(type(self.item) is CostItem, "exact cost item required")
        _require(
            type(self.status) is str and self.status in STATUSES, "invalid cost status"
        )
        _require(type(self.published) is bool, "published must be bool")
        _require(
            all(
                type(value) is int and 0 <= value <= 2**63 - 1
                for value in (self.started_ns, self.finished_ns)
            )
            and self.finished_ns >= self.started_ns,
            "invalid monotonic interval",
        )
        for name in METRICS[1:]:
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _number(value, name))
        _require(
            self.peak_rss_bytes is None
            or type(self.peak_rss_bytes) is int
            and 0 <= self.peak_rss_bytes <= 2**63 - 1,
            "invalid peak RSS bytes",
        )
        _sha(self.evidence_sha256, "evidence_sha256")
        gaps = self.measurement_gaps
        _require(
            type(gaps) in (tuple, list) and len(gaps) <= 16, "invalid measurement gaps"
        )
        for gap in gaps:
            _text(gap, "measurement gap")
        _require(len(set(gaps)) == len(gaps), "duplicate measurement gap")
        _require(
            not any(
                getattr(self, name) is None
                for name in METRICS[1:] + ("peak_rss_bytes",)
            )
            or bool(gaps),
            "missing measurements need reasons",
        )
        object.__setattr__(self, "measurement_gaps", tuple(gaps))
        if self.status == "not_run":
            _require(
                self.started_ns == self.finished_ns
                and all(
                    getattr(self, name) in (None, 0)
                    for name in METRICS[1:] + ("peak_rss_bytes",)
                ),
                "not-run receipt cannot claim resource consumption",
            )

    @property
    def wall_seconds(self):
        return (self.finished_ns - self.started_ns) / 1e9


def summarize_costs(roster, receipts, rates=None):
    """Validate frozen item bindings and aggregate declared exclusive charges.

    Nanoseconds use a declared monotonic clock identity. Same-clock/same-resource
    intervals must not overlap. Different resources can run concurrently; their
    wall charges are resource-seconds, not global elapsed time. CPU must be an
    exclusive interval delta, not a process-lifetime or overlapping child total.
    Rates, when supplied, must name all four metrics in one declared utility unit.
    A zero rate is an explicit pricing assumption, not evidence of free work.
    """
    _require(
        type(roster) in (tuple, list) and 0 < len(roster) <= 10000,
        "bounded cost roster required",
    )
    _require(all(type(row) is CostItem for row in roster), "invalid cost roster")
    planned = {row.operation_id: row for row in roster}
    _require(len(planned) == len(roster), "duplicate planned cost item")
    _require(
        type(receipts) in (tuple, list) and len(receipts) <= len(roster),
        "invalid receipt array",
    )
    _require(all(type(row) is CostReceipt for row in receipts), "invalid cost receipt")
    observed = {row.item.operation_id: row for row in receipts}
    _require(len(observed) == len(receipts), "duplicate cost receipt")
    _require(
        all(planned.get(key) == row.item for key, row in observed.items()),
        "cost item drift",
    )
    intervals, clock_intervals = {}, {}
    for row in receipts:
        if row.started_ns == row.finished_ns:
            continue
        interval = (row.started_ns, row.finished_ns)
        intervals.setdefault((row.item.clock_id, row.item.resource_id), []).append(
            interval
        )
        clock_intervals.setdefault(row.item.clock_id, []).append(interval)
    for group in intervals.values():
        group.sort()
        _require(
            all(left[1] <= right[0] for left, right in zip(group, group[1:])),
            "overlapping exclusive cost intervals",
        )
    missing_operations = sorted(set(planned) - set(observed))
    totals, known, missing = {}, {}, {}
    for metric in METRICS:
        values = [getattr(row, metric) for row in receipts]
        known[metric] = math.fsum(value for value in values if value is not None)
        missing[metric] = sum(value is None for value in values)
        totals[metric] = (
            None if missing[metric] or missing_operations else known[metric]
        )
    utility = None
    if rates is not None:
        _require(
            type(rates) is dict and set(rates) == set(METRICS),
            "rates must name every cost metric",
        )
        rates = {key: _number(value, "utility rate") for key, value in rates.items()}
        if not any(rates[metric] > 0 and missing[metric] for metric in METRICS):
            utility = math.fsum(rates[metric] * known[metric] for metric in METRICS)
            _require(math.isfinite(utility), "utility conversion overflow")
    # Even fully measured supplied receipts do not prove all physical work was listed.
    spans = {
        clock: (max(end for _, end in values) - min(start for start, _ in values)) / 1e9
        for clock, values in clock_intervals.items()
    }
    rss = [row.peak_rss_bytes for row in receipts]
    return {
        "schema": "hepta.verify.cost-ledger.v1",
        "declared_roster_complete": not missing_operations,
        "planned_operations": len(roster),
        "recorded_operations": len(receipts),
        "missing_operations": missing_operations,
        "totals": totals,
        "known_partial_totals": known,
        "missing_metric_counts": missing,
        "wall_charge_unit": "resource_seconds",
        "observed_monotonic_clock_spans_seconds": spans,
        "global_elapsed_seconds": (
            next(iter(spans.values()), 0)
            if not missing_operations and len({row.clock_id for row in roster}) == 1
            else None
        ),
        "peak_rss_bytes": max(rss)
        if not missing_operations and rss and None not in rss
        else None,
        "known_partial_peak_rss_bytes": max(
            (value for value in rss if value is not None), default=None
        ),
        "peak_rss_aggregation": "maximum_observed_scope_peak_not_concurrent_host_memory",
        "utility_rates": rates,
        "declared_receipt_utility": utility,
        "utility_covers_declared_roster": utility is not None
        and not missing_operations,
        "status_counts": {
            status: sum(row.status == status for row in receipts) for status in STATUSES
        },
        "stage_counts": {
            stage: sum(row.item.stage == stage for row in receipts) for stage in STAGES
        },
        "unpublished_operations": sum(not row.published for row in receipts),
        "measurement_gaps": sorted(
            {gap for row in receipts for gap in row.measurement_gaps}
        ),
        "roster_sha256": digest(
            [asdict(row) for row in sorted(roster, key=lambda row: row.operation_id)]
        ),
        "receipts_sha256": digest(
            [
                asdict(row)
                for row in sorted(receipts, key=lambda row: row.item.operation_id)
            ]
        ),
        "exclusive_attribution_proved": False,
        "full_physical_cost_complete": False,
        "cost_units": "declared_utility",
        "production_authority": "NONE",
    }
