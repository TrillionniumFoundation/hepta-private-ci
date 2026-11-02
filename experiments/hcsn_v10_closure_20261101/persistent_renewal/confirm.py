"""Fixed-size posthoc-designed independent confirmation, frozen models only."""

import argparse
import gzip
import json
from pathlib import Path
import shutil
import time

import numpy as np

from .campaign import read_plan, sha, source_hashes, write
from .environment import rollout
from .models import Model


HERE = Path(__file__).parent


def prepare(base, output):
    original, _ = read_plan(base)
    frozen = json.loads((base / "FROZEN_MODELS.json").read_text())
    fit = json.loads((base / "FIT.json").read_text())
    output.mkdir(parents=True, exist_ok=False)
    snapshot = output / "source_snapshot"; snapshot.mkdir()
    for name in [*source_hashes(), "confirm.py", "extend.py"]:
        shutil.copy2(HERE / name, snapshot / name)
    shutil.copy2(base / "source_snapshot/physics.py", snapshot / "physics.py")
    excluded, exclusion_sources = set(), {}
    for seed in original["fit_seeds"]:
        path = base / "fits" / f"data_{seed}.npz"
        data = np.load(path)
        excluded.update(map(int, data["train_world_seeds"])); excluded.update(map(int, data["validation_world_seeds"]))
        exclusion_sources[str(path)] = sha(path)
    for directory in [base.parent / "development002", base]:
        path = directory / "evaluation/worlds.jsonl.gz"
        with gzip.open(path, "rt") as stream:
            excluded.update(int(json.loads(line)["episode"]["seed"]) for line in stream)
        exclusion_sources[str(path)] = sha(path)
    namespace = [20261101, 102997]
    worlds = []
    for condition_index, condition in enumerate(original["conditions"]):
        for shard in range(8):
            for local_index in range(24):
                retry = 0
                seed = int(np.random.SeedSequence(namespace + [condition_index, shard, local_index, retry]).generate_state(1)[0])
                while seed in excluded:
                    retry += 1
                    seed = int(np.random.SeedSequence(namespace + [condition_index, shard, local_index, retry]).generate_state(1)[0])
                excluded.add(seed)
                worlds.append({"condition": condition, "shard": shard, "local_index": local_index,
                    "world": shard * 24 + local_index, "world_seed": seed, "collision_retry": retry})
    write(output / "WORLD_SEEDS.json", worlds)
    protocol = {"schema": "hcsn-v10-fixed-independent-confirmation.v1", "created_unix": time.time(),
        "design_role": "Posthoc-designed fixed independent confirmation motivated by prior wide confidence intervals; not initial preregistration",
        "base_directory": str(base.resolve()), "base_directory_repo_relative": str(base.resolve().relative_to(HERE.parents[2])),
        "base_plan_sha256": sha(base / "PLAN.json"),
        "base_fit_sha256": sha(base / "FIT.json"), "base_frozen_models_sha256": sha(base / "FROZEN_MODELS.json"),
        "model_selection": frozen["selection"], "all_checkpoints": frozen["checkpoints"],
        "models_retrained": False, "selection_changed": False, "source_sha256": source_hashes(),
        "confirmation_source_sha256": sha(HERE / "confirm.py"), "physics_sha256": original["physics_sha256"],
        "world_seed_sha256": sha(output / "WORLD_SEEDS.json"), "exclusion_source_sha256": exclusion_sources,
        "world_namespace": namespace, "worlds_per_condition": 192, "total_worlds": 384,
        "shards": 8, "worlds_per_condition_per_shard": 24, "max_concurrent_shards": 6,
        "fixed_stopping": "Execute all eight shards; no interim outcome-dependent stop or further sample extension",
        "conditions": original["conditions"], "config": original["config"], "fit_seeds": original["fit_seeds"],
        "families": original["families"], "ordinary_core_families": original["ordinary_core_families"],
        "primary_condition": "matched", "primary_comparisons": ["D-B", "D-M"],
        "primary_interval": "Two-sided 97.5% crossed world-by-fit percentile-bootstrap intervals for each of two comparisons; Bonferroni family-wise 95% descriptive coverage target",
        "primary_positive_rule": "For each stated positive comparison require its adjusted lower interval endpoint >0; joint superiority requires both",
        "secondary_condition": "hidden_refractory_mismatch", "secondary_intervals": "Two-sided95%, descriptive",
        "bootstrap": {"replicates": 10000, "seed": 103003, "crossed_units": "Resample independent worlds and five fit seeds; all arms paired on same worlds"},
        "scope": original["scope"], "limitations": ["finite original perfect-READ synthetic task", "known-law analytic prior", "finite family/width search is not global strong-model certification", "READ-fee utility excludes CPU monetization", "H still uses analytic operator"],
        "real_AV_confirmation": False, "architecture_acceptance": False, "device_energy_joules": None}
    write(output / "CONFIRMATION_PLAN.json", protocol)
    print(json.dumps({"plan_sha256": sha(output / "CONFIRMATION_PLAN.json"), "worlds": len(worlds), "shards": 8}), flush=True)


def read_confirmation(output):
    protocol = json.loads((output / "CONFIRMATION_PLAN.json").read_text())
    if sha(HERE / "confirm.py") != protocol["confirmation_source_sha256"] or source_hashes() != protocol["source_sha256"]:
        raise ValueError("Confirmation scientific source changed")
    if sha(output / "WORLD_SEEDS.json") != protocol["world_seed_sha256"]:
        raise ValueError("World assignments changed")
    base = Path(protocol["base_directory"])
    if not base.is_dir():
        base = HERE.parents[2] / protocol["base_directory_repo_relative"]
    original, module = read_plan(base)
    if sha(base / "FIT.json") != protocol["base_fit_sha256"] or sha(base / "FROZEN_MODELS.json") != protocol["base_frozen_models_sha256"]:
        raise ValueError("Model selection changed")
    return protocol, original, module, base


def shard(output, number):
    protocol, original, module, base = read_confirmation(output)
    if number not in range(protocol["shards"]):
        raise ValueError("Invalid shard")
    dest = output / f"shard_{number:02d}"; dest.mkdir()
    models = {}
    for seed in protocol["fit_seeds"]:
        for family in protocol["families"]:
            width = protocol["model_selection"][str(seed)]["widths"][family]
            name = f"fits/{family}_{seed}_w{width}.npz"
            if sha(base / name) != protocol["all_checkpoints"][name]:
                raise ValueError("Checkpoint changed")
            model = Model(family, seed, width); model.p = dict(np.load(base / name)); models[(seed, family)] = model
    assignments = [w for w in json.loads((output / "WORLD_SEEDS.json").read_text()) if w["shard"] == number]
    began_cpu, began_wall = time.process_time(), time.perf_counter()
    count = 0
    with gzip.open(dest / "worlds.jsonl.gz", "xt") as worlds, gzip.open(dest / "runs.jsonl.gz", "xt") as stream:
        for assignment in assignments:
            condition = assignment["condition"]
            config = module.Config(**{**original["config"], "condition": condition})
            episode = module.make_episode(assignment["world_seed"], config)
            worlds.write(json.dumps({**assignment, "episode": episode}) + "\n")
            def emit(family, controller, fit_seed=None, model=None):
                nonlocal count
                result = rollout(episode, config, module, family, controller, model)
                result.update(condition=condition, world=assignment["world"], fit_seed=fit_seed, shard=number)
                stream.write(json.dumps(result, allow_nan=False) + "\n"); count += 1
            for family in ("analytic", "exact_history"):
                for controller in ("lightweight", "task_value"):
                    emit(family, controller)
            for seed in protocol["fit_seeds"]:
                for family in protocol["families"]:
                    for controller in ("lightweight", "task_value"):
                        emit(family, controller, seed, models[(seed, family)])
            stream.flush(); worlds.flush()
            print(json.dumps({"shard": number, "condition": condition, "local_index": assignment["local_index"]}), flush=True)
    write(dest / "COMPLETE.json", {"shard": number, "worlds": len(assignments), "runs": count,
        "plan_sha256": sha(output / "CONFIRMATION_PLAN.json"), "world_seed_sha256": protocol["world_seed_sha256"],
        "raw_sha256": {name: sha(dest / name) for name in ("worlds.jsonl.gz", "runs.jsonl.gz")},
        "inclusive_cpu_seconds": time.process_time() - began_cpu, "inclusive_wall_seconds": time.perf_counter() - began_wall})


def aggregate(output):
    protocol, _, _, base = read_confirmation(output)
    indexed, world_seeds, receipts, parity, tick_count, outputs = {}, set(), [], 0., 0, 0
    for number in range(protocol["shards"]):
        dest = output / f"shard_{number:02d}"
        receipt = json.loads((dest / "COMPLETE.json").read_text())
        if receipt["plan_sha256"] != sha(output / "CONFIRMATION_PLAN.json") or receipt["worlds"] != 48:
            raise ValueError("Shard identity or scope changed")
        for name, digest in receipt["raw_sha256"].items():
            if sha(dest / name) != digest:
                raise ValueError("Raw shard changed")
        with gzip.open(dest / "worlds.jsonl.gz", "rt") as stream:
            for line in stream:
                record = json.loads(line)
                if record["episode"]["seed"] in world_seeds:
                    raise ValueError("Repeated world")
                world_seeds.add(record["episode"]["seed"])
        with gzip.open(dest / "runs.jsonl.gz", "rt") as stream:
            for line in stream:
                record = json.loads(line)
                key = (record["condition"], record["world"], record["fit_seed"], record["family"], record["controller"])
                if key in indexed:
                    raise ValueError("Repeated run")
                indexed[key] = {"net_reward": record["summary"]["net_reward"],
                    "probabilities": [r["probabilities"] for r in record["trace"]] if record["family"] in ("analytic", "exact_history") else None,
                    "actions": [r["action"] for r in record["trace"]] if record["family"] in ("analytic", "exact_history") else None}
                tick_count += len(record["trace"]); outputs += len(record["predictions"])
        receipts.append({"shard": number, "complete_sha256": sha(dest / "COMPLETE.json"), **receipt})
    if len(world_seeds) != protocol["total_worlds"] or len(indexed) != protocol["total_worlds"] * 34:
        raise ValueError("Fixed confirmation incomplete")
    rng = np.random.default_rng(protocol["bootstrap"]["seed"])
    result = {"schema": "hcsn-v10-fixed-confirmation-summary.v1", "design_role": protocol["design_role"],
        "scope": protocol["scope"], "worlds": len(world_seeds), "runs": len(indexed), "tick_states": tick_count,
        "mandatory_outputs": outputs, "all_eight_shards_completed": True, "conditions": {},
        "real_AV_confirmation": False, "architecture_acceptance": False, "strong_ordinary_qualification": False}
    paired_arrays = {}
    for condition in protocol["conditions"]:
        values, fits = {}, {}
        for seed in protocol["fit_seeds"]:
            family = protocol["model_selection"][str(seed)]["ordinary_family"]
            arms = {label: np.array([indexed[(condition, i, s, f, c)]["net_reward"] for i in range(192)])
                for label, s, f, c in (("A", seed, family, "lightweight"), ("B", seed, family, "task_value"),
                    ("C", None, "analytic", "lightweight"), ("D", None, "analytic", "task_value"),
                    ("H", None, "exact_history", "task_value"), ("M", seed, "mlp", "task_value"))}
            contrasts = {"D-B": arms["D"] - arms["B"], "D-M": arms["D"] - arms["M"],
                "B-A": arms["B"] - arms["A"], "D-C": arms["D"] - arms["C"], "C-A": arms["C"] - arms["A"],
                "interaction": arms["D"] - arms["C"] - arms["B"] + arms["A"], "D-H": arms["D"] - arms["H"],
                "B-M": arms["B"] - arms["M"]}
            for name, vector in contrasts.items(): values.setdefault(name, []).append(vector)
            fits[str(seed)] = {"ordinary_family": family, "means": {k: float(v.mean()) for k, v in arms.items()},
                              "contrasts": {k: float(v.mean()) for k, v in contrasts.items()}}
        intervals = {}
        for name, vectors in values.items():
            array = np.array(vectors); paired_arrays[condition + "__" + name] = array
            bootstrap = []
            for _ in range(protocol["bootstrap"]["replicates"]):
                ii = rng.integers(5, size=5); jj = rng.integers(192, size=192)
                bootstrap.append(float(array[np.ix_(ii, jj)].mean()))
            primary = condition == protocol["primary_condition"] and name in protocol["primary_comparisons"]
            quantiles = [.0125, .9875] if primary else [.025, .975]
            low, high = np.quantile(bootstrap, quantiles)
            intervals[name] = {"mean": float(array.mean()), "lower": float(low), "upper": float(high),
                "confidence_level": .975 if primary else .95, "primary": primary,
                "positive_at_declared_threshold": bool(low > 0)}
        result["conditions"][condition] = {"fits": fits, "contrasts": intervals}
        for index in range(192):
            for controller in ("lightweight", "task_value"):
                analytic, history = (indexed[(condition, index, None, f, controller)] for f in ("analytic", "exact_history"))
                if analytic["actions"] != history["actions"]:
                    raise AssertionError("History actions differ")
                parity = max(parity, float(np.max(np.abs(np.array(analytic["probabilities"]) - history["probabilities"]))))
    result["exact_history_probability_max_error"] = parity
    result["exact_history_actions_identical"] = True
    result["both_matched_primary_comparisons_positive"] = all(result["conditions"]["matched"]["contrasts"][k]["positive_at_declared_threshold"] for k in protocol["primary_comparisons"])
    np.savez_compressed(output / "PAIRED_CONTRASTS.npz", **paired_arrays)
    write(output / "SHARD_MANIFEST.json", receipts)
    result["paired_sha256"], result["shard_manifest_sha256"] = sha(output / "PAIRED_CONTRASTS.npz"), sha(output / "SHARD_MANIFEST.json")
    write(output / "SUMMARY.json", result)
    print(json.dumps({c: r["contrasts"] for c, r in result["conditions"].items()}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "shard", "aggregate"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base", type=Path)
    parser.add_argument("--shard", type=int)
    args = parser.parse_args()
    cpu, wall = time.process_time(), time.perf_counter()
    if args.command == "prepare": prepare(args.base, args.output)
    elif args.command == "shard": shard(args.output, args.shard)
    else: aggregate(args.output)
    destination = args.output / (f"shard_{args.shard:02d}" if args.command == "shard" else "")
    write(destination / f"{args.command.upper()}_RUNTIME.json", {"inclusive_cpu_seconds": time.process_time() - cpu,
        "inclusive_wall_seconds": time.perf_counter() - wall, "nested_diagnostics_not_added": True, "energy_joules": None})


if __name__ == "__main__":
    main()
