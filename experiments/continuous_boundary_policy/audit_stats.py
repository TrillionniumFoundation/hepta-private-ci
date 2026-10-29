"""Independent aggregation, registered paired inference, and measured costs."""

import numpy as np
from scipy.stats import t as student_t

from .audit_integrity import ARMS, CONTROLS, LEARNED, SEEDS, strict_json
from .audit_math import require

COUNTERS = (
    "source_kernel_calls",
    "native_ndu_calls",
    "semantic_message_bytes",
    "wire_request_bytes",
    "wire_response_bytes",
)


def calibration(probabilities, labels):
    p, y = np.asarray(probabilities, dtype=float), np.asarray(labels, dtype=float)
    if not len(p):
        return {"observations": 0, "brier": None, "ece": None, "bins": []}
    bins, ece = [], 0.0
    indices = np.minimum((p * 10).astype(int), 9)
    for index in range(10):
        select = indices == index
        count = int(select.sum())
        predicted, actual = (
            (float(p[select].mean()), float(y[select].mean()))
            if count
            else (None, None)
        )
        if count:
            ece += count / len(p) * abs(predicted - actual)
        bins.append(
            {
                "lower": index / 10,
                "upper": (index + 1) / 10,
                "count": count,
                "mean_prediction": predicted,
                "event_rate": actual,
            }
        )
    return {
        "observations": len(p),
        "brier": float(np.mean((p - y) ** 2)),
        "ece": ece,
        "bins": bins,
    }


def summarize(records):
    metrics = (
        "gross_utility",
        "net_utility",
        "discounted_action_regret",
        "action_regret",
        "steps",
        "failures",
        "repairs",
        "stops",
    )
    result = {
        "episodes": len(records),
        **{f"mean_{key}": float(np.mean([r[key] for r in records])) for key in metrics},
    }
    briers = [row["brier"] for row in records if row["brier"] is not None]
    result["episode_equal_brier"] = float(np.mean(briers)) if briers else None
    result["episodes_with_risk_exposure"] = len(briers)
    result["calibration"] = calibration(
        [p for r in records for p in r["probabilities"]],
        [y for r in records for y in r["labels"]],
    )
    result["stability_failures"] = sum(row["stability_failure"] for row in records)
    result["counters"] = {name: sum(row[name] for row in records) for name in COUNTERS}
    return result


def paired_statistics(deltas, stability_failures=0):
    delta = np.asarray(deltas, dtype=float)
    require(
        delta.shape == (8,) and np.isfinite(delta).all(),
        "Primary inference must use eight independent seed differences",
    )
    mean, sem = float(delta.mean()), float(delta.std(ddof=1) / np.sqrt(8))
    critical = float(student_t.ppf(1 - 0.05 / (2 * 4), 7))
    interval = [mean - critical * sem, mean + critical * sem]
    generator = np.random.Generator(np.random.Philox(9973))
    boot = delta[generator.integers(0, 8, size=(20000, 8))].mean(axis=1)
    return {
        "seed_deltas": delta.tolist(),
        "mean_delta": mean,
        "standard_error": sem,
        "simultaneous_interval": interval,
        "individual_confidence": 0.9875,
        "familywise_confidence": 0.95,
        "family_size": 4,
        "df": 7,
        "descriptive_bootstrap95": np.quantile(boot, [0.025, 0.975]).tolist(),
        "minimum_effect": 0.005,
        "stability_failures": int(stability_failures),
        "benefit_gate_passed": bool(interval[0] > 0.005 and stability_failures == 0),
    }


def inspect_native_cost(native, phase_cost):
    """Read both original sparse and direct-score receipts without rewriting them.

    Parent cumulative RUSAGE_CHILDREN and per-PID wait4 expose microsecond CPU
    clocks. Their separately rounded user/system fields can differ slightly.
    The parent phase total is charged once; the per-PID value is a subset.
    """
    counters = native.get("counters", native)
    require(
        native["exit_code"] == 0 and counters["native_errors"] == 0,
        "Native host failed during measured phase",
    )
    cpu = native.get("completed_child_cpu_seconds", native.get("child_cpu_seconds"))
    require(
        isinstance(cpu, (int, float))
        and not isinstance(cpu, bool)
        and np.isfinite(cpu)
        and cpu >= 0,
        "Invalid exact child CPU receipt",
    )
    residual = phase_cost["completed_child_cpu_seconds"] - cpu
    require(
        np.isfinite(residual) and abs(residual) <= 5e-6,
        "Phase child CPU differs from per-PID measurement beyond clock rounding",
    )
    for name in (
        "request_bytes",
        "response_bytes",
        "actual_kernel_calls",
        "actual_ndu_calls",
    ):
        require(
            type(counters[name]) is int and counters[name] >= 0,
            "Invalid native process counter",
        )
    return counters, float(cpu), float(residual)


def audit_costs(root, training, raw_counts):
    rows = [
        strict_json(line) for line in (root / "costs.jsonl").read_bytes().splitlines()
    ]
    expected = {
        (phase, seed, None)
        for phase in ("training_setup", "confirmation_setup")
        for seed in SEEDS
    }
    expected |= {
        ("training_development", seed, arm) for seed in SEEDS for arm in LEARNED
    }
    expected |= {
        (phase, seed, arm)
        for phase in ("confirmation_rollout", "serialization")
        for seed in SEEDS
        for arm in ARMS
    }
    seen, phase_totals = set(), {}
    native_cpu, clock_residual = 0.0, 0.0
    wire = dict.fromkeys(
        ("request_bytes", "response_bytes", "actual_kernel_calls", "actual_ndu_calls"),
        0,
    )
    fields = ("python_cpu_seconds", "completed_child_cpu_seconds", "wall_seconds")
    for row in rows:
        key = row["phase"], row["seed"], row.get("arm")
        require(
            key in expected and key not in seen,
            "Missing/duplicate/undeclared cost phase",
        )
        seen.add(key)
        cost = row["cost"]
        require(
            all(
                isinstance(cost[name], (int, float))
                and np.isfinite(cost[name])
                and cost[name] >= 0
                for name in fields
            ),
            "Invalid nonnegative measured cost",
        )
        phase_totals.setdefault(row["phase"], dict.fromkeys(fields, 0.0))
        for name in fields:
            phase_totals[row["phase"]][name] += cost[name]
        native = row.get("native_process_cost")
        if row["phase"] == "training_development":
            receipt = training[row["seed"], row["arm"]]
            require(
                cost == receipt["cost"] and native == receipt["native_process_cost"],
                "Training cost ledger changed",
            )
        if native is not None:
            counters, process_cpu, residual = inspect_native_cost(native, cost)
            native_cpu += process_cpu
            clock_residual += residual
            for name in wire:
                wire[name] += counters[name]
            if row["arm"] != "native_sparse":
                require(
                    counters["actual_kernel_calls"] == 0,
                    "Continuous phase invoked sparse cells",
                )
            if row["phase"] == "confirmation_rollout":
                raw = raw_counts[row["seed"], row["arm"]]
                require(
                    counters["actual_kernel_calls"] == raw["source_kernel_calls"]
                    and counters["actual_ndu_calls"] == raw["native_ndu_calls"],
                    "Native measured call count differs from raw decisions",
                )
                require(
                    counters["request_bytes"] >= raw["wire_request_bytes"]
                    and counters["response_bytes"] >= raw["wire_response_bytes"],
                    "Native full wire accounting omits raw decision messages",
                )
        elif row["phase"] in {"confirmation_rollout", "training_development"}:
            require(
                row["arm"] in CONTROLS, "Learned phase lacks measured native process"
            )
    require(seen == expected, "Incomplete measured phase roster")
    total = {
        name: sum(phase[name] for phase in phase_totals.values()) for name in fields
    }
    total["total_cpu_seconds"] = (
        total["python_cpu_seconds"] + total["completed_child_cpu_seconds"]
    )
    return {
        "record_count": len(rows),
        "phase_totals": phase_totals,
        "total": total,
        "native_process_counters": wire,
        "native_process_cpu_seconds_subset": native_cpu,
        "parent_minus_per_pid_cpu_seconds": clock_residual,
        "cpu_clock_rounding_tolerance_seconds_per_phase": 5e-6,
        "raw_rows": rows,
        "scope": "nonoverlapping scientific windows; per-PID CPU is a subset, not added again; compiler, independent audit and engineering diagnostics excluded",
    }


def verify_context_counters(records, counts):
    totals = {
        "actual_kernel_calls": sum(
            s["source_kernel_calls"] for r in records for s in r["steps"]
        ),
        "actual_ndu_calls": sum(
            s["native_ndu_calls"] for r in records for s in r["steps"]
        ),
        "semantic_message_bytes": sum(
            s["semantic_message_bytes"] for r in records for s in r["steps"]
        ),
        "wire_request_bytes": sum(
            s["wire_request_bytes"] for r in records for s in r["steps"]
        ),
        "wire_response_bytes": sum(
            s["wire_response_bytes"] for r in records for s in r["steps"]
        ),
        "model_state_updates": sum(
            s["native_ndu_calls"] for r in records for s in r["steps"]
        ),
        "physical_environment_windows": sum(len(r["steps"]) for r in records),
    }
    require(counts == totals, "Persisted rollout counts disagree with raw decisions")
    for elapsed in range(max(len(record["steps"]) for record in records)):
        active = [
            record["steps"][elapsed]
            for record in records
            if len(record["steps"]) > elapsed
        ]
        for field in ("wire_request_bytes", "wire_response_bytes"):
            values = [step[field] for step in active]
            count, amount = len(values), sum(values)
            expected = [
                amount // count + int(index < amount % count) for index in range(count)
            ]
            require(values == expected, "Batch wire bytes were not allocated exactly")
