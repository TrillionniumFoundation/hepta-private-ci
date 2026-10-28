"""Independent ledger arithmetic and paired statistics, without runtime imports."""

import argparse
from collections import defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path

import numpy as np

ARMS = ("ordinary_first_event", "endogenous_renewal", "learned_threshold7",
        "fixed_shared6", "fixed_cross7", "always_wait", "always_repair", "stop")
SEEDS = (1103, 1151, 1201, 1213, 1223, 1231, 1237, 1249)


def close(actual, expected, label, tolerance=2e-11):
    if not math.isfinite(float(actual)) or abs(actual - expected) > tolerance:
        raise ValueError(f"{label}: {actual!r} differs from {expected!r}")


def audit_episode(episode):
    """Reconstruct scored time/cost solely from event times and public actions."""
    scenario, rows = episode["scenario"], episode["records"]
    if not 1 <= len(rows) <= 4:
        raise ValueError("Every episode must terminate within four decisions")
    total, clock, pending, failures, random_counter = 0.0, 0.0, 0.0, 0, 0
    level = scenario["level"]
    active_total, repairs, paid, terminal = 0.0, 0, 0.0, False
    for index, row in enumerate(rows):
        obs, outcome, action = row["observation"], row["outcome"], row["action"]
        if terminal or row["scenario_id"] != scenario["identity"]:
            raise ValueError("Action after termination or mixed scenario identities")
        if obs["inputs"] != scenario["inputs"] or obs["decision_index"] != index:
            raise ValueError("Changed public inputs or decision order")
        for key, expected in (("repair_cost", scenario["repair_cost"]), ("level", level),
                              ("time", clock), ("refractory_remaining", pending),
                              ("remaining_duration", 2.0 - 0.5 * index)):
            close(obs[key], expected, "observation " + key)
        legal = {"wait", "stop"} if pending > 0 else {"wait", "repair", "stop"}
        if set(obs["legal_actions"]) != legal or action not in legal:
            raise ValueError("Illegal action or altered action availability")
        decision = row.get("decision")
        if decision is not None and decision["action"].lower() != action:
            raise ValueError("Scored action differs from selected action")
        elapsed = 0.0 if action == "stop" else 0.5
        end = clock + elapsed
        close(outcome["elapsed_duration"], elapsed, "elapsed duration")
        close(outcome["time"], end, "outcome time")
        events = outcome["events"]
        if type(outcome["failure_count"]) is not int or outcome["failure_count"] != len(events):
            raise ValueError("Failure count is not the retained event count")
        if len(events) > 128 or (action == "stop" and events):
            raise ValueError("Event budget or stopped-clock violation")
        initial_pending = 0.06 if action == "repair" else pending
        lost, earliest = min(initial_pending, elapsed), clock + initial_pending
        for event in events:
            failures += 1
            if event["kind"] != "first_passage" or event["ordinal"] != failures:
                raise ValueError("Event kind/ordinal mismatch")
            time = float(event["time"])
            if not math.isfinite(time) or not earliest - 2e-11 <= time <= end + 2e-11:
                raise ValueError("Events violate interval or refractory separation")
            lost += min(0.06, max(0.0, end - time))
            earliest = time + 0.06
        active = elapsed - lost
        close(outcome["active_duration"], active, "independent active-time reconstruction")
        if active < -2e-11:
            raise ValueError("Negative active time")
        next_pending = (max(0.0, events[-1]["time"] + 0.06 - end) if events
                        else max(0.0, initial_pending - elapsed))
        close(outcome["refractory_remaining"], next_pending, "refractory carry")
        if next_pending > 2e-11:
            close(outcome["level"], 1.02, "reset level during refractory")
        if action == "stop":
            close(outcome["level"], level, "stopped state")
        if not math.isfinite(float(outcome["level"])) or outcome["level"] < 0.12:
            raise ValueError("Invalid live physical level")
        interventions = [{"time": clock, "kind": "repair"}] if action == "repair" else []
        if row["interventions"] != interventions:
            raise ValueError("Intervention ledger mismatch")
        charge = scenario["repair_cost"] if action == "repair" else 0.0
        running, loss = 0.6 * active, 0.5 * len(events)
        reward = running - loss - charge
        total += reward
        terminal = action == "stop" or index == 3
        for key, expected in (("running_reward", running), ("failure_cost", loss),
                              ("action_cost", charge), ("reward", reward), ("cumulative_reward", total)):
            close(row[key], expected, key)
        if type(row["done"]) is not bool or row["done"] != terminal:
            raise ValueError("Termination receipt mismatch")
        counter = outcome["random_counter"]
        if type(counter) is not int or counter < random_counter:
            raise ValueError("Random stream cursor regressed")
        if action == "stop" and counter != random_counter:
            raise ValueError("Stopped path consumed randomness")
        clock, level, pending, random_counter = end, outcome["level"], next_pending, counter
        active_total += active
        repairs += int(action == "repair")
        paid += charge
    if not terminal:
        raise ValueError("Incomplete episode")
    close(episode["total_reward"], total, "episode score")
    values = (rows[0].get("decision") or {}).get("values")
    forecast = None if not values else values["actions"][rows[0]["action"].upper()]["value"]
    return {"total_reward": total, "failures": failures, "repairs": repairs,
            "paid_repair_cost": paid, "active_time": active_total, "elapsed": clock,
            "stopped": rows[-1]["action"] == "stop", "decisions": len(rows),
            "initial_plan_value": forecast,
            "realized_minus_initial_plan": None if forecast is None else total - forecast}


def bootstrap_comparison(delta, rng, replicates=4000, family_size=3):
    """Resample model seeds, then paired complete episodes within each seed."""
    values = np.asarray(delta, dtype=np.float64)
    if values.shape != (8, 256) or not np.isfinite(values).all():
        raise ValueError("Registered primary cohort must be 8 seeds by 256 episodes")
    means = np.empty(replicates)
    for i in range(replicates):
        selected = rng.integers(0, values.shape[0], values.shape[0])
        indices = rng.integers(0, values.shape[1], (values.shape[0], values.shape[1]))
        means[i] = values[selected[:, None], indices].mean()
    tail = 0.05 / (2 * family_size)
    interval = np.quantile(means, [tail, 1 - tail])
    seed_means = values.mean(axis=1)
    return {"mean_gain": float(values.mean()), "per_seed_mean_gain": seed_means.tolist(),
            "empirical_family_adjusted_interval": interval.tolist(),
            "individual_interval_level": 1 - 2 * tail, "family_size": family_size,
            "lower_bound_threshold": 0.005, "all_seed_means_positive": bool(np.all(seed_means > 0)),
            "pass": bool(interval[0] > 0.005 and np.all(seed_means > 0)),
            "replicates": replicates, "population_guarantee": False}


def audit_run(root, phase="confirmation"):
    root = Path(root)
    expected_count = 256 if phase == "confirmation" else 128
    cohort, scenarios_seen, input_files = {}, {}, []
    aggregate = defaultdict(list)
    for path in sorted(root.rglob("*.jsonl.gz")):
        used = False
        with gzip.open(path, "rt") as stream:
            for line in stream:
                episode = json.loads(line)
                if episode.get("phase") != phase:
                    continue
                used = True
                arm, seed = episode["arm"], episode["seed"]
                if arm not in ARMS or seed not in SEEDS:
                    raise ValueError("Unregistered arm or model seed")
                scenario = episode["scenario"]
                key = (seed, scenario["identity"])
                canonical = json.dumps(scenario, sort_keys=True, separators=(",", ":"))
                if key in scenarios_seen and scenarios_seen[key] != canonical:
                    raise ValueError("Paired arms received different scenarios")
                scenarios_seen[key] = canonical
                record_key = (seed, arm, scenario["identity"])
                if record_key in cohort:
                    raise ValueError("Duplicate evaluation episode")
                checked = audit_episode(episode)
                cohort[record_key] = checked["total_reward"]
                aggregate[arm].append(checked)
        if used:
            input_files.append({"path": str(path.relative_to(root)), "bytes": path.stat().st_size,
                                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    matrices = {arm: [] for arm in ARMS}
    for seed in SEEDS:
        ids = sorted(k[1] for k in scenarios_seen if k[0] == seed)
        if len(ids) != expected_count:
            raise ValueError(f"Wrong scenario count for seed {seed}: {len(ids)}")
        for arm in ARMS:
            if sum(1 for key in cohort if key[:2] == (seed, arm)) != expected_count:
                raise ValueError(f"Incomplete cohort for {seed}/{arm}")
            matrices[arm].append([cohort[(seed, arm, identity)] for identity in ids])
    summaries = {}
    for arm in ARMS:
        records = aggregate[arm]
        summary = {"episodes": len(records)}
        for key in records[0]:
            nonnull = [row[key] for row in records if row[key] is not None]
            summary["mean_" + key] = None if not nonnull else float(np.mean(nonnull))
        summary["per_seed_mean_reward"] = np.mean(matrices[arm], axis=1).tolist()
        summaries[arm] = summary
    comparisons = {}
    if phase == "confirmation":
        rng = np.random.Generator(np.random.PCG64(2026102807))
        for baseline in ("ordinary_first_event", "fixed_cross7", "learned_threshold7"):
            differences = np.asarray(matrices["endogenous_renewal"]) - np.asarray(matrices[baseline])
            comparisons["endogenous_renewal-minus-" + baseline] = bootstrap_comparison(differences, rng)
    return {"schema": "HeptaFirstPassageIndependentAuditV2", "phase": phase,
            "ledger_pass": True, "episodes": len(cohort), "seeds": list(SEEDS),
            "source": "independent ledger arithmetic, no simulator/policy/kernel imports",
            "inputs": input_files, "arms": summaries, "primary_comparisons": comparisons,
            "statistics_scope": "empirical two-stage paired bootstrap; Bonferroni two-sided family alpha .05 across three comparisons",
            "plan_value_scope": "WAIT_AFTER_CURRENT forecast versus actual replanning outcome; not same-policy calibration"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--phase", choices=("confirmation", "stress_drift", "stress_diffusion"), default="confirmation")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit_run(args.root, args.phase)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"output": str(args.output), "episodes": result["episodes"], "ledger_pass": True}))


if __name__ == "__main__":
    main()
