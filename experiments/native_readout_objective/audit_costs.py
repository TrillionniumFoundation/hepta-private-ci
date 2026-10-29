"""Nonoverlapping measured phases; exact native-process CPU is only a subset."""

import numpy as np

from .audit_core import (
    ARMS,
    LEARNED,
    SEEDS,
    canonical,
    inspect_native_cost,
    read,
    require,
    strict_json,
)
from .audit_integrity import BASE
from .audit_training import load_shard

FIELDS = ("python_cpu_seconds", "completed_child_cpu_seconds", "wall_seconds")


def cost_values(cost):
    require(
        all(
            isinstance(cost.get(k), (int, float))
            and not isinstance(cost[k], bool)
            and np.isfinite(cost[k])
            and cost[k] >= 0
            for k in FIELDS
        ),
        "Invalid nonnegative measured phase cost",
    )


def native_identity(native, source):
    identity, counts = native["identity"], native["counters"]
    require(
        identity["schema"] == "hepta.continuous-boundary.native-identity.v1"
        and identity["binary_sha256"] == source["native_binary_sha256"]
        and identity["source_manifest_digest"]
        == source["native_source_manifest_sha256"]
        and identity["source_commit"] == BASE
        and identity["owner_authority"] == "DENY_ALL"
        and native["hardware_energy_measured"] is False,
        "Measured native process differs from published executable/source/authority",
    )
    for name in (
        "original_journal_replay_steps",
        "event_validation_kernel_steps",
        "event_validation_ndu_calls",
        "owner_ticks",
    ):
        require(
            counts[name] == 0,
            "Hidden extra original-native execution in pure research path",
        )
    require(
        counts["actual_kernel_calls"]
        == counts["total_native_kernel_calls"]
        == counts["batch_ticks"]
        and counts["actual_ndu_calls"] == counts["total_native_ndu_calls"],
        "Native total work differs from accounted pure calls",
    )


def native_work(native, cost, source, expected):
    cost_values(cost)
    native_identity(native, source)
    counters, process_cpu, residual = inspect_native_cost(native, cost)
    require(
        counters["actual_kernel_calls"] == expected["source_kernel_calls"]
        and counters["actual_ndu_calls"] == expected["native_ndu_calls"],
        "Actual native process call count differs from all retained raw rows",
    )
    require(
        counters["request_bytes"] >= expected["wire_request_bytes"]
        and counters["response_bytes"] >= expected["wire_response_bytes"],
        "Full native wire accounting omits raw requests/responses",
    )
    return counters, process_cpu, residual


def export_counts(root, receipt):
    batch = load_shard(root, receipt["native_export"])[0]
    request = {
        "command": "KernelBatch",
        "profile_sha256": receipt["profile_sha256"],
        "sequences": batch["request_sequences"],
    }
    return {
        "source_kernel_calls": receipt["rows"],
        "native_ndu_calls": 0,
        "wire_request_bytes": len(canonical(request)) + 1,
        "wire_response_bytes": len(canonical(batch["response"])) + 1,
    }


def phase_roster(seeds=SEEDS, confirmed=True):
    rows = []
    for seed in seeds:
        rows.extend(
            [("training_setup", seed, None), ("native_feature_export", seed, None)]
        )
        rows.extend(("training_development", seed, arm) for arm in LEARNED)
    if confirmed:
        for seed in seeds:
            rows.append(("confirmation_setup", seed, None))
            for arm in ARMS:
                rows.extend(
                    [("confirmation_rollout", seed, arm), ("serialization", seed, arm)]
                )
            rows.append(("diagnostic_setup", seed, None))
            rows.extend(("diagnostic_panel", seed, arm) for arm in LEARNED)
    return rows


def audit_costs(
    root,
    source,
    selection,
    training,
    exports,
    development_counts,
    confirmation_counts,
    diagnostic_counts,
    confirmed=True,
):
    raw = (root / "costs.jsonl").read_bytes()
    rows = [strict_json(line) for line in raw.splitlines()]
    roster = phase_roster(confirmed=confirmed)
    require(
        [(r["phase"], r["seed"], r.get("arm")) for r in rows] == roster,
        "Measured cost phase roster/order has missing, duplicate or undeclared windows",
    )
    prefix = raw[: selection["training_costs_prefix_bytes"]]
    require(
        len(prefix.splitlines()) == len(phase_roster(confirmed=False)),
        "Selection cost prefix includes confirmation or omits training work",
    )
    phase_totals, native_cpu, residuals = {}, 0.0, 0.0
    totals = dict.fromkeys(
        ("request_bytes", "response_bytes", "actual_kernel_calls", "actual_ndu_calls"),
        0,
    )
    model_costs = {
        "model_build_cpu_seconds_subset": 0.0,
        "planning_cpu_seconds_subset": 0.0,
    }
    for row in rows:
        phase, seed, arm, cost = row["phase"], row["seed"], row.get("arm"), row["cost"]
        cost_values(cost)
        phase_totals.setdefault(phase, dict.fromkeys(FIELDS, 0.0))
        for field in FIELDS:
            phase_totals[phase][field] += cost[field]
        expected_counts, native = None, row.get("native_process_cost")
        if phase == "training_development":
            receipt = training[seed, arm]
            require(
                cost == receipt["cost"] and native == receipt["native_process_cost"],
                "Training cost copies differ",
            )
            expected_counts = development_counts[seed, arm]
            for candidate in receipt["candidates"]:
                subset = candidate["fit_cost_subset"]
                cost_values(subset)
                require(
                    all(subset[k] <= cost[k] + 5e-6 for k in FIELDS),
                    "Fitting subset exceeds enclosing cost",
                )
                fit = candidate["fit"]
                if arm != "ridge_reference":
                    require(
                        all(
                            isinstance(fit[k], (int, float))
                            and np.isfinite(fit[k])
                            and 0 <= fit[k] <= subset[k] + 5e-6
                            for k in ("wall_seconds", "python_cpu_seconds")
                        ),
                        "Optimizer internal clock exceeds enclosing fitting window",
                    )
            require(
                all(
                    sum(c["fit_cost_subset"][k] for c in receipt["candidates"])
                    <= cost[k] + 5e-6
                    for k in FIELDS
                ),
                "Overlapping or double-counted fitting subsets",
            )
        elif phase == "native_feature_export":
            receipt = exports[seed]
            require(
                cost == receipt["cost"] and native == receipt["native_process_cost"],
                "Feature-export cost copies differ",
            )
            expected_counts = export_counts(root, receipt)
        elif phase == "confirmation_rollout":
            expected_counts = confirmation_counts[seed, arm]
        elif phase == "diagnostic_panel":
            expected_counts = diagnostic_counts[seed, arm]
        if native is not None:
            require(
                expected_counts is not None and arm != "finite_grid_dp",
                "Unexpected native cost in a setup/control phase",
            )
            counters, process_cpu, residual = native_work(
                native, cost, source, expected_counts
            )
            native_cpu += process_cpu
            residuals += residual
            for field in totals:
                totals[field] += counters[field]
        else:
            require(
                expected_counts is None or arm == "finite_grid_dp",
                "Native scientific work lacks a process receipt",
            )
            require(
                cost["completed_child_cpu_seconds"] <= 5e-6,
                "Unaccounted native child CPU outside native phase",
            )
        phases = {
            "training_setup": ("training", "development"),
            "confirmation_setup": ("test_id", "test_ood"),
            "diagnostic_setup": ("diagnostic",),
        }.get(phase, ())
        shared_cpu, shared_wall = 0.0, 0.0
        for context_phase in phases:
            for context in read(root, f"contexts/{seed}/{context_phase}.json")[
                "contexts"
            ]:
                for name in ("model_build_cost", "planning_cost"):
                    shared_cpu += context[name]["cpu_seconds"]
                    shared_wall += context[name]["wall_seconds"]
                    model_costs[name.replace("_cost", "_cpu_seconds_subset")] += (
                        context[name]["cpu_seconds"]
                    )
        require(
            shared_cpu <= cost["python_cpu_seconds"] + 5e-6
            and shared_wall <= cost["wall_seconds"] + 5e-6,
            "Shared boundary/DP solver costs exceed setup window",
        )
    total = {key: sum(p[key] for p in phase_totals.values()) for key in FIELDS}
    total["total_cpu_seconds"] = (
        total["python_cpu_seconds"] + total["completed_child_cpu_seconds"]
    )
    return {
        "record_count": len(rows),
        "phase_totals": phase_totals,
        "total": total,
        "native_process_counters": totals,
        "native_process_cpu_seconds_subset": native_cpu,
        "parent_minus_per_pid_cpu_seconds": residuals,
        **model_costs,
        "scope": "nonoverlapping scientific windows; exact child CPU and fitting/model/DP clocks are subsets, never added twice; compilation and independent audit excluded",
        "hardware_energy_measured": False,
        "cpu_clock_rounding_tolerance_seconds_per_phase": 5e-6,
    }
