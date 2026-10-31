"""Fresh-world renewal follow-up with separated forecasts and full-process costs.

This preserves v2's synthetic perfect-sensor task, unequal core priors/capacities,
and one-read receding heuristic. It does not establish natural-AV or SSM gains.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time
import traceback

import numpy as np
import torch

from experiments.hcsn_mechanism_content_v2 import mechanism as old
from experiments.hcsn_mechanism_content_v2.renewal import (
    GatedPropagator, LearnedCore, Physics, RenewalCore, fit_ordinary,
)

ROOT = Path(__file__).resolve().parents[2]
ARMS = {
    "A": ("ordinary", "lightweight", "none"),
    "B": ("ordinary", "task_value", "none"),
    "C": ("analytic", "lightweight", "none"),
    "D": ("analytic", "task_value", "none"),
    "D_current": ("analytic", "task_value", "current"),
    "D_hypothetical": ("analytic", "task_value", "hypothetical"),
    "D_both": ("analytic", "task_value", "both"),
    "B_on_D": ("ordinary", "fixed_action_replay", "none"),
    "hold_on_D": ("frozen", "fixed_action_replay", "none"),
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def jsonl(path):
    with Path(path).open() as stream:
        return [json.loads(line) for line in stream]


def policy(core, controller, obs, tick, budget, physics, matrix, config,
           simulation_seed, intervention="none"):
    """Scope current-observation forecasts separately from fake-READ forecasts.

    Suppression holds an observed content distribution in the POLICY only; it
    is a joint event/content forecast intervention, never a pure risk-channel
    or independent financial Put ablation. Actual output propagation is intact.
    """
    if intervention not in ("none", "current", "hypothetical", "both"):
        raise ValueError("Unknown forecast intervention")
    if intervention in ("none", "both"):
        return old.choose_action(core, controller, obs, tick, budget, physics,
                                 matrix, config, simulation_seed,
                                 suppress_events=intervention == "both")
    future = [d for d in config.deadlines if d > tick]
    if not future or budget <= 0:
        return "STOP", {"reason": "no_future_output_or_budget", "simulations": 0}
    prior = {d: old.policy_prediction(core, obs, d * config.dt, physics, matrix,
                                      intervention == "current") for d in future}
    if controller == "lightweight":
        error = float(1 - prior[future[0]].max())
        request = "READ" if error > config.light_threshold and future[0] - tick <= 2 else "WAIT"
        return request, {"forecast_error": error, "simulations": 0}
    candidates = sorted(set([tick + 1] + future))
    start_tick = round(obs.time / config.dt)
    grid = np.arange(start_tick, config.ticks + 1) * config.dt
    rng = np.random.default_rng(simulation_seed)
    samples = [old.generate_path(rng, physics, grid, obs.x,
               int(rng.choice(config.classes, p=obs.content_probs)), matrix,
               obs.refractory_remaining) for _ in range(config.particles)]
    baseline = sum(1 - p.max() for p in prior.values()) / len(config.deadlines)
    values = []
    for arrival in candidates:
        loss = 0.
        for sample in samples:
            index = arrival - start_tick
            fake = old.Observation(arrival * config.dt, sample["x"][index],
                sample["refractory_remaining"][index],
                np.eye(config.classes)[sample["content"][index]].tolist(), True)
            for deadline in future:
                predicted = (prior[deadline] if deadline < arrival else
                    old.policy_prediction(core, fake, deadline * config.dt,
                        physics, matrix, intervention == "hypothetical"))
                loss += 1 - predicted.max()
        loss /= config.particles * len(config.deadlines)
        values.append({"arrival_tick": arrival, "net_value": float(baseline - loss - config.read_cost)})
    best = max(values, key=lambda row: (row["net_value"], -row["arrival_tick"]))
    action = "STOP" if best["net_value"] <= 0 else ("READ" if best["arrival_tick"] == tick + 1 else "WAIT")
    return action, {"candidate_values": values, "selected_arrival": best["arrival_tick"],
                   "simulations": config.particles, "value_scope": "one_planned_read_heuristic"}


def rollout(core, controller, episode, config, intervention="none", forced=None):
    """v2 action chronology with injectable policy; raw exact traces retained."""
    physics = Physics(**episode["calibration"]["estimated"])
    path, matrix = episode["path"], old.transition_matrix(config.classes)
    obs = old.Observation(0., episode["initial_x"], 0., [1 / config.classes] * config.classes, False)
    budget, pending, stopped, reads = config.budget, None, False, 0
    trace, access, predictions = [], [], []
    wall, cpu, control_cpu = time.perf_counter(), time.process_time(), 0.
    core.evaluation_seconds = 0.
    core.calls = core.work = core.cdf_terms = 0
    for tick in range(config.ticks + 1):
        now = tick * config.dt
        if pending == tick:
            obs = old.Observation(now, path["x"][tick], path["refractory_remaining"][tick],
                                  np.eye(config.classes)[path["content"][tick]].tolist(), True)
            access.append({"request_tick": tick - 1, "reveal_tick": tick,
                           "observed_state": asdict(obs), "external_state_reset": False})
            pending = None
        if tick in config.deadlines:
            probs, event = old.predict(core, obs, now, physics, matrix)
            truth = path["content"][tick]
            predictions.append({"tick": tick, "probabilities": probs.tolist(),
                "truth_for_scoring_only": truth, "observed_state": asdict(obs),
                "horizon_since_read": now - obs.time, **event,
                "correct": int(probs.argmax() == truth),
                "nll": float(-np.log(max(probs[truth], 1e-12))),
                "brier": float(np.square(probs - np.eye(config.classes)[truth]).sum())})
        if tick == config.ticks or stopped:
            continue
        began = time.process_time()
        if forced is not None:
            request, detail = forced.get(tick, "STOP"), {"fixed_action_replay": True}
        else:
            seed = int(np.random.SeedSequence([episode["seed"], tick, 4337]).generate_state(1)[0])
            request, detail = policy(core, controller, obs, tick, budget, physics,
                                    matrix, config, seed, intervention)
        control_cpu += time.process_time() - began
        executed, guard = request, None
        if request == "READ" and (budget <= 0 or pending is not None):
            executed, guard = "WAIT", "budget_or_inflight"
        if executed == "READ":
            budget -= 1
            reads += 1
            pending = tick + 1
        if executed == "STOP":
            stopped = True
        visible, _ = old.predict(core, obs, now, physics, matrix)
        trace.append({"tick": tick, "requested_action": request, "executed_action": executed,
            "guard": guard, "budget_after": budget, "observed_state": asdict(obs),
            "propagated_content": visible.tolist(), "read_reveal_tick": pending,
            "physical_estimates": asdict(physics), "policy_detail": detail,
            "actual_future_available_to_policy": False})
    stats = {key: float(np.mean([p[field] for p in predictions]))
             for key, field in (("accuracy", "correct"), ("nll", "nll"), ("brier", "brier"))}
    stats.update(reads=reads, net_reward=stats["accuracy"] - reads * config.read_cost,
        arm_wall_seconds=time.perf_counter() - wall, arm_cpu_seconds=time.process_time() - cpu,
        controller_cpu_seconds_inclusive=control_cpu, core_wall_seconds_inclusive=core.evaluation_seconds,
        core_calls=core.calls, mandatory_outputs=len(predictions), energy_joules=None)
    return {"summary": stats, "trace": trace, "access": access, "predictions": predictions}


def source_manifest():
    paths = {Path(__file__).resolve(), Path(__file__).with_name("mechanism_followup_tests.py").resolve()}
    for name, module in sys.modules.items():
        filename = getattr(module, "__file__", None)
        if name.startswith("experiments.") and filename and filename.endswith(".py"):
            paths.add(Path(filename).resolve())
    return {str(path.relative_to(ROOT)): digest(path) for path in sorted(paths)}


def verify_sources(plan):
    for name, expected in plan["source_sha256"].items():
        if digest(ROOT / name) != expected:
            raise RuntimeError(f"Frozen source changed: {name}")


def freeze(output, episodes):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    plan = {
        "schema": "hcsn-mechanism-causal-followup.v3", "created_unix": time.time(),
        "output": str(output), "source_sha256": source_manifest(),
        "fit_seeds": [2026103181, 2026103182, 2026103183], "episodes_per_group": episodes,
        "conditions": ["matched", "hidden_refractory_mismatch"], "arms": ARMS,
        "world_namespace": [20261031, 39107], "worker_order_seed": 2026103191,
        "training": {"train_size": 8192, "epochs": 80, "width": 128, "cap": 32},
        "config": asdict(old.Config()), "bootstrap_replicates": 10000,
        "bootstrap_seed": 2026103193,
        "primary": "D minus B accuracy-minus-0.04*READ-fees, paired episodes; matched condition",
        "success": "descriptive paired hierarchy bootstrap lower95 >0; no noninferiority or architecture-wide claim",
        "secondary": "B-A,D-C,interaction; split forecast effects; fixed D schedule content scores",
        "cost_primary": "whole fresh process CPU per arm including imports, load, rollout, evidence serialization",
        "cost_exclusions": "synthetic-world generation separately charged; no hardware sensor/network or energy measure",
        "training_accounting": "3 ordinary fits charged once globally; B deployment cost separately shown with its own fit",
        "forecast_scope": "hold last observed content in policy forecasts, not pure risk-feature/Put intervention",
        "reuse": "v2 task, ordinary architecture, hyperparameters and controller; new fits and heldout worlds",
        "fit_development_selection": "fixed 80 epochs, no selection; inherited fixed development seed991238 reported only",
        "threads": 1, "workers_parallel": 1, "python": sys.executable,
    }
    write(output / "PROTOCOL.json", plan)
    print(json.dumps({"plan": str(output / "PROTOCOL.json"), "sha256": digest(output / "PROTOCOL.json")}))


def paths(plan, seed, condition=None, arm=None):
    base = Path(plan["output"])
    fit = base / f"fit_{seed}"
    group = base / f"world_{seed}_{condition}" if condition is not None else None
    run = base / f"arm_{seed}_{condition}_{arm}" if arm is not None else None
    return fit, group, run


def worker(plan_path, kind, seed, condition=None, arm=None):
    plan = json.loads(Path(plan_path).read_text())
    verify_sources(plan)
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    fit_path, world_path, run_path = paths(plan, seed, condition, arm)
    output = fit_path if kind == "fit" else world_path if kind == "world" else run_path
    if not output.is_dir():
        raise RuntimeError("Meter must create the worker directory")
    began_cpu, began_wall = time.process_time(), time.perf_counter()
    if kind == "fit":
        core, report, data = fit_ordinary(seed, **plan["training"])
        np.savez_compressed(output / "training.npz", **data)
        torch.save({"state_dict": core.model.state_dict(), "report": report}, output / "ordinary.pt")
        write(output / "training.json", report)
    elif kind == "world":
        config = old.Config(**{**plan["config"], "condition": condition})
        with (output / "worlds.jsonl").open("x") as stream:
            for index in range(plan["episodes_per_group"]):
                namespace = plan["world_namespace"] + [seed, plan["conditions"].index(condition), index]
                episode_seed = int(np.random.SeedSequence(namespace).generate_state(1)[0])
                episode = old.make_episode(episode_seed, config)
                episode["episode_index"] = index
                stream.write(json.dumps(episode, allow_nan=False) + "\n")
    else:
        loading_cpu = time.process_time()
        worlds = jsonl(world_path / "worlds.jsonl")
        family, controller, intervention = plan["arms"][arm]
        checkpoint_hash = None
        if family == "ordinary":
            checkpoint_path = fit_path / "ordinary.pt"
            checkpoint_hash = digest(checkpoint_path)
            checkpoint = torch.load(checkpoint_path, weights_only=False, map_location="cpu")
            report = checkpoint["report"]
            model = GatedPropagator(report["width"], report["cap"])
            model.load_state_dict(checkpoint["state_dict"])
            model.eval()
            core = LearnedCore(model, report["cap"])
        else:
            core = RenewalCore(cap=plan["training"]["cap"]) if family == "analytic" else old.FrozenContentCore()
        replay_source, replay_hash = None, None
        if controller == "fixed_action_replay":
            replay_path = paths(plan, seed, condition, "D")[2] / "episodes.jsonl"
            replay_source = jsonl(replay_path)
            replay_hash = digest(replay_path)
        loading_cpu = time.process_time() - loading_cpu
        config = old.Config(**{**plan["config"], "condition": condition})
        serial_cpu, rollout_cpu = 0., 0.
        with (output / "episodes.jsonl").open("x") as stream:
            for index, world in enumerate(worlds):
                forced = ({r["tick"]: r["executed_action"] for r in replay_source[index]["trace"]}
                          if replay_source is not None else None)
                began = time.process_time()
                result = rollout(core, controller, world, config, intervention, forced)
                rollout_cpu += time.process_time() - began
                result.update(episode_index=index, world_seed=world["seed"], arm=arm,
                              fit_seed=seed, condition=condition, intervention=intervention)
                began = time.process_time()
                stream.write(json.dumps(result, allow_nan=False) + "\n")
                stream.flush()
                serial_cpu += time.process_time() - began
        write(output / "identity.json", {"worlds_sha256": digest(world_path / "worlds.jsonl"),
            "checkpoint_sha256": checkpoint_hash, "replay_D_sha256": replay_hash,
            "protocol_sha256": digest(plan_path), "loading_cpu_seconds": loading_cpu,
            "rollout_cpu_seconds_inclusive": rollout_cpu, "output_cpu_seconds": serial_cpu,
            "all_output_forecasts_unsuppressed": True})
    write(output / "body.json", {"cpu_seconds": time.process_time() - began_cpu,
        "wall_seconds": time.perf_counter() - began_wall, "energy_joules": None,
        "scope": "worker body after imports; external receipt charges whole process",
        "python": platform.python_version(), "torch": torch.__version__, "threads": torch.get_num_threads()})


def metered(plan_path, kind, seed, condition=None, arm=None):
    plan = json.loads(Path(plan_path).read_text())
    fit, world, run = paths(plan, seed, condition, arm)
    output = fit if kind == "fit" else world if kind == "world" else run
    output.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, "-m", __name__, "worker", "--plan", str(plan_path),
               "--kind", kind, "--seed", str(seed)]
    # __name__ is __main__ under -m execution; use the stable module path.
    command[2] = "experiments.hcsn_causal_execution_v3.mechanism_followup"
    if condition is not None:
        command += ["--condition", condition]
    if arm is not None:
        command += ["--arm", arm]
    env = dict(os.environ)
    env.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    started = time.perf_counter()
    with (output / "worker.log").open("xb") as log:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    receipt = {"command": command, "exit_code": process.returncode,
        "user_cpu_seconds": usage.ru_utime, "system_cpu_seconds": usage.ru_stime,
        "cpu_seconds": usage.ru_utime + usage.ru_stime, "wall_seconds": time.perf_counter() - started,
        "max_rss_kib_linux": usage.ru_maxrss, "energy_joules": None,
        "protocol_sha256": digest(plan_path), "output_files_sha256": {
            p.name: digest(p) for p in sorted(output.iterdir()) if p.is_file()},
        "scope": "fresh process: interpreter/imports/load/execution/output/exit; no sensor or network hardware",
        "host_isolation": "shared host; study workers sequential; other correctness workloads may coexist"}
    write(output / "receipt.json", receipt)
    print(json.dumps({"worker": output.name, "exit_code": process.returncode,
                      "cpu_seconds": receipt["cpu_seconds"]}), flush=True)
    if process.returncode:
        raise RuntimeError(f"Worker failed; evidence retained: {output}")


def execute(plan_path):
    plan_path = Path(plan_path).resolve()
    plan = json.loads(plan_path.read_text())
    verify_sources(plan)
    began_cpu, began_wall = time.process_time(), time.perf_counter()
    write(Path(plan["output"]) / "EXECUTION_STARTED.json", {"unix": time.time(),
        "protocol_sha256": digest(plan_path), "source_sha256": source_manifest()})
    rng = np.random.default_rng(plan["worker_order_seed"])
    for seed in rng.permutation(plan["fit_seeds"]):
        metered(plan_path, "fit", int(seed))
    groups = [(seed, condition) for seed in plan["fit_seeds"] for condition in plan["conditions"]]
    rng.shuffle(groups)
    for seed, condition in groups:
        metered(plan_path, "world", seed, condition)
        main = list("ABCD")
        rng.shuffle(main)
        for arm in main:
            metered(plan_path, "arm", seed, condition, arm)
        extras = [arm for arm in plan["arms"] if arm not in main]
        rng.shuffle(extras)
        for arm in extras:
            metered(plan_path, "arm", seed, condition, arm)
    write(Path(plan["output"]) / "EXECUTION_COMPLETED.json", {
        "coordinator_cpu_seconds_excluding_children": time.process_time() - began_cpu,
        "serial_study_wall_seconds": time.perf_counter() - began_wall,
        "unix": time.time(), "protocol_sha256": digest(plan_path)})


def interval(values, plan):
    """Resample independent fitted-seed groups, then paired episodes within each."""
    data = np.asarray(values, float)
    rng = np.random.default_rng(plan["bootstrap_seed"])
    groups = rng.integers(0, len(data), size=(plan["bootstrap_replicates"], len(data)))
    indices = rng.integers(0, data.shape[1], size=(*groups.shape, data.shape[1]))
    draws = data[groups[..., None], indices].mean(axis=(1, 2))
    return {"mean": float(data.mean()), "descriptive_95": np.quantile(draws, [.025, .975]).tolist(),
            "fit_groups": len(data), "paired_episodes": data.size,
            "independence_limitation": "only three independently fitted groups; no population-wide architecture claim"}


def analyze(plan_path):
    plan = json.loads(Path(plan_path).read_text())
    verify_sources(plan)
    base, findings = Path(plan["output"]), {}
    for condition in plan["conditions"]:
        records = {arm: [jsonl(paths(plan, seed, condition, arm)[2] / "episodes.jsonl")
                        for seed in plan["fit_seeds"]] for arm in plan["arms"]}
        metric = lambda arm, key: np.array([[row["summary"][key] for row in group] for group in records[arm]])
        contrasts = {}
        for left, right in (("D", "B"), ("B", "A"), ("D", "C"), ("C", "A"),
                            ("D_current", "D"), ("D_hypothetical", "D"), ("D_both", "D"),
                            ("B_on_D", "D"), ("hold_on_D", "D")):
            contrasts[f"{left}-{right}"] = {key: interval(metric(left, key) - metric(right, key), plan)
                                            for key in ("accuracy", "net_reward", "nll", "brier", "reads")}
        contrasts["interaction"] = interval(metric("D", "net_reward") - metric("C", "net_reward")
                                               - metric("B", "net_reward") + metric("A", "net_reward"), plan)
        divergences = {}
        for arm in ("B", "D_current", "D_hypothetical", "D_both", "B_on_D", "hold_on_D"):
            rows = []
            for reference, changed in zip(records["D"], records[arm], strict=True):
                for left, right in zip(reference, changed, strict=True):
                    left_actions = {r["tick"]: r["executed_action"] for r in left["trace"]}
                    right_actions = {r["tick"]: r["executed_action"] for r in right["trace"]}
                    ticks = sorted(set(left_actions) | set(right_actions))
                    first = next((tick for tick in ticks if left_actions.get(tick) != right_actions.get(tick)), None)
                    rows.append({"fit_seed": left["fit_seed"], "world_seed": left["world_seed"],
                        "first_action_divergence": first,
                        "content_probability_changed": not np.allclose(
                            [r["probabilities"] for r in left["predictions"]],
                            [r["probabilities"] for r in right["predictions"]], atol=1e-8)})
            divergences[arm] = {"action_changed": sum(r["first_action_divergence"] is not None for r in rows),
                "tick0_action_changed": sum(r["first_action_divergence"] == 0 for r in rows),
                "content_changed": sum(r["content_probability_changed"] for r in rows), "episodes": len(rows)}
            write(base / f"D_vs_{arm}_{condition}.json", rows)
        findings[condition] = {"means": {arm: {key: float(metric(arm, key).mean())
            for key in ("accuracy", "net_reward", "nll", "brier", "reads", "arm_wall_seconds", "arm_cpu_seconds")}
            for arm in plan["arms"]}, "contrasts": contrasts, "divergences": divergences}
    receipts = []
    for path in sorted(base.glob("*/receipt.json")):
        receipt = json.loads(path.read_text())
        for name, expected in receipt["output_files_sha256"].items():
            if digest(path.parent / name) != expected:
                raise RuntimeError(f"Output changed after receipt: {path.parent / name}")
        receipts.append({"worker": path.parent.name, **receipt})
    fit_cost = sum(row["cpu_seconds"] for row in receipts if row["worker"].startswith("fit_"))
    costs = {"all_worker_cpu_seconds": sum(row["cpu_seconds"] for row in receipts),
        "ordinary_training_once_cpu_seconds": fit_cost,
        "world_generation_cpu_seconds": sum(row["cpu_seconds"] for row in receipts if row["worker"].startswith("world_")),
        "max_single_worker_rss_kib": max(row["max_rss_kib_linux"] for row in receipts),
        "energy_joules": None, "per_arm": {},
        "cost_interpretation": "separate full-process measurements; scientific workers execute serially; host not isolated",
        "sensor_network_energy": "not physically measured", "training_deployment_horizon": "each fit used across both recorded conditions"}
    for arm in plan["arms"]:
        # Exact worker-name lookup avoids overlapping arm name suffixes.
        chosen = [json.loads((paths(plan, seed, condition, arm)[2] / "receipt.json").read_text())
                  for seed in plan["fit_seeds"] for condition in plan["conditions"]]
        costs["per_arm"][arm] = {"cpu_seconds": sum(r["cpu_seconds"] for r in chosen),
            "wall_seconds": sum(r["wall_seconds"] for r in chosen),
            "max_single_worker_rss_kib": max(r["max_rss_kib_linux"] for r in chosen),
            "independent_deployment_plus_fit_cpu_seconds": sum(r["cpu_seconds"] for r in chosen)
                + (fit_cost if plan["arms"][arm][0] == "ordinary" else 0)}
    result = {"protocol_sha256": digest(plan_path), "findings": findings, "costs": costs,
              "workers": len(receipts), "failed_workers": sum(r["exit_code"] != 0 for r in receipts),
              "production_activation": False, "scope": "controlled renewal mechanism and implementation costs only"}
    write(base / "RESULTS.json", result)
    print(json.dumps({"results": str(base / "RESULTS.json"), "workers": len(receipts),
        "D_minus_B": findings["matched"]["contrasts"]["D-B"]["net_reward"], "costs": costs}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("freeze")
    p.add_argument("--output", required=True)
    p.add_argument("--episodes", type=int, default=128)
    for action in ("execute", "analyze", "worker"):
        p = sub.add_parser(action)
        p.add_argument("--plan", required=True)
        if action == "worker":
            p.add_argument("--kind", choices=("fit", "world", "arm"), required=True)
            p.add_argument("--seed", type=int, required=True)
            p.add_argument("--condition", choices=("matched", "hidden_refractory_mismatch"))
            p.add_argument("--arm", choices=tuple(ARMS))
    args = parser.parse_args()
    if args.command == "freeze":
        if args.episodes < 1:
            raise ValueError("Positive episode count required")
        freeze(args.output, args.episodes)
    elif args.command == "execute":
        execute(args.plan)
    elif args.command == "analyze":
        analyze(args.plan)
    else:
        try:
            worker(args.plan, args.kind, args.seed, args.condition, args.arm)
        except Exception:
            traceback.print_exc()
            raise


if __name__ == "__main__":
    main()
