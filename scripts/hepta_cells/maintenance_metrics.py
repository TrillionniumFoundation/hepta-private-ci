"""Measured windows for Cell experiments; unavailable meters remain unknown.

Windows can contain one another and are never added by this module. A process
high-water mark covers its lifetime, including work before the measured window.
It is not a campaign process-tree peak or an energy measurement.
"""

from collections import Counter
import math
import sys
import time

try:
    import resource
except ImportError:
    resource = None


def _usage():
    if resource is None:
        return None
    try:
        own = resource.getrusage(resource.RUSAGE_SELF)
        children = resource.getrusage(resource.RUSAGE_CHILDREN)
    except (OSError, ValueError):
        return None
    scale = (
        1
        if sys.platform == "darwin"
        else 1024
        if sys.platform.startswith("linux")
        else None
    )
    return {
        "self_cpu_seconds": own.ru_utime + own.ru_stime,
        "reaped_children_cpu_seconds": children.ru_utime + children.ru_stime,
        "self_lifetime_peak_rss_bytes": int(own.ru_maxrss * scale) if scale else None,
        "reaped_children_max_peak_rss_bytes": int(children.ru_maxrss * scale)
        if scale
        else None,
    }


class Measurement:
    """Observe a synchronous window, including failure, without claiming coverage.

    Access ``result`` after exiting the context. Child CPU includes only children
    reaped during this interval; it can miss surviving/detached work. Concurrent
    activity in the same process also contributes to CPU and high-water marks.
    """

    def __init__(self, stage, scope, *, parent_scope=None):
        if not all(type(value) is str and value for value in (stage, scope)):
            raise ValueError("stage and scope must be nonempty strings")
        if parent_scope is not None and (
            type(parent_scope) is not str or not parent_scope
        ):
            raise ValueError("parent scope must be a nonempty string or None")
        self.stage, self.scope, self.parent_scope = stage, scope, parent_scope
        self.result = None

    def __enter__(self):
        if hasattr(self, "_wall"):
            raise ValueError("a measurement cannot be reused")
        self._before = _usage()
        self._wall, self._cpu = time.perf_counter_ns(), time.process_time_ns()
        return self

    def __exit__(self, error_type, error, traceback):
        wall, cpu, after = time.perf_counter_ns(), time.process_time_ns(), _usage()
        child_cpu = None
        if self._before is not None and after is not None:
            delta = (
                after["reaped_children_cpu_seconds"]
                - self._before["reaped_children_cpu_seconds"]
            )
            if delta >= 0:
                child_cpu = delta
        self.result = {
            "schema": "hepta.measurement-window.v1",
            "stage": self.stage,
            "scope": self.scope,
            "parent_scope": self.parent_scope,
            "status": "returned" if error_type is None else "raised",
            "error_type": None if error_type is None else error_type.__name__,
            "wall_ns": wall - self._wall,
            "parent_process_cpu_ns": cpu - self._cpu,
            "reaped_children_cpu_seconds": child_cpu,
            "resource_before": self._before,
            "resource_after": after,
            "campaign_process_tree_peak_rss_bytes": None,
            "energy_joules": None,
            "queue_peak_items": None,
            "coverage": "inclusive window; process CPU may include concurrent work; child CPU covers reaped children only",
            "memory_scope": "resource snapshots are process-lifetime high-water marks; children maximum is not a concurrent sum",
            "additive": False,
            "full_system_cost_known": False,
        }
        return False


def summarize_tasks(rows, *, duration_key="wall_ns", scope):
    """Linear-interpolated percentiles over actual durations, with missing counts.

    Missing values are excluded only from the explicitly labelled observed
    distribution. A missing/failed duration is never silently encoded as zero.
    """
    values, missing = [], 0
    for row in rows:
        value = row.get(duration_key)
        if value is None:
            missing += 1
        elif type(value) is not int or value < 0:
            raise ValueError("duration must be a nonnegative integer or None")
        else:
            values.append(value)
    values.sort()

    def quantile(q):
        if not values:
            return None
        position = (len(values) - 1) * q
        left, right = math.floor(position), math.ceil(position)
        return (values[left] + (values[right] - values[left]) * (position - left)) / 1e6

    return {
        "scope": scope,
        "count": len(values) + missing,
        "observed_count": len(values),
        "missing_count": missing,
        "coverage_complete": missing == 0 and bool(values),
        "observed_p50_ms": quantile(0.50),
        "observed_p95_ms": quantile(0.95),
        "observed_p99_ms": quantile(0.99),
        "percentile_method": "linear interpolation over observed durations; no minimum-tail-sample claim",
    }


def summarize_decisions(rows):
    counts, reasons = Counter(), Counter()
    for row in rows:
        decision = row.get("decision")
        if decision not in ("Adopt", "NoUpdate"):
            raise ValueError(
                "only completed Adopt/NoUpdate decisions can be summarized"
            )
        reason = row.get("reason")
        if type(reason) is not str or not reason:
            raise ValueError("completed decisions must retain their reason")
        counts[decision] += 1
        if decision == "NoUpdate":
            reasons[reason] += 1
    total = sum(counts.values())
    return {
        "completed_decisions": total,
        "adopt": counts["Adopt"],
        "no_update": counts["NoUpdate"],
        "no_update_fraction": counts["NoUpdate"] / total if total else None,
        "no_update_reasons": dict(sorted(reasons.items())),
    }
