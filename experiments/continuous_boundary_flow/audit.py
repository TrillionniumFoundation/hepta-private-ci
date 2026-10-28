"""Independent recomputation of continuous-boundary experiment evidence.

No training or report-summary functions are imported. The trusted manifest binds
raw records and checkpoints; these hashes are not a signature or proof against an
adversary replacing the entire evidence bundle.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.stats import t as student_t
from scipy.special import log_ndtr, ndtr


class AuditError(ValueError):
    """The evidence bundle violates its declared protocol or internal contract."""


def require(condition, message):
    if not condition:
        raise AuditError(message)


def finite(value, name):
    require(
        isinstance(value, (int, float)) and not isinstance(value, bool),
        f"{name}: expected a real number",
    )
    require(math.isfinite(value), f"{name}: nonfinite number")
    return float(value)


def nonnegative(value, name):
    value = finite(value, name)
    require(value >= 0, f"{name}: negative value")
    return value


def digest_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    def reject_constant(value):
        raise AuditError(f"{path}: forbidden JSON constant {value}")

    try:
        return json.loads(
            Path(path).read_text(encoding="utf-8"), parse_constant=reject_constant
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditError(f"Cannot read {path}: {exc}") from exc


def paired_summary(seed_deltas, family_size=3, bootstrap_seed=731, draws=20000):
    """Seed-cluster inference; episodes/ticks are never treated as replicates."""
    values = np.asarray(seed_deltas, dtype=float)
    require(
        values.ndim == 1 and len(values) >= 2, "At least two seed differences required"
    )
    require(np.isfinite(values).all(), "Nonfinite seed difference")
    require(isinstance(family_size, int) and family_size >= 1, "Invalid family size")
    n = len(values)
    mean = float(values.mean())
    se = float(values.std(ddof=1) / np.sqrt(n))
    critical = float(student_t.ppf(1 - 0.05 / (2 * family_size), n - 1))
    interval = [mean - critical * se, mean + critical * se]
    rng = np.random.default_rng(bootstrap_seed)
    bootstrap = values[rng.integers(0, n, size=(draws, n))].mean(axis=1)
    return {
        "n_independent_seeds": n,
        "mean_difference": mean,
        "seed_differences": values.tolist(),
        "standard_error": se,
        "simultaneous_interval": interval,
        "individual_confidence": 1 - 0.05 / family_size,
        "familywise_confidence": 0.95,
        "method": "paired seed Student t, Bonferroni two-sided",
        "bootstrap_95_descriptive": np.quantile(bootstrap, [0.025, 0.975]).tolist(),
        "bootstrap_seed": bootstrap_seed,
        "bootstrap_draws": draws,
        "positive_utility_established": bool(interval[0] > 0),
    }


def calibration_scores(probabilities, labels, n_bins=10):
    """Brier and fixed-bin ECE; callers must supply the declared event/horizon."""
    p, y = np.asarray(probabilities, dtype=float), np.asarray(labels, dtype=float)
    require(p.ndim == y.ndim == 1 and p.size == y.size, "Calibration shape mismatch")
    require(
        np.isfinite(p).all() and np.isfinite(y).all(), "Nonfinite calibration values"
    )
    require(np.all((p >= 0) & (p <= 1)), "Risk probability outside [0,1]")
    require(np.all((y == 0) | (y == 1)), "Calibration labels must be binary")
    if not p.size:
        return {"count": 0, "brier": None, "ece": None, "bins": []}
    indices = np.minimum((p * n_bins).astype(int), n_bins - 1)
    bins, ece = [], 0.0
    for index in range(n_bins):
        mask = indices == index
        if not np.any(mask):
            continue
        pred, observed = float(p[mask].mean()), float(y[mask].mean())
        count = int(mask.sum())
        ece += count / p.size * abs(pred - observed)
        bins.append(
            {
                "lower": index / n_bins,
                "upper": (index + 1) / n_bins,
                "count": count,
                "mean_probability": pred,
                "event_frequency": observed,
            }
        )
    return {
        "count": int(p.size),
        "brier": float(np.mean((p - y) ** 2)),
        "ece": float(ece),
        "bins": bins,
    }


def window_utility(spec, elapsed, action, active_time, failed, tau_hit):
    """Discounted realized maintenance utility from physical event primitives."""
    require(action in ("wait", "repair", "stop"), "Unknown task action")
    require(isinstance(elapsed, int) and elapsed >= 0, "Invalid elapsed window")
    q = nonnegative(spec["discount"], "discount")
    dt = nonnegative(spec["dt"], "dt")
    require(dt > 0, "dt must be positive")
    active = nonnegative(active_time, "active_time")
    require(active <= dt + 1e-10, "Active time exceeds decision window")
    require(isinstance(failed, bool), "failed must be Boolean")
    if action == "stop":
        require(
            active == 0 and not failed and tau_hit is None,
            "Stopped window has physical events",
        )
        return {
            "gross_utility": 0.0,
            "production": 0.0,
            "failure_cost": 0.0,
            "maintenance_cost": 0.0,
        }
    if failed:
        tau = nonnegative(tau_hit, "tau_hit")
        require(
            tau <= dt + 1e-10 and abs(tau - active) <= 1e-9,
            "Failure time and active duration disagree",
        )
    else:
        require(
            tau_hit is None and abs(active - dt) <= 1e-9,
            "Surviving window must produce for its full duration",
        )
        tau = dt
    occupation = -math.expm1(-q * active) / q if q else active
    outer = math.exp(-q * elapsed * dt)
    production = (
        outer * nonnegative(spec["production_rate"], "production_rate") * occupation
    )
    loss = (
        outer
        * nonnegative(spec["failure_cost"], "failure_cost")
        * math.exp(-q * tau)
        * failed
    )
    maintenance = (
        outer
        * nonnegative(spec["maintenance_cost"], "maintenance_cost")
        * (action == "repair")
    )
    return {
        "gross_utility": production - loss - maintenance,
        "production": production,
        "failure_cost": loss,
        "maintenance_cost": maintenance,
    }


COUNTERS = (
    "source_kernel_calls",
    "native_ndu_calls",
    "semantic_message_bytes",
    "wire_request_bytes",
    "wire_response_bytes",
    "model_state_updates",
    "solver_evals",
)
REFERENCE_ARMS = {"dp", "always_keep", "always_repair", "always_stop"}


def contained_path(root, relative):
    require(
        isinstance(relative, str) and relative,
        "Artifact path must be a nonempty string",
    )
    path = (root / relative).resolve()
    require(
        path.is_relative_to(root.resolve()),
        f"Artifact escapes run directory: {relative}",
    )
    require(path.is_file(), f"Missing artifact: {relative}")
    return path


def checked_artifact(root, entry):
    require(
        isinstance(entry, dict) and "path" in entry and "sha256" in entry,
        "Artifact entry lacks path or digest",
    )
    path = contained_path(root, entry["path"])
    require(digest_file(path) == entry["sha256"], f"SHA-256 mismatch: {entry['path']}")
    return path


def strict_json(text, location):
    def reject(value):
        raise AuditError(f"{location}: forbidden JSON constant {value}")

    try:
        obj = json.loads(text, parse_constant=reject)
    except json.JSONDecodeError as exc:
        raise AuditError(f"Malformed JSON at {location}: {exc}") from exc
    require(isinstance(obj, dict), f"Expected object at {location}")
    return obj


def integer(value, name, upper=None):
    require(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0,
        f"{name}: expected nonnegative integer",
    )
    require(upper is None or value <= upper, f"{name}: exceeds upper bound")
    return value


def independent_hit_probability(x, mu, sigma, horizon):
    """Reflection formula, independently implemented without task/kernel imports."""
    require(x > 0 and sigma > 0 and horizon > 0, "Invalid first-passage inputs")
    scale = sigma * math.sqrt(horizon)
    reflected = math.exp(
        min(0.0, -2 * mu * x / sigma**2 + float(log_ndtr((-x + mu * horizon) / scale)))
    )
    return min(1.0, max(0.0, float(ndtr((-x - mu * horizon) / scale)) + reflected))


def q24_product(a, b):
    value = a * b
    whole, remainder = divmod(abs(value), 2**24)
    rounded = whole + int(
        2 * remainder > 2**24 or (2 * remainder == 2**24 and whole % 2)
    )
    return -rounded if value < 0 else rounded


def audit_episode(record, message_price, profile=None):
    required = {
        "arm",
        "train_seed",
        "split",
        "episode_id",
        "eval_seed",
        "checkpoint_sha256",
        "spec",
        "steps",
        "reported_utility",
        "reported_net_utility",
        "stability_failure",
    }
    require(
        required <= record.keys(), f"Episode lacks {sorted(required - record.keys())}"
    )
    spec, steps = record["spec"], record["steps"]
    require(isinstance(spec, dict), "TaskSpec must be an object")
    horizon = integer(spec.get("horizon"), "horizon")
    require(
        horizon > 0 and isinstance(steps, list) and 0 < len(steps) <= horizon,
        "Episode step count violates horizon",
    )
    totals = dict.fromkeys(
        ("gross_utility", "production", "failure_cost", "maintenance_cost"), 0.0
    )
    counters = dict.fromkeys(COUNTERS, 0)
    probabilities, labels = [], []
    failures = repairs = stops = native_scores = native_activations = (
        physics_verified
    ) = 0
    previous_state = previous_native = None
    require(
        isinstance(record["stability_failure"], bool),
        "stability_failure must be Boolean",
    )
    for elapsed, step in enumerate(steps):
        require(isinstance(step, dict), "Step must be an object")
        fields = {
            "elapsed",
            "action",
            "state_idx",
            "x",
            "active_time",
            "failed",
            "tau_hit",
            "predicted_risk",
            *COUNTERS,
        }
        require(fields <= step.keys(), f"Step lacks {sorted(fields - step.keys())}")
        require(
            step["elapsed"] == elapsed, "Steps are missing, duplicated, or out of order"
        )
        integer(step["state_idx"], "state_idx")
        require(
            previous_state is None or step["state_idx"] == previous_state,
            "Physical state chain was broken",
        )
        previous_state = step.get("next_state_idx")
        if previous_state is not None:
            require(
                previous_state == -1
                if step["action"] == "stop"
                else isinstance(previous_state, int) and previous_state >= 0,
                "Invalid next state for declared action",
            )
        native_before, native_after = (
            step.get("native_checkpoint_before"),
            step.get("native_checkpoint_after"),
        )
        if native_before is not None or native_after is not None:
            require(
                all(
                    isinstance(v, str)
                    and len(v) == 64
                    and all(c in "0123456789abcdef" for c in v)
                    for v in (native_before, native_after)
                ),
                "Invalid native checkpoint digest",
            )
            require(
                previous_native is None or native_before == previous_native,
                "Native checkpoint chain was broken",
            )
            previous_native = native_after
        require(
            finite(step["x"], "x") > 0, "Pre-action physical state must exceed zero"
        )
        action = step["action"]
        ledger = window_utility(
            spec, elapsed, action, step["active_time"], step["failed"], step["tau_hit"]
        )
        for key, value in ledger.items():
            totals[key] += value
        for key in COUNTERS:
            counters[key] += integer(
                step[key], key, 1 if key.endswith("calls") else None
            )
        require(
            step["semantic_message_bytes"] % 8 == 0,
            "Semantic Q24 payload must use i64-sized values",
        )
        if record["arm"] not in REFERENCE_ARMS:
            require(
                step["source_kernel_calls"] == step["native_ndu_calls"] == 1,
                "Learning arm bypassed actual source kernel or native NDU action evaluation",
            )
        if action == "stop":
            require(elapsed == len(steps) - 1, "Actions occurred after absorbing stop")
            require(
                step["predicted_risk"] is None,
                "Stopped window is not a calibration observation",
            )
            stops += 1
        else:
            probability = finite(step["predicted_risk"], "predicted_risk")
            require(0 <= probability <= 1, "Risk prediction outside [0,1]")
            if step.get("x_after_action") is not None:
                x_after = finite(step["x_after_action"], "x_after_action")
                mu, sigma = finite(spec["mu"], "mu"), finite(spec["sigma"], "sigma")
                expected_risk = independent_hit_probability(
                    x_after, mu, sigma, spec["dt"]
                )
                physics_verified += 1
                require(
                    abs(probability - expected_risk) <= 2e-8,
                    "Risk disagrees with independent first-passage formula",
                )
                if "uniforms" in step:
                    u = step["uniforms"]
                    require(
                        isinstance(u, list)
                        and len(u) == 6
                        and all(0 <= finite(v, "uniform") < 1 for v in u),
                        "Invalid fixed innovation slots",
                    )
                    require(
                        step["failed"] == (u[2] < probability),
                        "Failure label disagrees with physical innovation",
                    )
                    if step["failed"]:
                        conditional = independent_hit_probability(
                            x_after, mu, sigma, step["tau_hit"]
                        )
                        require(
                            abs(conditional - u[3] * probability) <= 2e-8,
                            "Conditional first-hit time disagrees with innovation",
                        )
            probabilities.append(probability)
            labels.append(int(step["failed"]))
        failures += int(step["failed"])
        repairs += int(action == "repair")
        for field, width in (("activation_q24", 20), ("scores_q24", 3)):
            values = step.get(field)
            if values is not None:
                require(
                    isinstance(values, list)
                    and len(values) == width
                    and all(
                        isinstance(v, int)
                        and not isinstance(v, bool)
                        and -(2**63) <= v < 2**63
                        for v in values
                    ),
                    f"Malformed {field}",
                )
                native_scores += int(field == "scores_q24")
                native_activations += int(field == "activation_q24")
                if field == "activation_q24":
                    require(
                        all(0 <= v <= 8 * 2**24 for v in values),
                        "Native activation outside sparse bounds",
                    )
                if field == "scores_q24" and step["native_ndu_calls"]:
                    require(values[2] == 0, "Native stop value must be fixed at zero")
                    selected = max(range(3), key=lambda i: (values[i], i))
                    require(
                        action == ("wait", "repair", "stop")[selected],
                        "Native scores disagree with action under registered tie rule and risk ceiling Q",
                    )
        if profile is not None:
            activation, scores = step.get("activation_q24"), step.get("scores_q24")
            require(
                activation is not None and scores is not None,
                "Checkpoint head requires native activation and score evidence",
            )
            expected = [
                bias + sum(q24_product(w, a) for w, a in zip(row, activation))
                for row, bias in zip(
                    profile["head_weights_q24"], profile["head_bias_q24"]
                )
            ]
            require(
                scores == expected,
                "Persisted native head and activation disagree with recorded scores",
            )
        raw = step.get("raw_features")
        if raw is not None:
            require(
                isinstance(raw, dict) and set(raw) == {"raw_q24", "continuous"},
                "Malformed typed raw features",
            )
            continuous = raw["continuous"]
            require(
                isinstance(continuous, dict)
                and set(continuous) == {"margin_q24", "risk_q24", "flow_q24"},
                "Malformed continuous readout",
            )
            require(
                isinstance(raw["raw_q24"], list) and len(raw["raw_q24"]) == 17,
                "Expected 17 public raw features",
            )
            numbers = raw["raw_q24"] + list(continuous.values())
            require(
                all(
                    isinstance(v, int)
                    and not isinstance(v, bool)
                    and -8 * 2**24 <= v <= 8 * 2**24
                    for v in numbers
                ),
                "Raw Q24 feature outside native bounds",
            )
            require(0 <= continuous["risk_q24"] <= 2**24, "Native risk outside [0,Q]")
            require(
                step["semantic_message_bytes"] == 8 * len(numbers),
                "Semantic payload byte ledger mismatch",
            )
    require(
        stops == 1 or len(steps) == horizon,
        "Truncated episode without an absorbing stop",
    )
    totals["net_utility"] = (
        totals["gross_utility"] - message_price * counters["semantic_message_bytes"]
    )
    for reported, actual in (
        ("reported_utility", "gross_utility"),
        ("reported_net_utility", "net_utility"),
    ):
        observed = finite(record[reported], reported)
        require(
            math.isclose(observed, totals[actual], rel_tol=2e-9, abs_tol=2e-9),
            f"{reported} disagrees with independently recomputed primitive ledger",
        )
    calibration = calibration_scores(probabilities, labels)
    return {
        **totals,
        **counters,
        "failures": failures,
        "repairs": repairs,
        "stops": stops,
        "steps": len(steps),
        "brier": calibration["brier"],
        "probabilities": probabilities,
        "labels": labels,
        "stability_failure": int(record["stability_failure"]),
        "native_score_steps": native_scores,
        "native_activation_steps": native_activations,
        "physical_first_hit_steps_verified": physics_verified,
    }


def audit_costs(root, manifest):
    path = contained_path(root, manifest.get("costs_path", "costs.jsonl"))
    bound = "costs_sha256" in manifest
    if bound:
        require(
            digest_file(path) == manifest["costs_sha256"],
            "SHA-256 mismatch: costs.jsonl",
        )
    rows, phases = [], {}
    numeric_fields = (
        "wall_seconds",
        "python_cpu_seconds",
        "completed_child_cpu_seconds",
        "actual_kernel_calls",
        "actual_ndu_calls",
        "wire_request_bytes",
        "wire_response_bytes",
        "fits",
    )
    with path.open(encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            row = strict_json(line, f"costs.jsonl:{lineno}")
            require(
                isinstance(row.get("phase"), str) and row["phase"],
                "Cost row lacks phase",
            )
            require(
                isinstance(row.get("cost_scope"), str) and row["cost_scope"],
                "Cost row lacks scope",
            )
            phase = phases.setdefault(row["phase"], {})
            for field in numeric_fields:
                if field in row:
                    phase[field] = phase.get(field, 0.0) + nonnegative(
                        row[field], field
                    )
            rows.append(row)
    require(rows, "No measured phase cost records")
    return {
        "hash_bound": bound,
        "phase_totals": phases,
        "records": rows,
        "interpretation": "Measured phase costs; wall and CPU are distinct, not added to utility or converted to energy.",
    }


