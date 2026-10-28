"""Report every planned slot; never turn absence, fixture passes or tail maxima into claims."""

from collections import Counter
import math
import statistics

from contracts import CONTROLS, LANES, SCHEMA


def distribution(values):
    values = list(values)
    if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("invalid elapsed value")
    values.sort()
    return {"n": len(values), "min": min(values) if values else None,
        "median": statistics.median(values) if values else None,
        "max": max(values) if values else None,
        "empirical_p95": values[math.ceil(0.95 * len(values)) - 1] if len(values) >= 100 else None,
        "tail_note": "p95 omitted below 100 samples; otherwise a finite-sample estimate, never stable p95"}


def summarize(plan, corpus, rows):
    expected = {(lane, case["id"], repeat) for lane in LANES for case in corpus["cases"]
                for repeat in range(plan["repeats"])}
    observed = set()
    for row in rows:
        key = (row["lane"], row["case"], row["repeat"])
        if key not in expected or key in observed:
            raise ValueError("unexpected or duplicate result slot")
        observed.add(key)
        if row["group"] != plan["group"] or row["mode"] != plan["mode"]:
            raise ValueError("mixed group/mode results")
        if row["status"] not in ("passed", "failed", "held", "not_run"):
            raise ValueError("unknown result status")
        if row["status"] == "passed" and (row["case"] not in CONTROLS or row["owner_scope"] != "qualification_fixture"):
            raise ValueError("this adapter cannot attest production or representative-case success")
        if row["status"] == "passed":
            distribution([row.get("wall_ms")])
    if observed != expected:
        raise ValueError("missing planned result slots")
    summaries = []
    for lane in LANES:
        for case in corpus["cases"]:
            selected = [r for r in rows if r["lane"] == lane and r["case"] == case["id"]]
            attempts = [r for r in selected if r["status"] in ("passed", "failed") and r.get("wall_ms") is not None]
            summaries.append({"lane": lane, "case": case["id"],
                "statuses": dict(Counter(r["status"] for r in selected)),
                "attempted_wall_ms_including_failures": distribution([r["wall_ms"] for r in attempts]),
                "successful_wall_ms": distribution([r["wall_ms"] for r in attempts if r["status"] == "passed"]),
                "successful_only_is_selection_biased": any(r["status"] != "passed" for r in selected)})
    return {"schema": SCHEMA, "group": plan["group"], "mode": plan["mode"],
        "planned_slots": len(expected), "statuses": dict(Counter(r["status"] for r in rows)),
        "case_summaries": summaries, "production_qualification": "held",
        "comparative_performance_claims": "held", "ratios": None,
        "gates": {"production_owner_adapter": "not implemented by fixture_v2",
            "representative_coverage": "held until actual execution and independent oracle checks",
            "model_identity": "replay is synthetic; live model alias alone does not pin weights",
            "request_parity": "ceilings alone do not prove equal instructions/context/provider options",
            "metrics": "retain original PID/cgroup coverage; no global CPU/PSS or per-case resource claim"}}
