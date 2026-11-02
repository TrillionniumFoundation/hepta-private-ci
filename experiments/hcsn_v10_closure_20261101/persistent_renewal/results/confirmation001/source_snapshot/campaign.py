"""Persistent original-renewal assay with frozen validation-only selection."""

import argparse
import ast
import copy
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .environment import initial_observation, load_physics, packet, reveal, rollout
from .models import Model


HERE = Path(__file__).parent
ROOT = HERE.parents[2]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False); stream.write("\n")


def source_hashes():
    return {name: sha(HERE / name) for name in ("models.py", "environment.py", "campaign.py", "tests.py")}


def prepare(output):
    output.mkdir(parents=True, exist_ok=False)
    snapshot = output / "source_snapshot"
    snapshot.mkdir()
    for name in source_hashes():
        (snapshot / name).write_bytes((HERE / name).read_bytes())
    segments, sources = [], {}
    selected = {
        "experiments/hcsn_mechanism_content_v2/renewal.py": ["Physics", "first_passage_cdf", "integrated_cdf", "renewal_counts", "content_from_counts", "shared_calibration"],
        "experiments/hcsn_mechanism_content_v2/mechanism.py": ["Observation", "Config", "transition_matrix", "generate_path", "predict", "policy_prediction", "choose_action", "make_episode"],
    }
    extraction = {}
    for name, definitions in selected.items():
        text = (ROOT / name).read_text(); sources[name] = sha(ROOT / name)
        tree = ast.parse(text)
        nodes = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        extraction[name] = {}
        for name_in_source in definitions:
            node = nodes[name_in_source]
            start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
            segment = "\n".join(text.splitlines()[start - 1:node.end_lineno]) + "\n"
            segments.append(segment)
            extraction[name][name_in_source] = {"start_line": start, "end_line": node.end_lineno,
                "sha256": hashlib.sha256(segment.encode()).hexdigest()}
    imports = "from dataclasses import asdict, dataclass\nimport math\nimport time\nimport numpy as np\nfrom scipy.integrate import quad\nfrom scipy.special import ndtr, log_ndtr\n\n"
    (snapshot / "physics.py").write_text(imports + "\n\n".join(segments))
    write(snapshot / "EXTRACTION.json", {"baseline_commit": "059b43a0b20ad07654880c155cc49799e0bb8858",
        "method": "Exact AST source segments and explicit NumPy/SciPy imports; no torch shim",
        "source_sha256": sources, "selected_definitions": extraction})
    module = load_physics(output)
    plan = {"schema": "hcsn-v10-persistent-original-renewal.v1", "created_unix": time.time(),
        "source_sha256": source_hashes(), "original_source_sha256": sources,
        "physics_sha256": sha(snapshot / "physics.py"), "extraction_sha256": sha(snapshot / "EXTRACTION.json"),
        "fit_seeds": [100101, 100103, 100107, 100109, 100113],
        "families": ["gru", "ssm", "mlp"], "ordinary_core_families": ["gru", "ssm"],
        "widths": [16, 32], "train_size": 512, "validation_size": 192,
        "training": {"min_epochs": 80, "max_epochs": 320, "patience": 40,
                     "min_delta": .0001, "learning_rate": .006, "batch_size": 128},
        "conditions": ["matched", "hidden_refractory_mismatch"], "worlds_per_condition": 24,
        "world_namespace": [20261101, 100991], "config": asdict(module.Config()),
        "training_read_schedule": "Uniformly choose 0..3 distinct READ-arrival ticks from 1..20; same sampled worlds/masks for all families and widths",
        "training_labels": "Current five-class content at each tick, supervision only; no unobserved x/content supplied to model",
        "selection": "Within family select width/checkpoint using only separate validation NLL; select GRU/SSM ordinary family likewise, retain all candidates",
        "early_stop": "Stop after at least 80 epochs and 40 epochs without validation improvement of 1e-4; max320; exhausted candidates remain unqualified",
        "common_packet": "dt,READ-mask,has-read,last accepted x/rest/content,age,shared estimated nu/sigma/reset/refractory,current time",
        "recurrence": "GRU/SSM state persists across ticks and READs, reset at episode boundary; hypothetical branches clone, never mutate actual view",
        "controls": "Original 4-particle one-planned-READ heuristic and original lightweight threshold; READ delay1,budget3,4 mandatory outputs",
        "exact_no_core": "Reconstruct latest sufficient packet from visible READ history, then exact renewal law; equality tests against persistent analytic",
        "learned_no_core": "MLP uses same latest-packet sufficient information and sampled training labels, no recurrent hidden history",
        "scope": "Original finite synthetic IG first-passage/reset/refractory process and five-class content Markov transitions; no new raw AV",
        "known_law_prior": "Analytic/history know original physical law and transition; ordinary receives same public estimates but learns forecast from samples",
        "real_AV_confirmation": False, "strong_ordinary_qualification": False,
        "architecture_acceptance": False, "device_energy_joules": None,
        "bootstrap": {"replicates": 4000, "seed": 100997, "unit": "Independent fit seeds and independent worlds, not outputs"},
    }
    write(output / "PLAN.json", plan)
    print(json.dumps({"plan": str(output / "PLAN.json"), "sha256": sha(output / "PLAN.json")}), flush=True)


def read_plan(output):
    plan = json.loads((output / "PLAN.json").read_text())
    if source_hashes() != plan["source_sha256"] or sha(output / "source_snapshot/physics.py") != plan["physics_sha256"]:
        raise RuntimeError("Frozen source changed")
    return plan, load_physics(output)


def dataset(seed, size, plan, module):
    config = module.Config(**{**plan["config"], "condition": "matched"})
    rng = np.random.default_rng(np.random.SeedSequence([seed, 101]))
    inputs, labels, schedules, world_seeds = [], [], [], []
    for i in range(size):
        world_seed = int(np.random.SeedSequence([seed, i, 313]).generate_state(1)[0])
        episode = module.make_episode(world_seed, config)
        physics = module.Physics(**episode["calibration"]["estimated"])
        arrivals = set(rng.choice(np.arange(1, config.ticks + 1), size=int(rng.integers(4)), replace=False).tolist())
        obs = initial_observation(episode["initial_x"], config.classes)
        rows, yy, mask = [], [], []
        for tick in range(config.ticks + 1):
            if tick in arrivals:
                obs = reveal(episode, tick, config)
            rows.append(packet(tick * config.dt, 0 if tick == 0 else config.dt, obs, physics, tick in arrivals))
            yy.append(episode["path"]["content"][tick]); mask.append(int(tick in arrivals))
        inputs.append(rows); labels.append(yy); schedules.append(mask); world_seeds.append(world_seed)
    return np.array(inputs), np.array(labels), np.array(schedules), np.array(world_seeds)


def nll(probabilities, labels):
    return float(-np.log(np.take_along_axis(probabilities, labels[..., None], axis=-1)[..., 0] + 1e-12).mean())


def train(output):
    plan, module = read_plan(output)
    dest = output / "fits"; dest.mkdir()
    reports = {}
    for seed in plan["fit_seeds"]:
        start_cpu, start_wall = time.process_time(), time.perf_counter()
        x, y, mask, seeds = dataset(seed, plan["train_size"], plan, module)
        vx, vy, vmask, vseeds = dataset(seed + 70001, plan["validation_size"], plan, module)
        np.savez_compressed(dest / f"data_{seed}.npz", train_x=x, train_y=y, train_mask=mask, train_world_seeds=seeds,
                            validation_x=vx, validation_y=vy, validation_mask=vmask, validation_world_seeds=vseeds)
        report = {"data_generation_cpu_seconds": time.process_time() - start_cpu,
                  "data_generation_wall_seconds": time.perf_counter() - start_wall,
                  "data_sha256": sha(dest / f"data_{seed}.npz"), "families": {}}
        orders = [np.random.default_rng(np.random.SeedSequence([seed, epoch, 711])).permutation(len(x))
                  for epoch in range(plan["training"]["max_epochs"])]
        for family in plan["families"]:
            candidates = []
            for width in plan["widths"]:
                began_cpu, began_wall = time.process_time(), time.perf_counter()
                model = Model(family, seed, width)
                first, second = ({k: np.zeros_like(v) for k, v in model.p.items()} for _ in range(2))
                history, best, significant_best, significant_epoch, best_epoch, step = [], float("inf"), float("inf"), 0, 0, 0
                weights = copy.deepcopy(model.p)
                stopped = False
                for epoch in range(plan["training"]["max_epochs"] + 1):
                    if epoch:
                        for indices in np.array_split(orders[epoch - 1], len(x) // plan["training"]["batch_size"]):
                            _, gradient = model.loss_grad(x[indices], y[indices])
                            norm = np.sqrt(sum(np.sum(g * g) for g in gradient.values()))
                            step += 1
                            for key, value in gradient.items():
                                g = value * min(1, 5 / max(norm, 1e-12))
                                first[key] = .9 * first[key] + .1 * g
                                second[key] = .999 * second[key] + .001 * g * g
                                model.p[key] -= plan["training"]["learning_rate"] * (first[key] / (1 - .9 ** step)) / (np.sqrt(second[key] / (1 - .999 ** step)) + 1e-8)
                    score = nll(model.sequence(vx), vy); history.append(score)
                    if score < best:
                        best, best_epoch, weights = score, epoch, copy.deepcopy(model.p)
                    if score < significant_best - plan["training"]["min_delta"]:
                        significant_best, significant_epoch = score, epoch
                    if epoch >= plan["training"]["min_epochs"] and epoch - significant_epoch >= plan["training"]["patience"]:
                        stopped = True; break
                model.p = weights
                path = dest / f"{family}_{seed}_w{width}.npz"
                np.savez_compressed(path, **weights)
                item = {"family": family, "width": width, "validation_nll": best, "selected_epoch": best_epoch,
                        "epochs_completed": len(history) - 1, "validation_plateau_stop": stopped,
                        "budget_exhausted": not stopped, "validation_nll_history": history,
                        "parameter_count": sum(v.size for v in weights.values()), "checkpoint_sha256": sha(path),
                        "fit_cpu_seconds": time.process_time() - began_cpu, "fit_wall_seconds": time.perf_counter() - began_wall}
                candidates.append(item)
                print(json.dumps({"seed": seed, **{k: item[k] for k in ("family", "width", "validation_nll", "selected_epoch", "epochs_completed", "validation_plateau_stop", "fit_cpu_seconds")}}), flush=True)
            selected = min(candidates, key=lambda c: (c["validation_nll"], c["width"]))
            report["families"][family] = {"selected_width": selected["width"], "validation_nll": selected["validation_nll"], "candidates": candidates}
        report["selected_ordinary_family"] = min(plan["ordinary_core_families"], key=lambda f: (report["families"][f]["validation_nll"], f))
        reports[str(seed)] = report
        write(dest / f"FIT_{seed}.json", report)
    write(output / "FIT.json", reports)
    write(output / "FROZEN_MODELS.json", {"plan_sha256": sha(output / "PLAN.json"), "fit_sha256": sha(output / "FIT.json"),
        "before_test_world_generation": True, "checkpoints": {str(p.relative_to(output)): sha(p) for p in dest.glob("*_w*.npz")},
        "selection": {str(s): {"ordinary_family": reports[str(s)]["selected_ordinary_family"],
            "widths": {f: reports[str(s)]["families"][f]["selected_width"] for f in plan["families"]}} for s in plan["fit_seeds"]}})


def evaluate(output):
    plan, module = read_plan(output)
    reports = json.loads((output / "FIT.json").read_text())
    frozen = json.loads((output / "FROZEN_MODELS.json").read_text())
    if frozen["fit_sha256"] != sha(output / "FIT.json"):
        raise ValueError("Fit selection changed")
    models = {}
    for seed in plan["fit_seeds"]:
        for family in plan["families"]:
            width = reports[str(seed)]["families"][family]["selected_width"]
            path = output / "fits" / f"{family}_{seed}_w{width}.npz"
            if sha(path) != frozen["checkpoints"][str(path.relative_to(output))]:
                raise ValueError("Checkpoint changed")
            model = Model(family, seed, width)
            model.p = dict(np.load(path)); models[(seed, family)] = model
    dest = output / "evaluation"; dest.mkdir()
    indexed, parity = {}, 0.
    with gzip.open(dest / "worlds.jsonl.gz", "xt") as worlds, gzip.open(dest / "runs.jsonl.gz", "xt") as stream:
        for condition_index, condition in enumerate(plan["conditions"]):
            config = module.Config(**{**plan["config"], "condition": condition})
            for index in range(plan["worlds_per_condition"]):
                seed = int(np.random.SeedSequence(plan["world_namespace"] + [condition_index, index]).generate_state(1)[0])
                episode = module.make_episode(seed, config)
                worlds.write(json.dumps({"condition": condition, "world": index, "episode": episode}) + "\n")
                def emit(family, controller, fit_seed=None, model=None):
                    began_cpu, began_wall = time.process_time(), time.perf_counter()
                    result = rollout(episode, config, module, family, controller, model)
                    result.update(condition=condition, world=index, fit_seed=fit_seed,
                        execution_cpu_seconds=time.process_time() - began_cpu, execution_wall_seconds=time.perf_counter() - began_wall)
                    stream.write(json.dumps(result, allow_nan=False) + "\n")
                    indexed[(condition, index, fit_seed, family, controller)] = result
                    return result
                for controller in ("lightweight", "task_value"):
                    analytic, history = emit("analytic", controller), emit("exact_history", controller)
                    for a, b in zip(analytic["trace"], history["trace"]):
                        parity = max(parity, float(np.max(np.abs(np.array(a["probabilities"]) - b["probabilities"]))))
                        if a["action"] != b["action"]:
                            raise AssertionError("Exact-history action differs")
                for fit_seed in plan["fit_seeds"]:
                    for family in plan["families"]:
                        for controller in ("lightweight", "task_value"):
                            emit(family, controller, fit_seed, models[(fit_seed, family)])
                stream.flush(); worlds.flush()
                print(json.dumps({"condition": condition, "world_completed": index + 1}), flush=True)
    result = {"scope": plan["scope"], "real_AV_confirmation": False, "architecture_acceptance": False,
              "strong_ordinary_qualification": False, "runs": len(indexed),
              "worlds": len(plan["conditions"]) * plan["worlds_per_condition"],
              "mandatory_outputs": sum(len(r["predictions"]) for r in indexed.values()),
              "exact_history_probability_max_error": parity, "exact_history_actions_identical": True,
              "conditions": {}, "all_candidates_validation_plateau": all(c["validation_plateau_stop"] for s in reports.values() for f in s["families"].values() for c in f["candidates"]),
              "execution_cpu_seconds_sum": sum(r["execution_cpu_seconds"] for r in indexed.values()),
              "execution_wall_seconds_sum": sum(r["execution_wall_seconds"] for r in indexed.values()),
              "raw_sha256": {str(p.relative_to(output)): sha(p) for p in dest.iterdir()}}
    rng = np.random.default_rng(plan["bootstrap"]["seed"])
    for condition in plan["conditions"]:
        fits, contrasts = {}, {}
        for fit_seed in plan["fit_seeds"]:
            family = reports[str(fit_seed)]["selected_ordinary_family"]
            arms = {label: np.array([indexed[(condition, i, s, f, c)]["summary"]["net_reward"] for i in range(plan["worlds_per_condition"])])
                for label, s, f, c in (("A", fit_seed, family, "lightweight"), ("B", fit_seed, family, "task_value"),
                    ("C", None, "analytic", "lightweight"), ("D", None, "analytic", "task_value"),
                    ("H", None, "exact_history", "task_value"), ("M", fit_seed, "mlp", "task_value"))}
            diffs = {"B-A": arms["B"] - arms["A"], "D-C": arms["D"] - arms["C"], "C-A": arms["C"] - arms["A"],
                     "D-B": arms["D"] - arms["B"], "interaction": arms["D"] - arms["C"] - arms["B"] + arms["A"],
                     "D-H": arms["D"] - arms["H"], "D-M": arms["D"] - arms["M"]}
            fits[str(fit_seed)] = {"ordinary_family": family, "means": {k: float(v.mean()) for k, v in arms.items()},
                                   "contrasts": {k: float(v.mean()) for k, v in diffs.items()}}
            for name, values in diffs.items():
                contrasts.setdefault(name, []).append(values)
        intervals = {}
        for name, values in contrasts.items():
            values = np.array(values); boot = []
            for _ in range(plan["bootstrap"]["replicates"]):
                ii = rng.integers(len(values), size=len(values)); jj = rng.integers(values.shape[1], size=values.shape[1])
                boot.append(float(values[np.ix_(ii, jj)].mean()))
            intervals[name] = {"mean": float(values.mean()), "lower95": float(np.quantile(boot, .025)), "upper95": float(np.quantile(boot, .975))}
        result["conditions"][condition] = {"fits": fits, "contrasts": intervals}
    write(output / "SUMMARY.json", result)
    print(json.dumps({c: x["contrasts"] for c, x in result["conditions"].items()}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "train", "evaluate"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cpu, wall = time.process_time(), time.perf_counter()
    {"prepare": prepare, "train": train, "evaluate": evaluate}[args.command](args.output)
    write(args.output / f"{args.command.upper()}_RUNTIME.json", {"inclusive_cpu_seconds": time.process_time() - cpu,
        "inclusive_wall_seconds": time.perf_counter() - wall, "nested_diagnostics_not_added": True, "energy_joules": None})


if __name__ == "__main__":
    main()
