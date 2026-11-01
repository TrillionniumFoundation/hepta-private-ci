"""Independent ODE reference and finite support/time-segmentation audit.

No project transition, event integral or compression routine is used by the ODE
right-hand side. This checks the finite generator, not continuum approximation.
"""

import argparse
import json
import platform
import time
from pathlib import Path

import numpy as np
import scipy
from scipy.integrate import solve_ivp

from .compression import AnchoredPackedMemory, BlockLaw, COLLECT, SPREAD, pack, unpack


TIMES = (0., .00001, .003, .03, .17, .83, 2.7, 8.)
THETA = ((.22, .008), (.30, .018), (.38, .032))


def ode_reference(q, times):
    """Integrate conservative/killed forward laws and event reward equations."""
    killed = q.copy()
    rates = np.zeros(40)
    for content in range(4):
        rates[content] = q[content, 32 + content]
        killed[content, 32 + content] = 0.
    initial = np.r_[np.eye(40).ravel(), np.eye(40).ravel(), np.zeros(80)]

    def derivative(_, y):
        return np.r_[(y[:1600].reshape(40, 40) @ q).ravel(),
                     (y[1600:3200].reshape(40, 40) @ killed).ravel(),
                     killed @ y[3200:3240] + rates, q @ y[3240:] + rates]

    result = solve_ivp(derivative, (0., max(times)), initial, t_eval=times,
                       method="DOP853", rtol=2e-12, atol=2e-14)
    if not result.success:
        raise RuntimeError(result.message)
    return result, killed, rates


def run():
    started, wall = time.process_time(), time.perf_counter()
    records = []
    for theta in THETA:
        law = BlockLaw(theta)
        reference, killed, rates = ode_reference(law.Q, TIMES)
        for index, duration in enumerate(TIMES):
            y = reference.y[:, index]
            transition = law.transition(duration)
            first, count = law.first_hit(np.eye(40), duration), law.event_count(np.eye(40), duration)
            survival = y[1600:3200].reshape(40, 40).sum(1)
            projected = unpack(pack(np.eye(40)))
            expanded_after = projected @ transition
            support_lost = int(np.sum((transition > 0) & (expanded_after <= 0)))
            observation_lost = 0
            for emission in (law.E_read, law.E_refresh):
                observation_lost += int(np.sum((transition @ emission > 0) & (expanded_after @ emission <= 0)))
            records.append(dict(theta=theta, duration=duration,
                transition_error=float(np.max(np.abs(transition - y[:1600].reshape(40, 40)))),
                first_hit_error=float(np.max(np.abs(first - y[3200:3240]))),
                event_count_error=float(np.max(np.abs(count - y[3240:]))),
                mass_error=float(np.max(np.abs(transition.sum(1) - 1))),
                hit_survival_error=float(np.max(np.abs(first + survival - 1))),
                first_hit_min=float(first.min()), first_hit_max=float(first.max()),
                event_count_minus_first_min=float(np.min(count - first)),
                minimum_probability=float(transition.min()), support_lost=support_lost,
                legal_observations_lost=observation_lost))
        duration, step = .17, 1e-6
        derivative = (law.transition(duration + step) - law.transition(duration - step)) / (2 * step)
        ode_at = reference.y[:1600, TIMES.index(duration)].reshape(40, 40)
        gradient_error = float(np.max(np.abs(derivative - ode_at @ law.Q)))
        records.append(dict(theta=theta, time_gradient_error=gradient_error,
            full_semigroup_error=float(np.max(np.abs(law.transition(.31) @ law.transition(.53) - law.transition(.84)))),
            block_semigroup_error=float(np.max(np.abs(
                (SPREAD @ law.transition(.31) @ COLLECT) @ (SPREAD @ law.transition(.53) @ COLLECT)
                - SPREAD @ law.transition(.84) @ COLLECT))), ode_function_evaluations=reference.nfev))
    law = BlockLaw()
    whole = AnchoredPackedMemory(law, [0, 1, 2, 3])
    split = AnchoredPackedMemory(law, [0, 1, 2, 3])
    dynamic = []
    for step, duration in enumerate((.001, .03, .83, 2.7, .17)):
        whole.advance(duration)
        for _ in range(11):
            split.advance(duration / 11)
        before_error = float(np.max(np.abs(whole.beliefs - split.beliefs)))
        # Read erasure is a genuine observation, not a missing-token mask.
        quality, token = ("read", 4) if step == 2 else ("refresh", step % 4)
        whole.observe(step % 4, token, quality)
        split.observe(step % 4, token, quality)
        whole.write((step + 1) % 4, (step + 2) % 4)
        split.write((step + 1) % 4, (step + 2) % 4)
        whole = AnchoredPackedMemory.restore(law, whole.checkpoint())
        split = AnchoredPackedMemory.restore(law, split.checkpoint())
        dynamic.append(dict(duration=duration, missing_intermediate_observations=10,
            observation=[quality, token], pre_observation_segmentation_error=before_error,
            posterior_error=float(np.max(np.abs(whole.beliefs - split.beliefs))),
            packed_state_error=float(np.max(np.abs(whole.packed - split.packed)))))
    numeric = [x for x in records if "duration" in x]
    summary = {key: max(x[key] for x in numeric) for key in
               ("transition_error", "first_hit_error", "event_count_error", "mass_error", "hit_survival_error")}
    summary.update(legal_observations_lost=sum(x["legal_observations_lost"] for x in numeric),
                   support_lost=sum(x["support_lost"] for x in numeric),
                   time_gradient_error=max(x.get("time_gradient_error", 0.) for x in records),
                   full_semigroup_error=max(x.get("full_semigroup_error", 0.) for x in records),
                   block_semigroup_error=max(x.get("block_semigroup_error", 0.) for x in records),
                   anchored_segmentation_error=max(x[key] for x in dynamic for key in
                       ("pre_observation_segmentation_error", "posterior_error", "packed_state_error")))
    gates = dict(finite_ode_agreement=max(summary[k] for k in
                 ("transition_error", "first_hit_error", "event_count_error", "hit_survival_error")) < 2e-9,
                 mass_and_positivity=summary["mass_error"] < 2e-12 and all(
                     x["minimum_probability"] >= -2e-13 for x in numeric),
                 first_hit_and_repeated_count=all(x["first_hit_min"] >= -2e-12
                     and x["first_hit_max"] <= 1 + 2e-12
                     and x["event_count_minus_first_min"] >= -2e-12 for x in numeric),
                 finite_support=summary["support_lost"] == summary["legal_observations_lost"] == 0,
                 time_gradient=summary["time_gradient_error"] < 2e-7,
                 full_semigroup=summary["full_semigroup_error"] < 2e-12,
                 block_semigroup=summary["block_semigroup_error"] < 2e-12,
                 anchored_segmentation=summary["anchored_segmentation_error"] < 2e-12)
    return dict(schema="hcsn-r16-support-operator-audit-v1", summary=summary, gates=gates,
                records=records, dynamic=dynamic, numeric_state_bytes=296,
                scope="Finite R15 law, 3 parameters x 40 initial states x 8 durations; time derivative only. No continuum, financial-parameter-gradient, learned-core or energy admission.",
                runtime=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__),
                cpu_seconds=time.process_time() - started, wall_seconds=time.perf_counter() - wall)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        json.dump(result, handle, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps(dict(summary=result["summary"], gates=result["gates"],
                          cpu_seconds=result["cpu_seconds"]), indent=2))
