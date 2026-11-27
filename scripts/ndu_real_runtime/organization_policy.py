"""Read-only ORG-1 finite-panel review; no structural execution or adoption.

The caller's protocol pin checks identity, not prospective registration. Original
artifact hashes check bytes, not measurement authenticity or scientific benefit.
Differentiation can be investigated as a split; sleep/retirement are unsupported.
"""

import math
import statistics

from .causal_protocol import digest
from .causal_topology import ARMS, validate_topology_pair
from .metering import canonical_sha
from .organization_artifacts import _Reader

STAGES = (
    "search",
    "training",
    "evaluation",
    "inference",
    "communication",
    "loading",
    "migration",
    "relearning",
    "maintenance",
    "recovery",
)
AXES = (
    "cpu_seconds",
    "accelerator_seconds",
    "transferred_bytes",
    "resident_byte_seconds",
)
TRIGGERS = {
    "stable_cluster": "cluster_stability",
    "learning_interference": "paired_heldout_score_drop",
    "capacity_bottleneck": "measured_capacity_pressure",
    "specialization": "estimated_call_or_quality_gain",
}
CONTRACTS = (
    "initial_artifacts_sha256",
    "objective_sha256",
    "scheduler_sha256",
    "scheduler_tuning_sha256",
    "evaluation_sha256",
    "before_graph_sha256",
    "before_state_sha256",
    "capability_inventory_sha256",
)


def _number(value, *, low=0, high=1e100):
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or not low <= value <= high
    ):
        raise ValueError("expected a finite bounded number, never boolean")
    return value


def _name(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        raise ValueError("expected a bounded nonempty identity")
    return value


def _unique(values, *, maximum=256):
    if not isinstance(values, list) or not 1 <= len(values) <= maximum:
        raise ValueError("expected a bounded nonempty identity list")
    names = [_name(value) for value in values]
    if len(names) != len(set(names)):
        raise ValueError("duplicate identity")
    return set(names)


def _protocol(protocol):
    if (
        protocol["schema"] != "hepta.org1.protocol.v1"
        or protocol["scope"] != "synthetic_reference"
    ):
        raise ValueError("only the ORG-1 synthetic reference protocol is supported")
    if protocol["operation"] not in {"split", "merge", "rewire"}:
        raise ValueError(
            "unsupported structure operation; retirement is not authorized"
        )
    _name(protocol["candidate_id"])
    contracts = protocol["contracts"]
    if set(contracts) != set(CONTRACTS) or not all(
        digest(v) for v in contracts.values()
    ):
        raise ValueError("complete frozen artifact contracts required")
    rule = protocol["trigger_rule"]
    if TRIGGERS.get(rule["kind"]) != rule["metric"]:
        raise ValueError("unsupported trigger; low utilization alone is insufficient")
    for key, minimum in (("minimum_windows", 2), ("minimum_samples_per_window", 1)):
        if type(rule[key]) is not int or not minimum <= rule[key] <= 256:
            raise ValueError("invalid trigger replication threshold")
    if _number(rule["minimum_value"]) <= 0:
        raise ValueError("a positive observed trigger threshold is required")
    roster = protocol["roster"]
    _unique([r["pair_id"] for r in roster])
    if not {"ordinary", "retention"} <= {r["panel"] for r in roster}:
        raise ValueError(
            "ordinary outcome and old-capability retention panels are required"
        )
    if len({(r["task_id"], r["seed"]) for r in roster}) != len(roster):
        raise ValueError("a task and seed cannot be counted as multiple planned pairs")
    for row in roster:
        _name(row["task_id"])
        if type(row["seed"]) is not int or not 0 <= row["seed"] < 2**32:
            raise ValueError("invalid task seed")
        if row["panel"] not in {"ordinary", "retention", "rare_fault"}:
            raise ValueError("unsupported evaluation panel")
        if row["panel"] == "rare_fault":
            _name(row["capability_id"])
        elif row["capability_id"] is not None:
            raise ValueError("only fault tasks may name protected capabilities")
    protected = protocol["protected_capabilities"]
    _unique([p["capability_id"] for p in protected])
    for item in protected:
        if _number(item["minimum_score"], high=1) <= 0:
            raise ValueError("protected capabilities need a positive recovery score")
        _number(item["maximum_drop"], high=1)
    axes = _unique(protocol["required_cost_axes"], maximum=8)
    if not set(AXES) <= axes or not axes <= {
        *AXES,
        "energy_joules",
        "provider_charges",
    }:
        raise ValueError(
            "required organization resource axes are absent or unsupported"
        )
    if set(protocol["utility_rates"]) != axes or set(protocol["budget"]) != axes:
        raise ValueError("rates and budgets must cover the exact frozen resource axes")
    for values in (protocol["utility_rates"], protocol["budget"]):
        for value in values.values():
            _number(value)
    if "provider_charges" in axes:
        _name(protocol["provider_charges_unit"])
    if _number(protocol["minimum_mean_net_gain"]) <= 0:
        raise ValueError("a positive practical-gain threshold is required")
    _number(protocol["maximum_retention_drop"], high=1)
    if protocol["comparison_method"] != "finite_paired_panel":
        raise ValueError("unsupported statistical comparison")


def _trigger(protocol, references, reader, pin):
    rule, windows, ids, samples = protocol["trigger_rule"], [], set(), set()
    if not isinstance(references, list) or len(references) > 256:
        raise ValueError("invalid trigger window inventory")
    for ref in references:
        row = reader.read(ref)
        if row.get("protocol_sha256") != pin:
            return False
        identity = _name(row["window_id"])
        if identity in ids:
            raise ValueError("duplicate trigger window")
        ids.add(identity)
        if _number(row["start"]) >= _number(row["end"]):
            raise ValueError("invalid observation window")
        members = _unique(row["sample_ids"], maximum=4096)
        if (
            type(row["samples"]) is not int
            or row["samples"] != len(members)
            or samples & members
        ):
            raise ValueError("trigger sample denominator is duplicated or inconsistent")
        samples.update(members)
        _number(row["value"], low=-1e100)
        if rule["kind"] == "stable_cluster":
            _name(row["cluster_id"])
        if rule["kind"] == "learning_interference":
            control, updated = row["control_scores"], row["updated_scores"]
            if (
                len(control) != row["samples"]
                or len(updated) != len(control)
                or not digest(row["intervention_sha256"])
            ):
                raise ValueError(
                    "paired local-update intervention observations are required"
                )
            observed = statistics.mean(
                _number(a, high=1) - _number(b, high=1)
                for a, b in zip(control, updated)
            )
            if not math.isclose(observed, row["value"], rel_tol=0, abs_tol=1e-12):
                raise ValueError("interference metric differs from paired observations")
        if rule["kind"] == "capacity_bottleneck":
            used, capacity = row["used"], row["capacity"]
            if (
                len(used) != row["samples"]
                or len(capacity) != len(used)
                or any(_number(c) <= 0 for c in capacity)
            ):
                raise ValueError("paired positive capacity measurements are required")
            observed = statistics.mean(_number(u) / c for u, c in zip(used, capacity))
            if not math.isclose(observed, row["value"], rel_tol=0, abs_tol=1e-12):
                raise ValueError("capacity pressure differs from measured usage/limits")
        windows.append(row)
    windows.sort(key=lambda row: row["start"])
    if any(a["end"] > b["start"] for a, b in zip(windows, windows[1:])):
        raise ValueError("trigger windows overlap")
    return (
        len(windows) >= rule["minimum_windows"]
        and all(
            w["samples"] >= rule["minimum_samples_per_window"]
            and w["value"] >= rule["minimum_value"]
            for w in windows
        )
        and (
            rule["kind"] != "stable_cluster"
            or len({w["cluster_id"] for w in windows}) == 1
        )
    )


def _costs(protocol, references, reader, reasons, arm, event_ids, run_id, pin):
    axes, stages = protocol["required_cost_axes"], set()
    totals = {axis: 0.0 for axis in axes}
    if not isinstance(references, list) or len(references) > len(STAGES):
        raise ValueError("one complete disjoint aggregate per cost stage is required")
    for ref in references:
        event = reader.read(ref)
        if (event.get("arm_id"), event.get("run_id"), event.get("protocol_sha256")) != (
            arm,
            run_id,
            pin,
        ):
            reasons.append(f"COST_OWNERSHIP_MISMATCH:{arm}")
        identity, stage = _name(event["event_id"]), event["stage"]
        if identity in event_ids or stage in stages or stage not in STAGES:
            raise ValueError("duplicate or unsupported organization cost event")
        event_ids.add(identity)
        stages.add(stage)
        values = event["values"]
        if set(values) != set(axes):
            reasons.append(f"COST_AXES_INCOMPLETE:{arm}:{stage}")
        if set(values) - set(axes):
            raise ValueError("cost event names an unregistered resource axis")
        if (
            "provider_charges" in axes
            and event.get("provider_charges_unit") != protocol["provider_charges_unit"]
        ):
            raise ValueError("provider charge units differ from the frozen protocol")
        for axis in axes:
            value = values.get(axis)
            if value is None:
                totals[axis] = None
                reasons.append(f"UNKNOWN_COST:{arm}:{stage}:{axis}")
            elif totals[axis] is None:
                _number(value)
            else:
                totals[axis] += _number(value)
                _number(totals[axis])
    if stages != set(STAGES):
        reasons.append(f"MISSING_COST_STAGES:{arm}")
        return totals, None
    for axis, total in totals.items():
        if total is not None and total > protocol["budget"][axis]:
            reasons.append(f"BUDGET_EXCEEDED:{arm}:{axis}")
    converted = (
        None
        if None in totals.values()
        else math.fsum(totals[a] * protocol["utility_rates"][a] for a in axes)
    )
    if converted is not None:
        _number(converted)
    return totals, converted


def _trials(protocol, references, reader, reasons, arm, run_id, pin):
    planned = {row["pair_id"]: row for row in protocol["roster"]}
    seen = {}
    if not isinstance(references, list) or len(references) > 256:
        raise ValueError("invalid outcome inventory")
    for ref in references:
        row = reader.read(ref)
        if (row.get("arm_id"), row.get("run_id"), row.get("protocol_sha256")) != (
            arm,
            run_id,
            pin,
        ):
            reasons.append(f"TRIAL_OWNERSHIP_MISMATCH:{arm}")
        pair = _name(row["pair_id"])
        if pair in seen:
            raise ValueError(
                "duplicate trial; retries cannot replace original attempts"
            )
        if pair not in planned:
            reasons.append(f"UNPLANNED_TRIAL:{arm}:{pair}")
            continue
        expected = planned[pair]
        if type(row["seed"]) is not int or (row["task_id"], row["seed"]) != (
            expected["task_id"],
            expected["seed"],
        ):
            reasons.append(f"TRIAL_IDENTITY_MISMATCH:{arm}:{pair}")
        status, score = row["status"], row["score"]
        if status not in {
            "completed",
            "failed",
            "timed_out",
            "cancelled",
            "unresolved",
        }:
            raise ValueError("unsupported original trial terminal status")
        if score is not None:
            _number(score, high=1)
        if status == "unresolved" or status == "completed" and score is None:
            reasons.append(f"UNRESOLVED_TRIAL:{arm}:{pair}")
            score = None
        elif status != "completed":
            if score not in (None, 0):
                raise ValueError(
                    "failed/cancelled/timed-out attempts cannot receive success credit"
                )
            score = 0.0
        seen[pair] = {"status": status, "score": score}
    if set(seen) != set(planned):
        reasons.append(f"INCOMPLETE_TRIAL_DENOMINATOR:{arm}")
    return seen


def review_organization(
    protocol,
    evidence,
    evidence_root,
    *,
    trusted_protocol_sha256,
    trusted_observer_sha256=(),
):
    """Screen referenced observations and raw D evidence, never grant authority."""
    _protocol(protocol)
    pin = canonical_sha(protocol)
    if evidence["schema"] != "hepta.org1.evidence.v1":
        raise ValueError("unsupported organization evidence schema")
    reader, reasons = _Reader(evidence_root), []
    if trusted_protocol_sha256 != pin or evidence["protocol_sha256"] != pin:
        reasons.append("FROZEN_PROTOCOL_MISMATCH")
    contracts = protocol["contracts"]
    inventory_ref = evidence["capability_inventory"]
    inventory = reader.read(inventory_ref)
    if inventory["schema"] != "hepta.org1.capabilities.v1":
        raise ValueError("unsupported protected capability inventory")
    protected = _unique(inventory["protected"])
    if inventory_ref["sha256"] != contracts[
        "capability_inventory_sha256"
    ] or protected != {p["capability_id"] for p in protocol["protected_capabilities"]}:
        reasons.append("PROTECTED_CAPABILITY_INVENTORY_MISMATCH")
    trigger = _trigger(protocol, evidence["trigger_windows"], reader, pin)
    if not trigger:
        reasons.append("TRIGGER_NOT_REPRODUCED")
    fixed, dynamic = evidence["fixed_topology"], evidence["dynamic_topology"]
    topology = validate_topology_pair(
        fixed, dynamic, evidence_root, trusted_observer_sha256=trusted_observer_sha256
    )
    if topology["status"] != "EVIDENCE_CONSISTENT":
        reasons.append("TOPOLOGY_EVIDENCE_BLOCKED")
    if dynamic.get("transition", {}).get("kind") != protocol["operation"]:
        reasons.append("STRUCTURE_OPERATION_MISMATCH")
    for receipt in (fixed, dynamic):
        refs = receipt.get("artifacts", {})
        if receipt.get("adaptive_scheduler_sha256") != contracts["scheduler_sha256"]:
            reasons.append("SCHEDULER_MISMATCH")
        if (
            refs.get("before_state", {}).get("sha256")
            != contracts["before_state_sha256"]
        ):
            reasons.append("INITIAL_STATE_MISMATCH")
        if (
            "before_graph" not in refs
            or canonical_sha(reader.read(refs["before_graph"]))
            != contracts["before_graph_sha256"]
        ):
            reasons.append("INITIAL_GRAPH_MISMATCH")
    if set(evidence["arms"]) != set(ARMS):
        raise ValueError(
            "both fixed and dynamic arms, and only those arms, are required"
        )
    trials, costs, totals, event_ids = {}, {}, {}, set()
    for arm, receipt in zip(ARMS, (fixed, dynamic)):
        data = evidence["arms"][arm]
        if data["contracts"] != contracts:
            reasons.append(f"ARM_CONTRACT_MISMATCH:{arm}")
        run_id = receipt.get("run_id")
        trials[arm] = _trials(
            protocol, data["trials"], reader, reasons, arm, run_id, pin
        )
        totals[arm], costs[arm] = _costs(
            protocol, data["costs"], reader, reasons, arm, event_ids, run_id, pin
        )
    for arm, checked in zip(ARMS, topology["arms"]):
        if checked["status"] == "EVIDENCE_CONSISTENT":
            known = checked["cost_inventory"]["methods"][arm]["measurements"]
            floors = {
                "cpu_seconds": known["cpu_seconds"]["observed_sum"],
                "transferred_bytes": checked["organization_counters"]["messages"][
                    "message_bytes"
                ],
            }
            for axis, floor in floors.items():
                if totals[arm][axis] is not None and totals[arm][axis] < floor:
                    reasons.append(f"KNOWN_TOPOLOGY_COST_OMITTED:{arm}:{axis}")
    ordinary, paired = [], []
    for row in protocol["roster"]:
        pair = row["pair_id"]
        values = [trials[arm].get(pair) for arm in ARMS]
        if any(v is None or v["score"] is None for v in values):
            continue
        baseline, candidate = values
        paired.append(pair)
        gain = candidate["score"] - baseline["score"]
        if row["panel"] == "ordinary":
            ordinary.append(gain)
        else:
            if any(v["status"] != "completed" for v in values):
                reasons.append("RETENTION_FAILURE:" + pair)
            if gain < -protocol["maximum_retention_drop"]:
                reasons.append("RETENTION_LOSS:" + pair)
        if row["panel"] == "rare_fault":
            obligation = next(
                (
                    p
                    for p in protocol["protected_capabilities"]
                    if p["capability_id"] == row["capability_id"]
                ),
                None,
            )
            if (
                obligation is None
                or any(v["status"] != "completed" for v in values)
                or candidate["score"] < obligation["minimum_score"]
                or gain < -obligation["maximum_drop"]
            ):
                reasons.append("PROTECTED_CAPABILITY_LOSS:" + row["capability_id"])
    tested = {
        r["capability_id"] for r in protocol["roster"] if r["panel"] == "rare_fault"
    }
    if tested != protected:
        reasons.append("PROTECTED_CAPABILITY_PANEL_INCOMPLETE")
    mean_gain = None
    if len(paired) == len(protocol["roster"]) and all(
        v is not None for v in costs.values()
    ):
        # Charge every observed construction/maintenance cost to this fixed panel.
        # No assumed future tasks or retrospective amortization are supported.
        mean_gain = statistics.mean(ordinary) - (costs[ARMS[1]] - costs[ARMS[0]]) / len(
            ordinary
        )
        _number(mean_gain, low=-1e100)
        if mean_gain <= protocol["minimum_mean_net_gain"]:
            reasons.append("NET_GAIN_NOT_SUFFICIENT")
    else:
        reasons.append("NET_GAIN_UNRESOLVED")
    return {
        "schema": "hepta.org1.review.v1",
        "status": "HOLD" if reasons else "REFERENCE_CONSISTENT",
        "proposal_trigger_supported": trigger,
        "finite_panel_passed": not reasons,
        "planned_pairs": len(protocol["roster"]),
        "observed_pairs": len(paired),
        "mean_net_gain": mean_gain,
        "cost_totals": totals,
        "converted_costs": costs,
        "reasons": sorted(set(reasons)),
        "topology": topology,
        "protocol_sha256": pin,
        "scientific_acceptance": "HOLD",
        "decision": "NoUpdate",
        "benefit_proven": False,
        "adoption_authorized": False,
        "runtime_authority": False,
        "full_physical_cost_known": False,
        "measurement_authenticity_verified": False,
        "inventory_completeness_verified": False,
        "preregistration_verified": False,
        "scope": "finite synthetic reference panel; strong-scheduler qualification and native owner review remain external",
    }
