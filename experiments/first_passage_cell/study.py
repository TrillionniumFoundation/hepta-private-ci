"""Registered physics/policy preparation and separately frozen evaluation.

All development grid outcomes are retained. Confirmation generation is behind
an explicit source, preparation, protocol and native binary identity gate.
"""

import argparse
import copy
import gzip
import json
from pathlib import Path
import time

import numpy as np

from .cell import canonical_bytes
from .ndu import NativeNduPort
from .study_io import (HERE, PROTOCOL, REPO, GzipLedger, atomic_json, compact_native,
                       digest_file, file_record, model_from_file, read_json,
                       resolved_path, verify_freeze, verify_records)
from .task import MaintenanceTask, scenarios, task_contract
from .training import (fit_cell, generate_renewal_data, objective_and_gradient,
                       save_dataset)
from .value import BIAS_GRID, THRESHOLD_GRID, select_action

ARMS = ("ordinary_first_event", "endogenous_renewal", "learned_threshold7",
        "fixed_shared6", "fixed_cross7", "always_wait", "always_repair", "stop")
POLICIES = dict(zip(ARMS, ("ordinary", "endogenous", "learned_threshold",
                         "fixed_shared6", "fixed7", "always_wait", "always_repair", "always_stop")))
PRIMARY = ARMS[:3]
TASK_FIELDS = ("task_profile", "scenario_id", "observation", "action", "outcome",
               "interventions", "running_reward", "failure_cost", "action_cost",
               "reward", "cumulative_reward", "done")
METRIC_FIELDS = ("decision_wall_seconds", "decision_cpu_seconds", "simulation_wall_seconds",
                "realized_native_wall_seconds", "native_calls", "forecast_requests",
                "forecast_cache_hits", "decisions")


def run_episode(seed, phase, arm, scenario, parameters, model_path, native,
                policy_parameter=0.0, cache=None, retain_full=False):
    """The simulator owns true physics; the policy receives only public state."""
    if arm not in ARMS:
        raise ValueError("Unregistered policy arm")
    task = MaintenanceTask(scenario)
    initial = task.checkpoint()
    model_sha = digest_file(model_path)
    bias = float(policy_parameter) if arm in PRIMARY[:2] else 0.0
    threshold = float(policy_parameter) if arm == "learned_threshold7" else 0.35
    metrics = {name: 0 for name in METRIC_FIELDS}
    calls_before = native.calls
    records = []
    for _ in range(4):
        observation = task.observation()
        checkpoint = task.checkpoint()
        context = {"phase": phase, "seed": int(seed), "scenario_id": scenario["identity"],
                   "arm": arm, "model_checkpoint_digest": model_sha,
                   "task_checkpoint_digest": checkpoint["sha256"],
                   "decision_index": task.index}
        old_cache = 0 if cache is None else len(cache)
        wall, cpu = time.perf_counter(), time.process_time()
        decision = select_action(parameters, observation, POLICIES[arm], bias=bias,
                                 threshold=threshold, native=native, context=context,
                                 forecast_cache=cache)
        metrics["decision_wall_seconds"] += time.perf_counter() - wall
        metrics["decision_cpu_seconds"] += time.process_time() - cpu
        if decision["values"] is not None:
            metrics["forecast_requests"] += 1
            metrics["forecast_cache_hits"] += int(cache is not None and len(cache) == old_cache)
        wall = time.perf_counter()
        record = dict(task.step(decision["action"].lower()))
        metrics["simulation_wall_seconds"] += time.perf_counter() - wall
        metrics["decisions"] += 1
        record["decision"] = dict(decision)
        record["decision"]["native_receipt"] = compact_native(decision["native_receipt"], retain_full)
        record["decision"]["native_action_order"] = (None if decision["values"] is None
                                                       else list(decision["values"]["actions"]))
        if retain_full:
            record["checkpoint_before"] = checkpoint
            record["checkpoint_after"] = task.checkpoint()
        records.append(record)
        if task.done:
            break
    context = {"phase": phase, "seed": int(seed), "scenario_id": scenario["identity"],
               "arm": arm, "model_checkpoint_digest": model_sha,
               "task_checkpoint_digest": initial["sha256"], "evaluation": "realized"}
    wall = time.perf_counter()
    realized = native.evaluate_realized(parameters, records[0]["observation"], task.ledger,
                                        context=context)
    metrics["realized_native_wall_seconds"] = time.perf_counter() - wall
    metrics["native_calls"] = native.calls - calls_before
    return {"schema": "HeptaFirstPassageEpisodeV2", "seed": int(seed), "phase": phase,
            "arm": arm, "scenario": scenario, "model_digest": parameters.digest(),
            "model_file": file_record(model_path)["path"], "model_checkpoint_digest": model_sha,
            "initial_task_checkpoint_digest": initial["sha256"],
            "policy_bias": bias, "policy_threshold": threshold if arm == "learned_threshold7" else None,
            "active_physical_parameters": 7 if arm == "fixed_cross7" else 6,
            "active_policy_parameters": 1 if arm in PRIMARY else 0,
            "records": records, "total_reward": task.total_reward,
            "realized_native_return": realized["realized_native_return"],
            "realized_native_receipt": compact_native(realized, retain_full),
            "runtime": metrics, "retained_full_receipts": bool(retain_full),
            "cost_metadata": {"active_rate": 0.6, "failure_penalty": 0.5,
                              "repair_cost": task.cost, "bias_is_cost": False,
                              "units": "registered_task_units_not_currency"}}


def prepare_physics(prepared, seeds):
    protocol = read_json(PROTOCOL)
    for seed in seeds:
        folder = prepared / str(seed)
        folder.mkdir(parents=True, exist_ok=True)
        training = generate_renewal_data(seed, protocol["data"]["training_trajectories_per_seed"], "training")
        development = generate_renewal_data(seed, protocol["data"]["development_trajectories_per_seed"], "development")
        train_sha = save_dataset(training, folder / "training.npz")
        dev_sha = save_dataset(development, folder / "likelihood_development.npz")
        for count in (6, 7):
            _, receipt = fit_cell(seed, training, interaction=count == 7)
            loss, gradient = objective_and_gradient(receipt["selected_vector"], development)
            receipt.update({"heldout_loss": loss, "heldout_gradient_norm": float(np.linalg.norm(gradient)),
                            "training_file_sha256": train_sha, "development_file_sha256": dev_sha,
                            "protocol_sha256": digest_file(PROTOCOL)})
            atomic_json(folder / f"model{count}.json", receipt)
        print(json.dumps({"stage": "physics", "seed": seed, "complete": True}), flush=True)


def prepare_policy_seed(prepared, seed, native):
    protocol = read_json(PROTOCOL)
    folder = prepared / str(seed)
    model_path = folder / "model6.json"
    parameters, _ = model_from_file(model_path)
    totals = {arm: np.zeros(17) for arm in PRIMARY}
    actual_totals = {arm: np.zeros(17) for arm in PRIMARY}
    runtimes = {arm: {key: 0 for key in METRIC_FIELDS} for arm in PRIMARY}
    runtime_sources = [file_record(HERE / name) for name in
                       ("cell.py", "kernels.py", "task.py", "training.py", "value.py",
                        "ndu.py", "study.py", "study_io.py")]
    native_binary_sha = digest_file(native.binary)
    count = protocol["data"]["policy_development_episodes_per_seed"]
    dataset = scenarios(seed, count, "policy_development")
    grids = {arm: THRESHOLD_GRID if arm == "learned_threshold7" else BIAS_GRID for arm in PRIMARY}
    ledger_path = folder / "policy_development.jsonl.gz"
    with GzipLedger(ledger_path) as ledger:
        for index, scenario in enumerate(dataset):
            caches = {arm: {} for arm in PRIMARY}
            for arm in PRIMARY:
                for grid_index, parameter in enumerate(grids[arm]):
                    episode = run_episode(seed, "policy_development", arm, scenario, parameters,
                                          model_path, native, float(parameter), caches[arm],
                                          retain_full=index == 0)
                    episode["policy_grid_index"] = grid_index
                    ledger.append(episode)
                    totals[arm][grid_index] += episode["realized_native_return"]
                    actual_totals[arm][grid_index] += episode["total_reward"]
                    for key in METRIC_FIELDS:
                        runtimes[arm][key] += episode["runtime"][key]
            if (index + 1) % 16 == 0:
                print(json.dumps({"stage": "policy", "seed": seed, "scenarios": index + 1,
                                  "episodes": ledger.episodes, "native_calls": native.calls}), flush=True)
    verify_records(runtime_sources)
    if digest_file(native.binary) != native_binary_sha or native_binary_sha != native.binary_sha256:
        raise ValueError("Native implementation changed during policy preparation")
    selected = {}
    for arm in PRIMARY:
        means = totals[arm] / count
        best = int(np.argmax(means))
        selected[arm] = {"parameter_kind": "distance_threshold" if arm == "learned_threshold7" else "repair_gap_bias",
                         "parameter_grid": grids[arm].tolist(), "selected_index": best,
                         "selected_parameter": float(grids[arm][best]),
                         "native_mean_returns": means.tolist(),
                         "actual_mean_returns": (actual_totals[arm] / count).tolist(),
                         "episodes_per_grid_point": count, "runtime": runtimes[arm]}
    result = {"schema": "HeptaFirstPassagePolicySelectionV2", "seed": seed,
              "phase": "policy_development", "protocol_sha256": digest_file(PROTOCOL),
              "model_digest": parameters.digest(), "model_file_sha256": digest_file(model_path),
              "selection_rule": "maximum mean original native signed-Q32 realized return; first grid-index tie",
              "native_binary_sha256": native.binary_sha256,
              "native_source_manifest_sha256": native.source_manifest_sha256,
              "ledger": file_record(ledger_path), "selected": selected,
              "full_receipt_sample_rule": "first scenario, all three arms and every grid value",
              "retained_all_outcomes": True, "runtime_sources": runtime_sources,
              "forecast_cache_scope": "per scenario and per arm; reused only among its development grid values"}
    atomic_json(folder / "policy_selection.json", result)
    return result


def validate_preparation(prepared, native):
    protocol = read_json(PROTOCOL)
    for seed in protocol["seeds"]:
        for count in (6, 7):
            parameters, receipt = model_from_file(prepared / str(seed) / f"model{count}.json")
            if receipt["active_parameter_count"] != count or receipt["seed"] != seed:
                raise ValueError("Physical model budget mismatch")
        selected = read_json(prepared / str(seed) / "policy_selection.json")
        model6, model_receipt = model_from_file(prepared / str(seed) / "model6.json")
        if (selected["seed"] != seed or selected["phase"] != "policy_development"
                or selected["model_digest"] != model6.digest()
                or selected["model_file_sha256"] != digest_file(prepared / str(seed) / "model6.json")
                or selected["protocol_sha256"] != digest_file(PROTOCOL)
                or selected["native_binary_sha256"] != native.binary_sha256
                or selected["native_source_manifest_sha256"] != native.source_manifest_sha256):
            raise ValueError("Policy-selection identity mismatch")
        if set(selected["selected"]) != set(PRIMARY):
            raise ValueError("Missing or unknown development policy family")
        for arm, item in selected["selected"].items():
            expected_grid = THRESHOLD_GRID if arm == "learned_threshold7" else BIAS_GRID
            means = np.asarray(item["native_mean_returns"], dtype=float)
            index = item["selected_index"]
            if (item["parameter_grid"] != expected_grid.tolist() or means.shape != (17,)
                    or not np.isfinite(means).all() or type(index) is not int
                    or index != int(np.argmax(means))
                    or item["selected_parameter"] != float(expected_grid[index])
                    or item["episodes_per_grid_point"] != protocol["data"]["policy_development_episodes_per_seed"]):
                raise ValueError("Policy grid, budget or canonical argmax mismatch")
        verify_records([selected["ledger"], *selected["runtime_sources"]])
        for count in (6, 7):
            receipt = read_json(prepared / str(seed) / f"model{count}.json")
            if (receipt["training_file_sha256"] != digest_file(prepared / str(seed) / "training.npz")
                    or receipt["development_file_sha256"] != digest_file(prepared / str(seed) / "likelihood_development.npz")):
                raise ValueError("Training/development dataset identity mismatch")


def finalize_preparation(prepared, native):
    validate_preparation(prepared, native)
    protocol = read_json(PROTOCOL)
    files = sorted(p for p in prepared.rglob("*") if p.is_file())
    if any(p.name.endswith(".incomplete") for p in files):
        raise ValueError("Incomplete preparation artifact retained; refusing finalization")
    manifest = {"schema": "HeptaFirstPassagePreparedV2", "protocol_sha256": digest_file(PROTOCOL),
                "seeds": protocol["seeds"], "native_binary_sha256": native.binary_sha256,
                "native_source_manifest_sha256": native.source_manifest_sha256,
                "task_contract": task_contract(), "files": [file_record(p) for p in files]}
    atomic_json(prepared / "prepared_manifest.json", manifest)
    return manifest


def run_frozen(prepared, output, freeze_path, native, phase):
    if phase not in {"confirmation", "stress_drift", "stress_diffusion"}:
        raise ValueError("Unregistered confirmation/stress phase")
    frozen = verify_freeze(freeze_path, prepared, native)
    validate_preparation(prepared, native)
    protocol = read_json(PROTOCOL)
    count = protocol["data"]["confirmation_episodes_per_seed" if phase == "confirmation" else "stress_episodes_per_seed"]
    summary, output_files = {}, []
    for seed in protocol["seeds"]:
        folder = prepared / str(seed)
        paths = {6: folder / "model6.json", 7: folder / "model7.json"}
        models = {n: model_from_file(path)[0] for n, path in paths.items()}
        selection = read_json(folder / "policy_selection.json")["selected"]
        path = output / phase / f"{seed}.jsonl.gz"
        with GzipLedger(path) as ledger:
            for index, scenario in enumerate(scenarios(seed, count, phase)):
                for arm in ARMS:
                    n = 7 if arm == "fixed_cross7" else 6
                    parameter = selection[arm]["selected_parameter"] if arm in PRIMARY else 0.0
                    episode = run_episode(seed, phase, arm, scenario, models[n], paths[n], native,
                                          parameter, {}, retain_full=index == 0)
                    ledger.append(episode)
                    item = summary.setdefault(arm, {"episodes": 0, "return_sum": 0.0,
                                                    **{key: 0 for key in METRIC_FIELDS}})
                    item["episodes"] += 1
                    item["return_sum"] += episode["total_reward"]
                    for key in METRIC_FIELDS:
                        item[key] += episode["runtime"][key]
                if (index + 1) % 32 == 0:
                    print(json.dumps({"stage": phase, "seed": seed, "scenarios": index + 1,
                                      "native_calls": native.calls}), flush=True)
        output_files.append(file_record(path))
    verify_freeze(freeze_path, prepared, native)
    receipt = {"schema": "HeptaFirstPassageRunV2", "phase": phase,
               "freeze_sha256": digest_file(freeze_path), "source_commit": frozen["source_commit"],
               "protocol_sha256": digest_file(PROTOCOL), "native_binary_sha256": native.binary_sha256,
               "native_source_manifest_sha256": native.source_manifest_sha256,
               "files": output_files, "arms": summary,
               "full_receipt_sample_rule": "first scenario per seed, every arm",
               "forecast_cache_scope": "fresh per arm and scenario; no cross-arm timing subsidy",
               "cost_scope": "actual task costs; compute wall time and Python-process CPU time reported separately",
               "plan_scope": "WAIT_AFTER_CURRENT forecasts; deployed MPC_REPLAN_EACH_HALF"}
    atomic_json(output / f"{phase}_run.json", receipt)
    return receipt


def replay_episode(path, line_index, native):
    """Reconstruct every compact native receipt from retained factual inputs."""
    with gzip.open(path, "rt") as stream:
        episode = next(json.loads(line) for i, line in enumerate(stream) if i == line_index)
    parameters, _ = model_from_file(resolved_path(episode["model_file"]))
    if digest_file(resolved_path(episode["model_file"])) != episode["model_checkpoint_digest"]:
        raise ValueError("Replay model checkpoint mismatch")
    checks = 0
    for row in episode["records"]:
        decision = row["decision"]
        original = decision["native_receipt"]
        if original is None:
            continue
        values = dict(decision["values"])
        values["actions"] = {name: decision["values"]["actions"][name]
                             for name in decision["native_action_order"]}
        reconstructed = native.evaluate_forecast(parameters, row["observation"], values,
                                                  policy=decision["policy"], bias=decision["bias"],
                                                  context=original["context"])
        expected = {key: value for key, value in original.items() if key != "full_receipt"}
        if compact_native(reconstructed) != expected:
            raise ValueError("Compact forecast native replay mismatch")
        checks += 1
    original = episode["realized_native_receipt"]
    transitions = [{key: row[key] for key in TASK_FIELDS} for row in episode["records"]]
    reconstructed = native.evaluate_realized(parameters, transitions[0]["observation"], transitions,
                                              context=original["context"])
    if compact_native(reconstructed) != {k: v for k, v in original.items() if k != "full_receipt"}:
        raise ValueError("Compact realized native replay mismatch")
    return {"schema": "HeptaFirstPassageNativeReplayV1", "episode_file": str(path),
            "episode_file_sha256": digest_file(path), "line_index": line_index,
            "forecast_receipts_replayed": checks, "realized_receipt_replayed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "replay"))
    parser.add_argument("--prepared", type=Path, default=HERE / "prepared")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--stage", choices=("physics", "policy", "all", "finalize"), default="all")
    parser.add_argument("--seed", type=int, action="append", help="Repeat for independent preparation seeds")
    parser.add_argument("--native-manifest", type=Path)
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--phase", choices=("confirmation", "stress_drift", "stress_diffusion"), default="confirmation")
    parser.add_argument("--episode-file", type=Path)
    parser.add_argument("--line-index", type=int, default=0)
    args = parser.parse_args()
    protocol = read_json(PROTOCOL)
    seeds = args.seed if args.seed is not None else protocol["seeds"]
    if len(seeds) != len(set(seeds)):
        parser.error("Duplicate model seed")
    if any(seed not in protocol["seeds"] for seed in seeds):
        parser.error("Unregistered model seed")
    if args.command == "prepare" and args.stage in {"physics", "all"}:
        prepare_physics(args.prepared, seeds)
    if args.command == "prepare" and args.stage == "physics":
        return
    if args.native_manifest is None:
        parser.error("Original native build manifest is required")
    native = NativeNduPort(args.native_manifest)
    if args.command == "prepare":
        if args.stage in {"policy", "all"}:
            for seed in seeds:
                prepare_policy_seed(args.prepared, seed, native)
        if args.seed is None or args.stage == "finalize":
            finalize_preparation(args.prepared, native)
    elif args.command == "run":
        if args.freeze is None or args.output is None:
            parser.error("Confirmation/stress requires --freeze and --output")
        run_frozen(args.prepared, args.output, args.freeze, native, args.phase)
    else:
        if args.episode_file is None:
            parser.error("Replay requires --episode-file")
        print(json.dumps(replay_episode(args.episode_file, args.line_index, native), sort_keys=True))


if __name__ == "__main__":
    main()
