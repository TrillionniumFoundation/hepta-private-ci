"""Development checks; never uses train, selection, or confirmation namespaces."""

import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .model import Model, PROTOCOL, RESET, RUN, STOP, rollout, tape


def run():
    started = time.process_time()
    model = Model()
    maximum_residual = 0.
    dominance_checks = 0
    for kernel in model.kernels:
        for dt, transition in model.transitions.items():
            policy, values = model.dp(kernel, dt)
            for remaining in range(1, model.horizon + 1):
                # Independent scalar finite-MDP recurrence, including the
                # intervened state before both reward accrual and propagation.
                for state in range(40):
                    run_value = model.reward_rate[state] * dt + sum(
                        transition[state, after] * values[remaining - 1, after]
                        for after in range(40))
                    reset_value = -model.fees[kernel]
                    for reset_state in range(40):
                        mass = model.kernels[kernel][state, reset_state]
                        if mass:
                            reset_value += mass * (model.reward_rate[reset_state] * dt + sum(
                                transition[reset_state, after] * values[remaining - 1, after]
                                for after in range(40)))
                    expected = max(model.salvage[state], run_value, reset_value)
                    maximum_residual = max(maximum_residual,
                                           abs(expected - values[remaining, state]))
            for boundary in PROTOCOL["boundary_candidates"]:
                for stop in PROTOCOL["stop_candidates"]:
                    fixed = model.threshold(boundary, stop)
                    assert model.exact(policy, kernel, dt) + 1e-12 >= model.exact(fixed, kernel, dt)
                    dominance_checks += 1
    assert maximum_residual < 3e-14
    # A fresh development tape checks the actual intervention owner. Force a
    # reset at the first step; the sampled intervention state must be exactly
    # the registered recovery phase, not an observation-only REFRESH token.
    draws = tape(PROTOCOL["development_seed"], "development-owner", 64, "iid", model.horizon)
    forced = np.full((model.horizon + 1, 40), RUN, dtype=np.int8)
    forced[0] = STOP
    forced[-1] = RESET
    tables = {dt: forced for dt in model.transitions}
    owner_checks = []
    for kernel in model.kernels:
        first = rollout(model, draws, kernel, tables, capture=True)
        second = rollout(model, draws, kernel, tables, capture=True)
        first.pop("cpu_seconds")
        second.pop("cpu_seconds")
        assert first == second
        expected_phase = PROTOCOL["reset_recovery_states"][kernel.split(":")[1]]["phase"]
        reset_events = 0
        for row in first["trace"]:
            if row["step"] == 0:
                assert all(action == RESET for action in row["actions"])
                assert all(state // 4 == expected_phase for state in row["intervention_state"])
                reset_events += len(row["indices"])
        assert reset_events == 64 and sum(first["resets"]) == 64
        owner_checks.append(dict(kernel=kernel, resets=reset_events,
                                 trace_sha256=hashlib.sha256(json.dumps(
                                     first, sort_keys=True, separators=(",", ":")).encode()).hexdigest()))
    # Sampling comparison is descriptive; algebraic/scalar recurrence checks
    # establish the implemented expected-return semantics.
    sample = tape(PROTOCOL["development_seed"], "development-sampler", 4096, "iid", model.horizon)
    policy = {dt: model.dp("repair:early", dt)[0] for dt in model.transitions}
    executed = rollout(model, sample, "repair:early", policy)
    expected = float(np.mean([model.exact(policy[float(dt)], "repair:early", float(dt))
                              for dt in sample["dt"]]))
    return dict(schema="hcsn-r16-control-development-v1", passed=True,
                scalar_bellman_max_absolute_error=maximum_residual,
                exact_threshold_dominance_checks=dominance_checks,
                actual_reset_owner_checks=owner_checks,
                development_sample=dict(episodes=4096, expected_return=expected,
                                        sampled_return=executed["mean"],
                                        sampling_standard_error=float(np.std(executed["returns"], ddof=1) / 64)),
                no_confirmation_data_used=True, no_training_data_used=True,
                process_cpu_seconds=time.process_time() - started)


if __name__ == "__main__":
    result = run()
    path = Path(__file__).with_name("DEVELOPMENT_CHECKS.json")
    path.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps(result, sort_keys=True, allow_nan=False))
