"""Development checks for the separate full-cell joint experiment.

Only synthetic H=2/H=4 training-side fixtures are used. No heldout or prior
confirmation results are read. N remains 15. Two optional Adam steps measure
development cost; their models are never candidate checkpoints.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
from pathlib import Path
import resource
import time
import traceback

import numpy as np
import torch

from ...round7.joint_control import build_graph
from ...round7.task import ACTIONS, Episode, TaskParameters, features, initial_state, legal_actions, step
from .full_joint import evaluate, make_model, make_trainable


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_safe(value):
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, Path):
        return str(value)
    return value


def sensitive_fixture(mode):
    """Independent non-saturated audit object; no saved baseline is modified."""
    model, metadata = make_model(mode, seed=11)
    if model.n_grid != 15:
        raise AssertionError("development audit must retain N=15")
    with torch.no_grad():
        model.drive.weight.zero_()
        model.drive.bias.fill_(math.atanh(.3 / 1.5))
        for name, fraction in (("raw_boundary", (.65-.35)/1.65),
                               ("raw_diffusion", (.60-.05)/.75),
                               ("raw_recovery", (.65-.05)/.90)):
            getattr(model.core, name).fill_(math.log(fraction/(1-fraction)))
        model.core.raw_reset_plus.fill_(math.atanh(-.25/.75))
        model.core.raw_reset_minus.fill_(math.atanh(.25/.75))
        model.readout[0].weight.zero_()
        model.readout[0].bias.zero_()
        for row, latent_weight, content_weight in ((0, .8, .3), (1, .5, .4), (2, .9, .3), (3, -.7, .2)):
            model.readout[0].weight[row, -4+row] = latent_weight
            model.readout[0].weight[row, 18+row] = content_weight
        model.readout[2].weight.zero_()
        model.readout[2].bias.zero_()
        for row, column, value in ((4, 0, .25), (4, 2, -.20), (5, 0, -.15),
                                   (5, 1, .10), (6, 3, .20), (6, 2, .15),
                                   (7, 0, -.10), (7, 2, .15)):
            model.readout[2].weight[row, column] = value
        model.readout[2].bias[4:] = torch.tensor([.03, .01, -.02, 0.], dtype=torch.float64)
    make_trainable(model)
    return model, metadata


def explicit_world_paths(model, parameters, temperature=.12, compute_price=.0005, event_price=.0002):
    """Sum all 16 private worlds and every internal-state/action path.

    Reward and public successors come from task.step, not the training oracle.
    The conditional transition is clipped/normalized exactly as hard_soft
    sampling; direct mode explicitly uses its identity transition.
    """
    if parameters.horizon != 2 or parameters.ordinary_count != 1:
        raise ValueError("the explicit-world fixture is H=2 with one source")
    cache, leaves = {}, 0
    totals = np.zeros(4, dtype=np.float64)

    def public_policy(state):
        if state not in cache:
            inputs = torch.from_numpy(features(state)[None, :])
            content, drive = model.encode(inputs)
            if model.mode == "direct":
                transition = np.eye(model.core.n_states, dtype=np.float64)
            else:
                transition = model.core.transition_matrix(drive)[0][0].numpy()
                transition = np.clip(transition, 0, None)
                transition /= transition.sum(-1, keepdims=True)
            scores = model.state_action_values(inputs, content)[0, :, 1, :]
            permitted = torch.tensor([a in legal_actions(state) for a in ACTIONS])
            policy = torch.softmax(scores.masked_fill(~permitted[None, :], -1e9)/temperature, -1)
            cache[state] = transition, policy.numpy()
        return cache[state]

    def visit(episode, state, before, probability, reward, decisions, event_count):
        nonlocal leaves
        if state.terminated:
            totals[:] += probability * np.array([1., reward, decisions, event_count])
            leaves += 1
            return
        transition, policy = public_policy(state)
        for after, transition_probability in enumerate(transition[before]):
            if transition_probability <= 0:
                continue
            emitted = int(before < model.n_grid and after >= model.n_grid)
            for action_index, action in enumerate(ACTIONS):
                action_probability = policy[after, action_index]
                if action_probability == 0:
                    continue
                successor = step(state, action, episode)
                visit(episode, successor.state, after, probability * transition_probability * action_probability,
                      reward + successor.reward - compute_price - event_price * emitted,
                      decisions + 1, event_count + emitted)

    with torch.no_grad():
        for truth, ordinary, delayed, corrupt in itertools.product((-1, 1), (-1, 1), (-1, 1), (False, True)):
            probability = parameters.prior_probability if truth == 1 else 1 - parameters.prior_probability
            probability *= parameters.ordinary_reliability if ordinary == truth else 1 - parameters.ordinary_reliability
            probability *= parameters.delayed_reliability if delayed == truth else 1 - parameters.delayed_reliability
            probability *= parameters.corruption_probability if corrupt else 1 - parameters.corruption_probability
            episode = Episode(0, parameters, truth, (ordinary,), delayed, corrupt)
            visit(episode, initial_state(episode), model.n_grid//2, probability, 0., 0, 0)
    return {"probability_mass": float(totals[0]), "metrics": totals[1:].tolist(),
            "external_worlds": 16, "complete_leaf_paths": leaves}


def finite_difference(model, graph, parameter, coordinate, epsilon=1e-5):
    original = float(parameter[coordinate].detach())
    with torch.no_grad():
        parameter[coordinate] = original + epsilon
        high = float(evaluate(model, graph)[0][0])
        parameter[coordinate] = original - epsilon
        low = float(evaluate(model, graph)[0][0])
        parameter[coordinate] = original
    return (high-low)/(2*epsilon)


def run_case(mode, updates):
    model, metadata = sensitive_fixture(mode)
    h2 = TaskParameters(horizon=2, budget=2, ordinary_count=1, ordinary_reliability=.72,
                        delayed_reliability=.86, arrival_tick=1, corruption_probability=.3,
                        prior_probability=.58)
    graph2 = build_graph([h2])
    explicit = explicit_world_paths(model, h2)
    with torch.no_grad():
        actual = evaluate(model, graph2)[0].numpy()
    path_error = float(np.abs(actual - explicit["metrics"]).max())
    fees = []
    for name, price, count in (("compute_price", .0005, explicit["metrics"][1]),
                               ("event_price", .0002, explicit["metrics"][2])):
        epsilon = 1e-5
        with torch.no_grad():
            high = float(evaluate(model, graph2, **{name: price+epsilon})[0][0])
            low = float(evaluate(model, graph2, **{name: price-epsilon})[0][0])
        numerical = (high-low)/(2*epsilon)
        fees.append({"price": name, "finite_difference": numerical, "negative_explicit_count": -count,
                     "absolute_error": abs(numerical+count)})

    h4 = TaskParameters(horizon=4, budget=3, ordinary_count=1, ordinary_reliability=.65,
                        delayed_reliability=.85, arrival_tick=1, corruption_probability=.5,
                        read_cost=.08, wait_cost=.03, repair_cost=.05, stop_cost=.01,
                        latency_cost=.01, prior_probability=.58)
    graph4 = build_graph([h4])
    probes = [("core."+name, p, ()) for name, p in model.core.named_parameters() if p.requires_grad]
    probes += [("content.0.weight", model.content[0].weight, (0, 0)),
               ("readout.0.weight", model.readout[0].weight, (0, 18)),
               ("readout.2.weight", model.readout[2].weight, (4, 0))]
    if model.drive.bias.requires_grad:
        probes.append(("drive.bias", model.drive.bias, (0,)))
    value = evaluate(model, graph4)[0][0]
    gradients = torch.autograd.grad(value, [p for _, p, _ in probes], allow_unused=True)
    checks = []
    for (name, parameter, coordinate), gradient in zip(probes, gradients):
        automatic = 0. if gradient is None else float(gradient[coordinate])
        numerical = finite_difference(model, graph4, parameter, coordinate)
        error = abs(automatic-numerical)
        checks.append({"parameter": name, "coordinate": list(coordinate), "automatic": automatic,
                       "central_difference": numerical, "absolute_error": error,
                       "finite": math.isfinite(automatic) and math.isfinite(numerical),
                       "passed": math.isfinite(error) and error <= 2e-8+2e-4*abs(numerical)})
    inactive = [name for name, p in model.named_parameters() if not p.requires_grad]
    expected_inactive = ["core.raw_leak"]
    if mode == "direct":
        expected_inactive += [name for name, _ in model.named_parameters() if name.startswith(("core.", "drive."))]
    elif mode == "continuous":
        expected_inactive += ["core.raw_reset_plus", "core.raw_reset_minus", "core.raw_recovery"]
    active_parameters = make_trainable(model)
    initial = {name: p.detach().clone() for name, p in model.named_parameters()}
    optimizer = torch.optim.Adam(active_parameters, lr=.003)
    steps = []
    for update in range(updates):
        optimizer.zero_grad(set_to_none=True)
        wall, cpu = time.perf_counter(), time.process_time()
        metrics, _ = evaluate(model, graph4)
        (-metrics[0]).backward()
        by_tensor = {name: {"norm": 0. if p.grad is None else float(p.grad.norm()),
                           "nonzero_coordinates": 0 if p.grad is None else int(torch.count_nonzero(p.grad)),
                           "finite": p.grad is None or bool(torch.isfinite(p.grad).all())}
                     for name, p in model.named_parameters() if p.requires_grad}
        norm = torch.nn.utils.clip_grad_norm_(active_parameters, 5., error_if_nonfinite=True)
        optimizer.step()
        steps.append({"update": update+1, "pre_update_metrics": metrics.detach().tolist(),
                      "gradient_by_tensor": by_tensor, "pre_clip_total_norm": float(norm),
                      "wall_seconds": time.perf_counter()-wall, "process_cpu_seconds": time.process_time()-cpu,
                      "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
    with torch.no_grad():
        final = evaluate(model, graph4)[0].tolist()
    changes = {name: float((p.detach()-initial[name]).abs().max()) for name, p in model.named_parameters()}
    guards = {"full_path_metrics": path_error <= 3e-12,
              "world_mass": abs(explicit["probability_mass"]-1) <= 3e-12,
              "fees": all(x["absolute_error"] <= 2e-9 for x in fees),
              "complete_return_gradients": all(x["passed"] for x in checks),
              "effective_core_gradient_nonzero": all(abs(x["automatic"]) > 1e-12 for x in checks if x["parameter"].startswith("core.")),
              "inactive_parameters_frozen": all(name in inactive for name in expected_inactive),
              "frozen_parameters_unchanged": all(changes[name] == 0 for name in inactive),
              "development_gradients_finite": all(p["finite"] for s in steps for p in s["gradient_by_tensor"].values())}
    return {"mode": mode, "n_grid": model.n_grid, "inherited_metadata": metadata,
            "fixture_modifications": "Only this in-memory development model: non-saturated drive/readout, sigma=.6, b=.65, reset centers=+/- .25*b, q_ref=.65.",
            "h2_public_states": len(graph2.states), "explicit_world_paths": explicit, "graph_h2_metrics": actual.tolist(),
            "maximum_h2_metric_error": path_error, "fee_derivatives": fees,
            "h4_public_states": len(graph4.states), "gradient_probes": checks, "inactive_parameters": inactive,
            "requested_trainable_scalars_including_zero_gradient_coordinates": sum(p.numel() for p in active_parameters),
            "development_updates": steps, "final_development_metrics": final,
            "maximum_parameter_change_by_tensor": changes, "guards": guards,
            "passed": all(guards.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--updates", type=int, choices=(0, 2), default=2)
    args = parser.parse_args()
    torch.set_num_threads(1)
    sources = {str(Path(__file__).name): digest(__file__), "full_joint.py": digest(Path(__file__).with_name("full_joint.py"))}
    started = time.perf_counter()
    cases = []
    for mode in ("direct", "continuous", "clocked", "first_passage"):
        try:
            cases.append(run_case(mode, args.updates))
        except Exception as error:
            cases.append({"mode": mode, "passed": False, "error": repr(error), "traceback": traceback.format_exc()})
        print(json.dumps({"mode": mode, "passed": cases[-1]["passed"]}), flush=True)
    unchanged = all(digest(Path(__file__).with_name(name)) == value for name, value in sources.items())
    result = {"schema": "hepta.full-joint.development-audit.v1", "created_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "Synthetic H2/H4 public training-side fixtures only, N15 unchanged. No heldout/confirmation read, no candidate checkpoint, no selection on these audit updates.",
              "runtime": {"torch": torch.__version__, "numpy": np.__version__, "threads": torch.get_num_threads(),
                          "peak_rss_units": "KiB on the recorded Linux runtime; process-wide peak, not a per-step allocation delta"},
              "source_sha256": sources, "source_unchanged": unchanged, "cases": cases,
              "wall_seconds": time.perf_counter()-started, "passed": unchanged and all(r["passed"] for r in cases)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(json_safe(result), stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
