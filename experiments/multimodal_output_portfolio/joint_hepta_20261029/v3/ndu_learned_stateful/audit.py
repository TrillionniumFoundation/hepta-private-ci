"""Post-freeze read-only evidence audit; independent raw-row trajectory and DP sums."""
import hashlib
import json
from functools import lru_cache
from pathlib import Path
import subprocess
import sys
import numpy as np
from .model import Kernel, Task, Policy

ROOT = Path(__file__).parent


def raw_events(table, z, a, cap):
    events = {}
    for y_index, y in enumerate((-1, 0, 1)):
        for d_index, duration in enumerate((1, 3)):
            for nz in (0, 1):
                key = (y, duration, nz) if duration <= cap else (-2, cap, z)
                index = y_index * 4 + d_index * 2 + nz
                events[key] = events.get(key, np.zeros(2)) + table[:, z, a, index]
    return events


def independent_optimum(table, task):
    @lru_cache(None)
    def recurse(w0, w1, z, remaining, steps):
        weights, mass = np.array([w0, w1]), w0 + w1
        best = (.55 + .45 * z) * max(w0, w1)
        if min(remaining, steps) <= 0:
            return best
        for a in (0, 1):
            for cap in range(1, remaining + 1):
                value = -task.fee * mass
                for (_, duration, nz), probabilities in raw_events(table, z, a, cap).items():
                    after = weights * probabilities
                    value += recurse(*after, nz, remaining - duration, steps - 1) - task.time_price * duration * sum(after)
                best = max(best, value)
        return best
    return recurse(.5, .5, 0, task.deadline, task.max_steps)


def independent_policy_value(law, fit, policy, task, dot_filter=False):
    def recurse(weights, belief, z, remaining, steps):
        action, argument = policy(belief, z, remaining, steps)
        if action == -1:
            return (.55 + .45 * z) * weights[argument]
        result = -task.fee * sum(weights)
        observed_fit = raw_events(fit, z, action, argument)
        for event, probabilities in raw_events(law, z, action, argument).items():
            after = weights * probabilities
            likelihood = observed_fit[event]
            if policy.mode == "no_duration":
                likelihood = sum(v for e, v in observed_fit.items() if (e[0], e[2]) == (event[0], event[2]))
            p0, p1 = map(float, likelihood)
            denominator = np.dot([1 - belief, belief], likelihood) if dot_filter else (1 - belief) * p0 + belief * p1
            next_b = belief * p1 / denominator
            result += recurse(after, next_b, event[2], remaining - event[1], steps - 1) - task.time_price * event[1] * sum(after)
        return result
    return recurse(np.array([.5, .5]), .5, 0, task.deadline, task.max_steps)


def main():
    path = ROOT / "evidence/registered_v1"
    result = json.loads((path / "results.json").read_text())
    protocol = json.loads((path / "protocol.json").read_text())
    manifest = json.loads((path / "manifest.json").read_text())["sha256"]
    assert all(hashlib.sha256((path / name).read_bytes()).hexdigest() == sha for name, sha in manifest.items())
    assert all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha for name, sha in result["source_sha256"].items())
    utility = np.load(path / "paired_utilities.npz")["utilities"]
    assert utility.shape == (144, 6, 4096)
    laws = {w["name"]: np.array(p) for w, p in zip(protocol["worlds"], result["world_kernels_diagnostic"])}
    fitted = {(b["world"], b["seed"], b["n_per_row"]): np.array(b["estimated_kernel"]) for b in result["learning"]}
    optimum_error = policy_error = mean_error = ledger_error = arithmetic_sensitivity = 0.
    negative_stop = negative_voi = tv_failures = 0
    for i, case in enumerate(result["cases"]):
        law, fit = laws[case["world"]], fitted[case["world"], case["seed"], case["n_per_row"]]
        task = Task(case["deadline"], case["fee"])
        for j, row in enumerate(case["policies"]):
            planning = law if row["policy"] == "known_oracle" else fit
            policy = Policy(Kernel(planning), task, row["policy"])
            checked = independent_policy_value(law, planning, policy, task)
            policy_error = max(policy_error, abs(checked - row["exact_true"]["utility"]))
            alternative = independent_policy_value(law, planning, policy, task, True)
            arithmetic_sensitivity = max(arithmetic_sensitivity, abs(checked - alternative))
            mean_error = max(mean_error, abs(float(utility[i, j].mean()) - row["confirmation_mean"]["utility"]))
            v = row["exact_true"]
            ledger_error = max(ledger_error, abs(v["utility"] - v["quality"] + v["fees"] + task.time_price * v["simulated_clock"]))
            if row["policy"] == "plugin_dp":
                optimum_error = max(optimum_error, abs(independent_optimum(fit, task) - row["exact_fitted"]["utility"]))
            if row["policy"] == "known_oracle":
                optimum_error = max(optimum_error, abs(independent_optimum(law, task) - row["exact_true"]["utility"]))
        negative_stop += case["contrasts"][0]["exact_gap"] < -1e-10
        negative_voi += case["contrasts"][1]["exact_gap"] < -1e-10
    tv_failures = sum(not b["bound_event_holds"] for b in result["learning"])
    tests = subprocess.run([sys.executable, "-m", "unittest", "experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_learned_stateful.test_model", "-q"], capture_output=True, text=True)
    print({"optimum_error": optimum_error, "policy_error": policy_error, "mean_error": mean_error, "ledger_error": ledger_error, "test_returncode": tests.returncode}, flush=True)
    assert max(optimum_error, policy_error, mean_error, ledger_error) < 1e-10 and tests.returncode == 0
    receipt = {"status": "passed", "audit_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "results_sha256": hashlib.sha256((path / "results.json").read_bytes()).hexdigest(),
               "frozen_sources_and_manifest_match": True, "cases": 144, "paired_utility_shape": list(utility.shape),
               "independent_optimum_max_error": optimum_error, "independent_policy_max_error": policy_error,
               "confirmation_mean_max_error": mean_error, "ledger_max_error": ledger_error,
               "observed_tv_bound_failures": tv_failures, "negative_vs_stop": int(negative_stop), "negative_vs_myopic": int(negative_voi),
               "tests_returncode": tests.returncode, "tests_output": tests.stderr,
               "posterior_arithmetic_sensitivity": {"alternate_numpy_dot_true_value_max_difference": arithmetic_sensitivity, "cause": "Changing floating-point posterior arithmetic can change a terminal decision at a fitted tie; accepted policy uses frozen scalar arithmetic", "frozen_experiment_changed": False},
               "scope": "Internal independent numerical implementation and hash audit; not external peer review or real-LLM validation"}
    (ROOT / "evidence/validation.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
