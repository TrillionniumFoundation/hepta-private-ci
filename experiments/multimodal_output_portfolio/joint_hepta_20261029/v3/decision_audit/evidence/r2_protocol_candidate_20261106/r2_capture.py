"""Fail-closed structural accounting for an independently exported R2 panel.

Digests authenticate bytes only. Actual evaluator custody and access-control
receipts require independent review; a JSON owner string cannot establish them.
"""

from collections import Counter
import hashlib
import itertools
import json
import math

import numpy as np

from r2_statistics import METHODS, require


CATEGORIES = {"encoder", "generation", "planner", "critic", "verification", "seal"}
OUTER = {"setup", "training", "analysis", "publication"}
FAILURES = {"failed", "cancelled", "timeout", "incomplete"}
RAW_FIELDS = {"peak_rss_bytes", "retained_disk_bytes", "network_payload_bytes", "energy_joules"}


def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def finite(value, name, nonnegative=False):
    require(type(value) in (float, int) and math.isfinite(value), f"unknown/nonfinite {name}")
    require(not nonnegative or value >= 0, f"negative {name}")
    return float(value)


def distinct(values, name):
    require(isinstance(values, list) and values and len(set(values)) == len(values), f"invalid {name} roster")
    return values


def hash_string(value, name):
    require(isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value), f"invalid {name} commitment")


def audit(bundle, protocol, *, design_sha256, capture_sha256):
    design, capture = bundle["design"], bundle["capture"]
    require(digest(design) == design_sha256, "design digest mismatch")
    require(digest(capture) == capture_sha256, "capture digest mismatch")
    require(capture["design_sha256"] == design_sha256, "capture belongs to other design")
    require(design["protocol_sha256"] == digest(protocol), "different preregistration")
    require(design["schema"] == "hepta.r2.panel-design.v1", "design schema")
    require(capture["schema"] == "hepta.r2.capture.v1", "capture schema")
    for name in ("test_seal_sha256", "custody_receipt_sha256", "candidate_manifest_sha256", "validation_selection_sha256", "tariff_manifest_sha256"):
        hash_string(design[name], name)
    tariffs = design["tariff_manifest"]
    require(digest(tariffs) == design["tariff_manifest_sha256"], "tariff manifest mismatch")
    require(tariffs["cpu_second"] == 0.02 and tariffs["wall_second"] == 0.001, "inherited tariffs changed")
    require(isinstance(tariffs["services"], dict) and tariffs["services"], "no real-action mapping")
    for key, value in tariffs["services"].items():
        require(isinstance(key, str) and bool(key), "invalid service key")
        finite(value, "sealed service tariff", True)
    clusters = distinct(design["source_clusters"], "cluster")
    seeds = distinct(design["fit_seeds"], "fit")
    require(all(isinstance(s, str) and s for s in clusters), "invalid cluster ID")
    require(seeds == protocol["analysis"]["fit_seeds"], "missing/reordered registered fit")
    require(design["draws"] == [0, 1] and design["methods"] == list(METHODS), "changed methods/draws")
    require(design["strong_reference"] in ("00", "greedy", "planner", "retrieval"), "reference not sealed before test")
    require(design["cost_unit"] == "declared_abstract_research_utility", "cost unit mismatch")
    require(design["failure_utilities"] == {s: -1.0 for s in FAILURES}, "changed predeclared failure utility")
    require(design["abstention_utility"] == 0.0, "changed abstention utility")
    require(design["budget_estimand"] == "same_total_budget", "different budget estimand")
    expected = set(itertools.product(seeds, clusters, [0, 1], METHODS))
    roster, coordinates, owners = {}, {}, {}
    for entry in capture["episodes"]:
        eid = entry["id"]
        key = (entry["fit_seed"], entry["source_cluster_id"], entry["draw"], entry["method"])
        require(isinstance(eid, str) and eid and eid not in roster, "duplicate/invalid episode ID")
        require(key in expected and key not in coordinates, "duplicate/unregistered episode coordinate")
        roster[eid], coordinates[key] = entry, eid
        event_ids = distinct(entry["event_ids"], "episode event")
        for event_id in event_ids:
            require(isinstance(event_id, str) and event_id and event_id not in owners, "physical event reused across episodes")
            owners[event_id] = eid
    require(set(coordinates) == expected, "missing registered episode, including failed fit/source")
    for event_id in distinct(capture["outer_event_ids"], "outer event"):
        require(isinstance(event_id, str) and event_id and event_id not in owners, "outer/episode event reuse")
        owners[event_id] = None
    events = {}
    for event in bundle["events"]:
        eid = event["id"]
        require(eid not in events or digest(events[eid]) == digest(event), "conflicting physical receipt retry")
        events[eid] = event
    require(set(events) == set(owners), "missing/unregistered captured event")
    costs = Counter()
    categories = {eid: set() for eid in roster}
    outer_costs, training_cells, raw_unknowns = Counter(), set(), []
    selected_costs = Counter()
    for event_id, event in events.items():
        owner = owners[event_id]
        require(event["episode_id"] == owner, "wrong event owner")
        require(event["metering"] == "exclusive", "inclusive envelope is not an additive cost leaf")
        require(event["cost_unit"] == design["cost_unit"], "mixed cost unit")
        amount = finite(event["cost"], "event cost", True)
        require(type(event["selected"]) is bool, "unknown selection")
        require(event["status"] in {"completed", "not_run"} | FAILURES, "unknown event terminal")
        cpu = finite(event["cpu_seconds"], "CPU seconds", True)
        wall = finite(event["wall_seconds"], "wall seconds", True)
        fee = finite(event["service_fee"], "real-action fee", True)
        service = event["service_tariff_key"]
        require(service in tariffs["services"], "unmapped real action")
        units = finite(event["service_units"], "service units", True)
        require(math.isclose(fee, tariffs["services"][service]*units, rel_tol=1e-10, abs_tol=1e-12), "service fee is not sealed mapping")
        require(math.isclose(amount, 0.02*cpu+0.001*wall+fee, rel_tol=1e-10, abs_tol=1e-12), "tariff/raw meter disagreement")
        if event["status"] == "not_run":
            require(cpu == wall == fee == amount == 0 and bool(event["not_run_reason"]), "not-run has actual cost or no reason")
        require(isinstance(event["unknown_raw_costs"], list), "missing unknown-cost disclosure")
        require(len(set(event["unknown_raw_costs"])) == len(event["unknown_raw_costs"]), "duplicate unknown raw field")
        require(set(event["raw_measurements"]) == RAW_FIELDS, "raw measurement coverage")
        actual_unknown = {key for key, value in event["raw_measurements"].items() if value is None}
        require(set(event["unknown_raw_costs"]) == actual_unknown, "unknown raw cost cannot be silently zeroed or hidden")
        for key, value in event["raw_measurements"].items():
            if value is not None:
                finite(value, key, True)
        raw_unknowns.extend({"event_id": event_id, "field": field} for field in event["unknown_raw_costs"])
        if owner is None:
            require(event["scope"] in OUTER, "unknown outer scope")
            outer_costs[event["scope"]] += amount
            if event["scope"] == "training":
                cell = (event["fit_seed"], event["method"])
                require(cell[0] in seeds and cell[1] in METHODS, "unregistered training receipt")
                training_cells.add(cell)
        else:
            require(event["scope"] == "episode" and event["category"] in CATEGORIES, "unknown episode cost scope/category")
            categories[owner].add(event["category"])
            costs[owner] += amount
            selected_costs["selected" if event["selected"] else "unselected"] += amount
    require(set(itertools.product(seeds, ("00", "10", "01", "11"))) <= training_cells, "missing arm/fit training or explicit no-training receipt")
    require(set(outer_costs) == OUTER, "unknown complete-lifecycle outer scope")
    rows = {}
    for row in bundle["outcomes"]:
        require(row["id"] not in rows, "duplicate outcome")
        rows[row["id"]] = row
    require(set(rows) == set(roster), "missing/extra outcome")
    payload = {"events": [events[key] for key in sorted(events)],
               "outcomes": [rows[key] for key in sorted(rows)]}
    require(capture["payload_sha256"] == digest(payload), "independently pinned capture payload changed")
    matrix = np.empty((len(seeds), len(clusters), 2, len(METHODS)), dtype=np.float64)
    fi, ci, mi = ({v: i for i, v in enumerate(items)} for items in (seeds, clusters, METHODS))
    statuses = Counter()
    for key, eid in coordinates.items():
        row = rows[eid]
        require(categories[eid] == CATEGORIES, "missing explicit category, unknown is not zero")
        require(row["status"] in {"completed", "abstained"} | FAILURES, "unknown outcome terminal")
        utility = finite(row["utility"], "independent utility")
        require(-1 <= utility <= 1, "utility domain changed")
        if row["status"] in FAILURES:
            require(utility == -1.0, "failure utility changed")
        elif row["status"] == "abstained":
            require(utility == 0.0, "abstention utility changed")
        else:
            hash_string(row["independent_label_receipt_sha256"], "label receipt")
        require(math.isclose(finite(row["sealed_cost"], "sealed cost", True), costs[eid], rel_tol=1e-10, abs_tol=1e-12), "outcome cost omits or duplicates captured work")
        fit, cluster, draw, method = key
        matrix[fi[fit], ci[cluster], draw, mi[method]] = utility-costs[eid]
        statuses[row["status"]] += 1
    return matrix, {
        "episode_count": len(roster), "unique_physical_events": len(events),
        "identical_duplicate_receipts": len(bundle["events"])-len(events),
        "status_counts": dict(statuses), "selected_and_unselected_cost": dict(selected_costs),
        "outer_costs_unamortized": dict(outer_costs), "unknown_raw_costs": raw_unknowns,
        "whole_cost_measurements_known": not raw_unknowns,
        "custody_and_truth_authenticated_by_this_checker": False,
        "external_review_required": True, "no_update": True,
    }
