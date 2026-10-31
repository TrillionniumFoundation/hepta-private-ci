"""Separate development, frozen preparation and new paired confirmation stages."""

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
import scipy
from scipy.stats import t as student_t

from . import finite
from .finite import ACTIONS, COMPUTE, EVENT, task
from .frozen import FrozenR7
from .head import CalibratedHead, fit


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
UPSTREAM = REPO / "experiments/analytic_event_neuron/round7"
MODES = ("first_passage", "clocked", "direct")
SEEDS = (11, 12, 13, 14, 15)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, record):
    Path(path).write_text(json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n")


def source_manifest():
    paths = list(HERE.glob("*.py")) + [UPSTREAM / p for p in ("task.py", "oracle.py")]
    return {str(p.relative_to(REPO)): digest(p) for p in paths}


def checkpoint(mode, seed):
    return UPSTREAM / "evidence/fits_primary" / f"{mode}_none_{seed}.json"


def metrics(q, target, graph):
    mask = np.broadcast_to(graph["legal"][:, None], q.shape)
    error = q[mask] - target[mask]
    actions = np.where(mask, q, -np.inf).argmax(-1)
    regret = target.max(-1) - np.take_along_axis(target, actions[..., None], -1)[..., 0]
    return {"q_rmse": float(np.sqrt(np.mean(error ** 2))),
        "q_max_abs_error": float(np.max(abs(error))), "mean_action_regret_all_states": float(regret.mean()),
        "max_action_regret_all_states": float(regret.max())}, actions


def prepare(output, iterations, development=False):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    start, cpu = time.perf_counter(), time.process_time()
    configs = finite.configurations()
    graph = finite.build_graph(configs)
    independent = finite.build_graph(configs, independent=True)
    alignment = np.array([independent["ids"][s] for s in graph["states"]])
    counts = {p: sum(s.parameters == p for s in graph["states"]) for p in configs}
    weights = np.array([1 / (len(configs) * counts[s.parameters]) for s in graph["states"]])
    protocol = {"schema": "hepta.round8.value-calibration.protocol.v1",
        "upstream_commit": "1bbf9712140ec388f7fb7967fa7b22244386441d",
        "modes": list(MODES if not development else MODES[:1]),
        "core_seeds": list(SEEDS if not development else SEEDS[:1]),
        "head_seed_offset": 92000, "hidden": 32, "iteration_cap": iterations,
        "training_domain": "complete finite public/latent graph for eight known nominal contracts",
        "confirmation": {"episodes_per_contract_fit": 128, "seed_start": 83100000,
            "heldout_parameter_regimes": ["nominal", "drift", "missing", "cost_shift"],
            "primary_regime": "nominal", "primary_contrasts": "new minus old within each of three fixed cell families",
            "primary_interval": "five paired fit means, Student-t, Bonferroni 98.333333%",
            "primary_compute_price_cpu": 1., "primary_training_amortization_sessions": 10000,
            "cpu_price_sensitivity": [0., .1, 1., 10.],
            "deployment_sessions_sensitivity": [128, 1000, 10000, 100000],
            "quality_noninferiority_margin": .02},
        "training_method": "supervised finite-model Q-star distillation, exact STOP anchor, direct and action-gap MSE",
        "not_claimed": ["model-free Q learning", "fresh joint cell training", "continuum QVI",
            "new unseen-state nominal generalization", "production activation"]}
    write(output / "PROTOCOL.json", protocol)
    write(output / "STATE_GRAPH.json", {"states": [s.to_dict() for s in graph["states"]],
        "starts": graph["starts"], "legal": graph["legal"].tolist(),
        "sunk_total_cost_canonicalized_to_zero": True})
    upstream_report = json.loads((UPSTREAM / "evidence/JOINT_OPTIMAL_DIAGNOSTIC.json").read_text())
    reference_rows = {(r["mode"], r["seed"]): r for r in upstream_report["checkpoints"]}
    setup_cpu = time.process_time() - cpu
    development_records = []
    if not development:
        for prior in sorted(output.parent.glob("development*/PREPARE.json")):
            prior_report = json.loads(prior.read_text())
            development_records.append({"path": str(prior),
                "sha256": digest(prior), "cpu_seconds": prior_report["cpu_seconds"]})
    development_cpu = sum(row["cpu_seconds"] for row in development_records)
    records = []
    for mode in protocol["modes"]:
        for seed in protocol["core_seeds"]:
            item_start = time.process_time()
            model = FrozenR7(checkpoint(mode, seed))
            matrix, events = model.kernels(graph["x"])
            target, optimal_value = finite.targets(graph, matrix, events)
            old_q = model.old_q(graph["x"])
            before, old_actions = metrics(old_q, target, graph)
            _, old_value = finite.targets(graph, matrix, events, old_actions)
            joined = model.inputs(graph["x"])
            head, training = fit(joined, target, graph["legal"], weights, seed + 92000,
                hidden=protocol["hidden"], iterations=iterations)
            path = output / f"{mode}_{seed}.json"
            head.save(path, training)
            reloaded = CalibratedHead.load(path)
            q = reloaded.predict(joined, target[:, :, 3])
            after, actions = metrics(q, target, graph)
            _, new_value = finite.targets(graph, matrix, events, actions)
            # Independent process law and recursive evaluator, not training DP.
            imatrix, ievents = model.kernels(independent["x"])
            reference_optimal = finite.reference(independent, imatrix, ievents)
            iactions = np.empty_like(actions)
            iactions[alignment] = actions
            reference_new = finite.reference(independent, imatrix, ievents, iactions)
            reference_error = max(float(abs(reference_optimal[alignment] - optimal_value).max()),
                float(abs(reference_new[alignment] - new_value).max()))
            old_record = reference_rows[mode, seed]
            historical_error = float(abs(old_value[graph["starts"], model.n // 2] -
                np.array([r["greedy_bellman_registered_return"] for r in old_record["per_configuration"]])).max())
            if reference_error > 1e-10 or historical_error > 1e-9:
                raise AssertionError(("independent/upstream executor mismatch", reference_error, historical_error))
            np.savez_compressed(output / f"{mode}_{seed}_tables.npz", target_q=target,
                old_q=old_q, new_q=q, old_actions=old_actions, new_actions=actions,
                old_value=old_value, new_value=new_value, optimal_value=optimal_value)
            diagnostics = []
            for c, i in enumerate(graph["starts"]):
                reach = matrix[i, model.n // 2] > 1e-12
                diagnostics.append({"contract": c, "old_actions_reachable": sorted({ACTIONS[a] for a in old_actions[i, reach]}),
                    "new_actions_reachable": sorted({ACTIONS[a] for a in actions[i, reach]}),
                    "optimal_actions_reachable": sorted({ACTIONS[a] for a in target[i, reach].argmax(-1)}),
                    "optimal_value": float(optimal_value[i, model.n // 2]),
                    "old_value": float(old_value[i, model.n // 2]), "new_value": float(new_value[i, model.n // 2])})
            record = {"mode": mode, "seed": seed, "checkpoint_sha256": model.sha256,
                "head_file": path.name, "head_sha256": digest(path), "before": before, "after": after,
                "training": training, "per_contract_initial": diagnostics,
                "old_exact_mean": float(old_value[graph["starts"], model.n // 2].mean()),
                "new_exact_mean": float(new_value[graph["starts"], model.n // 2].mean()),
                "optimal_exact_mean": float(optimal_value[graph["starts"], model.n // 2].mean()),
                "independent_value_max_error": reference_error, "historical_executor_max_error": historical_error,
                "prepare_inclusive_cpu_seconds": time.process_time() - item_start,
                "standalone_new_preparation_cpu_seconds": time.process_time() - item_start + setup_cpu + development_cpu}
            records.append(record)
            print(json.dumps({"mode": mode, "seed": seed, "before": before, "after": after,
                "old_return": record["old_exact_mean"], "new_return": record["new_exact_mean"],
                "preset4": diagnostics[4], "preset6": diagnostics[6]}), flush=True)
    report = {"status": "development" if development else "prepared", "protocol": protocol,
        "public_state_count": len(graph["states"]), "fits": records,
        "cpu_seconds": time.process_time() - cpu, "wall_seconds": time.perf_counter() - start,
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__},
        "common_setup_cpu_seconds": setup_cpu, "development_records": development_records,
        "development_cpu_seconds": development_cpu,
        "cost_scope": "Incremental new-versus-frozen comparison: original R7 training is common sunk work; primary charges each hypothetical standalone new head all common setup, its fit/certification/export and all recorded development attempts. Campaign totals count shared work only once.",
        "confirmation_episodes_created": 0}
    write(output / "PREPARE.json", report)
    frozen = {"source": source_manifest(), "files": {p.name: digest(p) for p in output.iterdir() if p.is_file()},
        "upstream_checkpoints": {str(checkpoint(m, s).relative_to(REPO)): digest(checkpoint(m, s))
            for m in protocol["modes"] for s in protocol["core_seeds"]}}
    write(output / "FREEZE.json", frozen)
    return report


def episode_run(model, head, episode, latent_seed):
    cpu = time.process_time_ns()
    state, latent, calls, reward, events = task.initial_state(episode), model.n // 2, 0, 0., 0
    records = []
    while not state.terminated:
        x = task.features(state)
        content, drive = model.encode(x)
        matrix, _ = model.transition(drive[0])
        previous = latent
        uniform = int.from_bytes(hashlib.sha256(f"r8/value/{latent_seed}/{calls}".encode()).digest()[:8], "big") / 2**64
        row = np.clip(matrix[latent], 0, None)
        row /= row.sum()
        latent = min(model.states - 1, int(np.searchsorted(row.cumsum(), uniform, side="right")))
        new_event = int(previous < model.n <= latent)
        joined = np.r_[x, content[0], model.basis[latent]]
        if head is None:
            h = np.tanh(joined @ model.w["readout.0.weight"].T + model.w["readout.0.bias"])
            q = (h @ model.w["readout.2.weight"].T + model.w["readout.2.bias"])[4:]
        else:
            q = head.predict(joined, np.asarray(abs(2 * state.posterior - 1) - x[16] - COMPUTE))
        allowed = [a in task.legal_actions(state) for a in ACTIONS]
        action = ACTIONS[int(np.where(allowed, q, -np.inf).argmax())]
        result = task.step(state, action, episode)
        records.append({"state": state.to_dict(), "latent_before": previous, "latent_after": latent,
            "q": q.tolist(), "action": action, "reward": result.reward,
            "cost": result.cost, "event": new_event, "guard_fallback": result.info["guard_fallback"]})
        reward += result.reward
        events += new_event
        state = result.state
        calls += 1
    return {"task_return": reward, "utility": reward - COMPUTE * calls - EVENT * events,
        "correct": int(state.answer == episode.truth), "decisions": calls, "events": events,
        "cpu_seconds": (time.process_time_ns() - cpu) / 1e9, "steps": records}


def confirm(prepared, output, freeze_reference):
    prepared, output = prepared.resolve(), output.resolve()
    frozen = json.loads((prepared / "FREEZE.json").read_text())
    if source_manifest() != frozen["source"]:
        raise ValueError("source changed after freeze")
    for relative, sha in frozen["upstream_checkpoints"].items():
        if digest(REPO / relative) != sha:
            raise ValueError("upstream checkpoint changed")
    for name, sha in frozen["files"].items():
        if digest(prepared / name) != sha:
            raise ValueError("prepared bytes changed")
    output.mkdir(parents=True, exist_ok=False)
    report = json.loads((prepared / "PREPARE.json").read_text())
    design = report["protocol"]["confirmation"]
    write(output / "START.json", {"freeze_sha256": digest(prepared / "FREEZE.json"),
        "freeze_reference": freeze_reference, "time_utc": datetime.now(timezone.utc).isoformat()})
    started, cpu = time.perf_counter(), time.process_time()
    summaries, fits = [], []
    with gzip.open(output / "RAW.jsonl.gz", "wt", compresslevel=6) as stream:
        for item in report["fits"]:
            mode, seed = item["mode"], item["seed"]
            model = FrozenR7(checkpoint(mode, seed))
            head = CalibratedHead.load(prepared / item["head_file"])
            for r, regime in enumerate(design["heldout_parameter_regimes"]):
                rows = []
                for c, config in enumerate(finite.configurations(regime)):
                    for n in range(design["episodes_per_contract_fit"]):
                        key = design["seed_start"] + (seed - 11) * 100000 + r * 10000 + c * 1000 + n
                        episode = task.generate_episode(key, config)
                        runs = {}
                        for label in (("old", "new") if key % 2 else ("new", "old")):
                            runs[label] = episode_run(model, head if label == "new" else None, episode, key + 10000000)
                        raw = {"mode": mode, "seed": seed, "regime": regime, "contract": c,
                            "episode_seed": key, "runs": runs}
                        stream.write(json.dumps(raw, separators=(",", ":"), allow_nan=False) + "\n")
                        row = {k: runs["new"][k] - runs["old"][k]
                            for k in ("utility", "task_return", "correct", "cpu_seconds", "decisions", "events")}
                        row["net_utility"] = row["utility"] - design["primary_compute_price_cpu"] * (
                            row["cpu_seconds"] + item["standalone_new_preparation_cpu_seconds"] /
                            design["primary_training_amortization_sessions"])
                        rows.append(row)
                fits.append({"mode": mode, "seed": seed, "regime": regime,
                    "new_preparation_cpu_seconds": item["standalone_new_preparation_cpu_seconds"],
                    "pairs": len(rows), "differences": {k: float(np.mean([x[k] for x in rows])) for k in rows[0]}})
                print(json.dumps(fits[-1]), flush=True)
    for regime in design["heldout_parameter_regimes"]:
        for mode in report["protocol"]["modes"]:
            selected = [r for r in fits if r["mode"] == mode and r["regime"] == regime]
            stats = {}
            for key in selected[0]["differences"]:
                values = np.array([r["differences"][key] for r in selected])
                half = student_t.ppf(1 - .05 / 6, len(values) - 1) * values.std(ddof=1) / np.sqrt(len(values))
                stats[key] = {"mean": float(values.mean()), "interval": [float(values.mean() - half), float(values.mean() + half)]}
            summaries.append({"mode": mode, "regime": regime, "fits": len(selected), "paired_effects": stats})
            sensitivity = []
            for price in design["cpu_price_sensitivity"]:
                for sessions in design["deployment_sessions_sensitivity"]:
                    values = np.array([r["differences"]["utility"] - price *
                        (r["differences"]["cpu_seconds"] + r["new_preparation_cpu_seconds"] / sessions) for r in selected])
                    half = student_t.ppf(1 - .05 / 6, len(values) - 1) * values.std(ddof=1) / np.sqrt(len(values))
                    sensitivity.append({"cpu_price": price, "deployment_sessions": sessions,
                        "mean": float(values.mean()), "interval": [float(values.mean() - half), float(values.mean() + half)]})
            summaries[-1]["cost_sensitivity"] = sensitivity
    result = {"status": "complete", "freeze_reference": freeze_reference,
        "freeze_sha256": digest(prepared / "FREEZE.json"), "fits": fits, "summaries": summaries,
        "raw_sha256": digest(output / "RAW.jsonl.gz"), "cpu_seconds": time.process_time() - cpu,
        "wall_seconds": time.perf_counter() - started, "source_unchanged": source_manifest() == frozen["source"],
        "production_activation": False, "interpretation": "paired execution on the unchanged finite evidence task; nominal model states were available during training"}
    write(output / "SUMMARY.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("develop", "prepare", "confirm"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepared", type=Path)
    parser.add_argument("--iterations", type=int, default=600)
    parser.add_argument("--freeze-reference")
    args = parser.parse_args()
    if args.stage == "confirm":
        if not args.prepared or not args.freeze_reference:
            parser.error("confirmation requires prepared bytes and an immutable freeze reference")
        confirm(args.prepared, args.output, args.freeze_reference)
    else:
        prepare(args.output, args.iterations, development=args.stage == "develop")


if __name__ == "__main__":
    main()
