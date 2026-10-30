"""Independent numerical audit. Each invocation creates a new evidence directory."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time
import traceback

import jax
jax.config.update("jax_enable_x64", True)
import jax.numpy as jnp
import numpy as np

from . import api, kernel, reference


ROOT = Path(__file__).parent


def suffix(params, state):
    state = api.observe(params, jnp.array([.3, -.2, .1]), api.propagate(state, .17))
    return api.observe(params, jnp.array([-.7, .4, .2]), api.propagate(state, 1.6))


def distance(left, right):
    return max(float(np.max(np.abs(np.asarray(left[k]) - np.asarray(right[k])))) for k in left)


def validate(out):
    protocol = json.loads((ROOT / "protocol.json").read_text())
    gates, records = protocol["acceptance"], []
    rng = np.random.default_rng(protocol["audit_seed"])
    def check(name, value, limit, sense="maximum"):
        passed = value <= limit if sense == "maximum" else value >= limit
        records.append(dict(name=name, value=float(value), limit=limit, sense=sense, passed=bool(passed)))
        return passed

    theta = np.array([.13, .47, .75, -.11, .65])
    p = rng.dirichlet(np.ones(10))
    advance = jax.jit(kernel.operator)
    errors = []
    for dt in [0., .03, .36, 1.17, 8.3, 40.]:
        transition, counts = advance(jnp.array(theta), dt)
        exact = reference.exact(theta, dt)
        errors.append(dict(duration=dt, state_l1=float(np.abs(p @ transition - p @ exact[:10, :10]).sum()),
                           count_absolute=float(abs(p @ counts - p @ exact[:10, 10])),
                           certificate=kernel.error_bounds(dt)))
    check("dense_state_l1", max(x["state_l1"] for x in errors), gates["dense_state_l1"])
    check("dense_event_absolute", max(x["count_absolute"] for x in errors), gates["dense_event_absolute"])
    params = api.init_parameters(seed=31, dtype=jnp.float64)
    state = api.initial_state(params)
    state = api.observe(params, jnp.array([1., -.5, .2]), state)
    combined, split = api.propagate(state, 3.73), state
    for dt in [.03, .7, 1.1, 1.9]:
        split = api.propagate(split, dt)
    check("semigroup_complete_state", distance(combined, split), gates["semigroup_full_state_absolute"])
    check("zero_time_identity", distance(state, api.propagate(state, 0.)), 0.)
    check("no_observation_counter_unchanged", abs(int(combined["observations"]) - int(state["observations"])), 0.)
    zero_observed = api.observe(params, jnp.zeros(3), combined)
    check("explicit_zero_changes_content", np.max(abs(np.asarray(zero_observed["content"] - combined["content"]))), 1e-4, "minimum")

    phase = dict(state, probability=jnp.eye(10, dtype=jnp.float64)[8])
    phase_final = api.propagate(phase, 2.1)
    ref = reference.exact(np.asarray(phase["physical"]), 2.1)
    check("existing_refractory_phases", np.max(abs(np.asarray(phase_final["probability"]) - ref[8, :10])), gates["dense_state_l1"])
    check("refractory_not_restarted", distance(phase_final, api.propagate(api.propagate(phase, .7), 1.4)), gates["semigroup_full_state_absolute"])
    long_state = api.propagate(state, 40.)
    next_probability = float(kernel.next_event_probability(state["probability"], state["physical"], 40.))
    repeated_count = float(long_state["events"] - state["events"])
    check("longgap_expected_count_exceeds_one", repeated_count, 1.0001, "minimum")
    check("first_next_probability_in_unit_interval", max(-next_probability, next_probability - 1, 0), 1e-10)
    check("count_dominates_first_next_probability", repeated_count - next_probability, 0., "minimum")
    killed = reference.augmented(np.asarray(state["physical"]))[:10, :10]
    killed[7, 8] = 0.
    from scipy.linalg import expm
    next_ref = 1 - np.asarray(state["probability"]) @ expm(killed * 40.) @ np.ones(10)
    check("first_next_independent_killed_reference", abs(next_probability - next_ref), gates["dense_state_l1"])
    check("probability_mass", abs(float(long_state["probability"].sum()) - 1), gates["mass_absolute"])
    check("minimum_probability", float(long_state["probability"].min()), gates["minimum_probability"], "minimum")

    shrink = dict(params, dynamics=jnp.array([[0., 0., -5.], [0., 0., 0.], [0., 0., 0.]]))
    top = dict(api.initial_state(params), probability=jnp.eye(10, dtype=jnp.float64)[7])
    shrunk = api.observe(shrink, jnp.array([1., 0., 0.]), top)
    check("zero_time_boundary_event", abs(float(shrunk["events"]) - 1), 1e-12)
    check("zero_time_boundary_phase_inventory", abs(float(shrunk["probability"][8]) - 1), 1e-12)
    check("zero_time_boundary_clock", abs(float(shrunk["elapsed"])), 0.)
    independent = jax.jit(jax.vmap(kernel.operator, in_axes=(None, 0)))(jnp.array(theta), jnp.array([.03, 40.]))
    check("long_neighbor_numerical_noninterference", np.max(abs(np.asarray(independent[0][0]) - np.asarray(advance(jnp.array(theta), .03)[0]))), 1e-12)

    terminal = np.r_[np.linspace(-.3, .8, 10), .31]
    def objective(t, prob, duration):
        transition, event_vector = kernel.operator(t, duration)
        return prob @ transition @ jnp.array(terminal[:10]) + terminal[-1] * (prob @ event_vector)
    value, gradients = jax.jit(jax.value_and_grad(objective, argnums=(0, 1, 2)))(jnp.array(theta), jnp.array(p), 1.17)
    independent_gradients = reference.scalar_and_derivatives(theta, p, 1.17, terminal)
    grad_rows = {}
    for name, actual, expected in zip(("physical", "probability", "duration"), gradients,
                                      (independent_gradients["physical"], independent_gradients["probability"], independent_gradients["duration"])):
        error = float(np.max(abs(np.asarray(actual) - expected) / (1 + abs(expected))))
        grad_rows[name] = dict(autodiff=np.asarray(actual).tolist(), independent=np.asarray(expected).tolist(), scaled_error=error)
        check(name + "_gradient", error, gates["gradient_scaled"])
    check("physical_centered_difference", np.max(abs(np.asarray(gradients[0]) - independent_gradients["centered"]) / (1 + abs(independent_gradients["centered"]))), gates["gradient_scaled"])
    observations = jnp.array([[1., -.5, .2], [.1, .4, -.7], [-.6, .2, .8]])
    gaps = jnp.array([.1, .7, 1.4])
    def content_objective(model):
        final, _ = api.run_sequence(model, observations, gaps)
        return final["content"] @ jnp.array([.2, -.3, .7, .1]) + .03 * final["reward"]
    projection_gradients = jax.jit(jax.grad(content_objective))(params)
    projection_norms = {key: float(jnp.linalg.norm(value)) for key, value in projection_gradients.items()}
    check("content_projection_gradient", projection_norms["input"], gates["observation_projection_gradient_norm_minimum"], "minimum")
    check("recurrent_content_gradient", projection_norms["recurrent"], gates["observation_projection_gradient_norm_minimum"], "minimum")
    check("dynamics_projection_gradient", projection_norms["dynamics"], gates["observation_projection_gradient_norm_minimum"], "minimum")
    direction = np.zeros_like(np.asarray(params["input"]))
    direction[1, 2] = 1e-5
    numerical = (float(content_objective(dict(params, input=params["input"] + direction))) - float(content_objective(dict(params, input=params["input"] - direction)))) / 2e-5
    check("content_projection_centered_difference", abs(numerical - float(projection_gradients["input"][1, 2])) / (1 + abs(numerical)), gates["gradient_scaled"])

    checkpoint = out / "checkpoint.npz"
    api.save_checkpoint(checkpoint, params, combined)
    recovery = subprocess.run([sys.executable, "-m", __package__ + ".validate", "--recover", str(checkpoint), str(out / "recovered.npz")],
                              capture_output=True, text=True, check=False)
    (out / "recovery.log").write_text(recovery.stdout + recovery.stderr)
    if recovery.returncode != 0:
        raise RuntimeError("Independent recovery process failed")
    _, recovered = api.load_checkpoint(out / "recovered.npz")
    check("fresh_process_recovery", distance(suffix(params, combined), recovered), gates["fresh_process_recovery_absolute"])
    rejections = 0
    for bad in [-1., float("nan"), kernel.MAX_DURATION + 1]:
        try:
            api.checked_propagate(state, bad)
        except ValueError:
            rejections += 1
    try:
        api.checked_propagate(dict(state, probability=state["probability"] * .7), .1)
    except ValueError:
        rejections += 1
    check("invalid_inputs_rejected", rejections, 4, "minimum")

    # Reuse the prior independent continuous reference; do not relabel grid error.
    from tools.hcsn.third.flow.continuous_reference import renewal_statistics
    from tools.hcsn.third.flow.finite_grid_reference import finite_grid_statistics
    common = dict(initial=.75, reset=.86, nu=-.13, sigma=.47, refractory_mean=.65, duration=3., stages=2)
    continuum = renewal_statistics(**common, terms=30)
    grids = [finite_grid_statistics(**common, cells=n, upper_wall=2.75) for n in (8, 64)]
    return dict(passed=all(row["passed"] for row in records), checks=records,
                dense_cases=errors, gradients=grad_rows, projection_gradient_norms=projection_norms,
                projection_objective="content linear readout plus .03 internal reward; not a content benchmark",
                longgap=dict(next_event_probability=next_probability, repeated_count=repeated_count),
                continuous_reference=dict(continuum=continuum, grids=grids, scope="Spatial/reflection diagnostic, not an equality gate"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--recover", nargs=2)
    args = parser.parse_args()
    if args.recover:
        params, state = api.load_checkpoint(args.recover[0])
        api.save_checkpoint(args.recover[1], params, suffix(params, state))
        return
    if args.output is None:
        parser.error("--output requires a new evidence directory")
    args.output.mkdir(parents=True, exist_ok=False)
    start, cpu_start = time.perf_counter(), time.process_time()
    sources = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ROOT.iterdir()) if p.suffix in (".py", ".json")}
    (args.output / "source_hashes.json").write_text(json.dumps(sources, indent=2) + "\n")
    (args.output / "source").mkdir()
    for name in sources:
        shutil.copy2(ROOT / name, args.output / "source" / name)
    result = {"passed": False}
    try:
        result = validate(args.output)
    except Exception:
        result["exception"] = traceback.format_exc()
    result["execution"] = dict(wall_seconds=time.perf_counter() - start, process_cpu_seconds=time.process_time() - cpu_start,
                                child_cpu_seconds=resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime + resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime,
                                max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                                affinity=sorted(os.sched_getaffinity(0)), python=sys.version, jax=jax.__version__, numpy=np.__version__,
                                blas_threads={key: os.environ.get(key) for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")})
    (args.output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(dict(passed=result["passed"], checks=len(result.get("checks", [])), exception=result.get("exception"), execution=result["execution"])))
    jax.clear_caches()
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
