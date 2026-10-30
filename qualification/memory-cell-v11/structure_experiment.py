"""Execute and audit budgeted topology changes on compiler-backed repair tasks.

Split is compared against equal-presentation continuation, a larger MLP, and
two fixed experts with the identical training-only clustering. Other lifecycle
actions are functional candidates, not claims of a topology advantage. Held
cases are constructed only after validation selection for each seed.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
import torch

from evolution import Action, Budget, Evaluation, EvolutionExecutor, Expert, Network, Prices
from features import Encoder
from maintenance import artifact_identity
from models import FeatureMemory, fit, load, predict, save
from task_experiment import parameter_bytes, softmax, summarize, write
from tasks import ACTIONS, Compiler, dump_tasks, execute_policy, make_tasks


def partition(x, seed):
    rng = np.random.default_rng(seed)
    centers = x[rng.choice(len(x), 2, replace=False)].copy()
    assignment = np.zeros(len(x), dtype=int)
    for _ in range(30):
        assignment = np.argmax(x @ centers.T, axis=1)
        if len(set(assignment)) != 2:
            # Explicit deterministic fallback uses training features, never labels.
            order = np.argsort(x[:, 0])
            assignment[order[:len(x) // 2]] = 0
            assignment[order[len(x) // 2:]] = 1
        centers = np.stack([x[assignment == i].mean(0) for i in range(2)])
        centers /= np.maximum(np.linalg.norm(centers, axis=1, keepdims=True), 1e-12)
    return assignment


class TaskNetwork:
    def __init__(self, encoder, compiler, records, directory):
        self.encoder, self.compiler = encoder, compiler
        self.records = {row["key"]: row for row in records}
        self.directory = Path(directory)
        self.directory.mkdir()
        self.evaluations = 0

    def choose(self, network, text):
        active = {key: expert for key, expert in network.experts.items() if expert.awake}
        if not active:
            return None, {"no_active_cell": True}
        x = self.encoder.encode([text])
        centers, names = [], []
        for name in sorted(active):
            anchors = [self.records[key]["x"] for key, owner in network.routes.items()
                       if owner == name and key in self.records]
            if anchors:
                center = np.mean(anchors, axis=0)
                centers.append(center / max(float(np.linalg.norm(center)), 1e-12))
                names.append(name)
        selected = names[int(np.argmax(np.array(centers) @ x[0]))] if names else sorted(active)[0]
        probabilities = softmax(predict(active[selected].model, x))[0]
        label = int(np.argmax(probabilities))
        return (ACTIONS[label] if label < 4 else None,
                dict(cell_id=selected, probabilities=probabilities.tolist(),
                     routing="cosine to training-feature centroids; no held source IDs or labels"))

    def outcomes(self, network, tasks, *, cache):
        return [execute_policy(task, self.compiler, lambda text, obs: self.choose(network, text),
                               steps=2, use_cache=cache) for task in tasks]

    def evaluate(self, network, tasks):
        outcomes = self.outcomes(network, tasks, cache=True)
        mean = np.mean([row["success"] for row in outcomes])
        credit = {}
        for name, expert in network.experts.items():
            if not expert.awake:
                continue
            ablated = Network({key: value for key, value in network.experts.items() if key != name},
                              dict(network.routes))
            counterfactual = self.outcomes(ablated, tasks, cache=True)
            credit[name] = float(mean - np.mean([row["success"] for row in counterfactual]))
        self.evaluations += 1
        write(self.directory / f"validation-{self.evaluations:04}.json",
              dict(outcomes=outcomes, leave_one_cell_out_credit=credit,
                   note="Same observed compiler outputs may be replayed; wall time is hot-cache validation, not serving latency."))
        return Evaluation(tuple(task.case_id for task in tasks), tuple(float(row["success"]) for row in outcomes),
                          hard_errors=sum(row["status"] == "executed" and not row["success"] for row in outcomes),
                          ablation_credit=credit)


def run_seed(seed, input_root, output, encoder, rustc):
    output.mkdir()
    values = np.load(input_root / str(seed) / "training-matrices.npz")
    rows = json.loads((input_root / str(seed) / "training-observations.json").read_text())
    if len(rows) != len(values["x"]) or not np.array_equal(values["labels"], [row["label"] for row in rows]):
        raise ValueError("training feature/label/source alignment mismatch")
    records = [dict(key=row["source_id"], x=values["x"][i], label=int(values["labels"][i]))
               for i, row in enumerate(rows)]
    assignment = partition(values["x"], seed + 200000)
    write(output / "PARTITION.json", dict(zip([row["key"] for row in records], assignment.tolist(), strict=True)))
    receipts, serial = [], 0

    def train(model, subset, *, deadline, options):
        nonlocal serial
        serial += 1
        steps = int(options.get("steps", 150))
        schedule = np.random.default_rng(seed + serial).integers(0, len(subset), size=(steps, 16))
        np.save(output / f"fit-{serial:03}-schedule.npy", schedule)
        result = fit(model, np.stack([row["x"] for row in subset]),
                     np.eye(5)[[row["label"] for row in subset]], [("multiclass", 5)], schedule,
                     source_ids=[row["key"] for row in subset], label=f"structural-{serial}", deadline=deadline)
        model.memory_source_ids = sorted(set(getattr(model, "memory_source_ids", ())) |
                                         {row["key"] for row in subset})
        result["inherited_and_current_source_ids"] = model.memory_source_ids
        receipts.append(result)
        write(output / f"fit-{serial:03}-receipt.json", result)
        return result

    def save_memory(model, path):
        return save(model, path, metadata={"inherited_and_current_source_ids": model.memory_source_ids,
                                          "scope": "Research weights; route partition is not a clean-fit owner projection."})

    def load_memory(path):
        model = load(path)
        model.memory_source_ids = json.loads((Path(path) / "manifest.json").read_text())["metadata"]["inherited_and_current_source_ids"]
        return model

    def fitted(hidden, subset, steps):
        model = FeatureMemory("mlp", values["x"].shape[1], 5, seed=seed, hidden=hidden)
        receipt = train(model, subset, deadline=time.perf_counter() + 60, options={"steps": steps})
        return model, receipt["wall_seconds"]

    base, base_seconds = fitted(64, records, 300)
    save_memory(base, output / "base")
    base_digest, base_bytes = artifact_identity(output / "base")
    incumbent = Network({"parent": Expert("parent", base, checkpoint=str(output / "base"),
                                           artifact_sha256=base_digest, artifact_bytes=base_bytes)},
                        {row["key"]: "parent" for row in records}, base_seconds)
    continued = load_memory(output / "base")
    continued_receipt = train(continued, records, deadline=time.perf_counter() + 60, options={"steps": 300})
    continuation = Network({"continued": Expert("continued", continued)},
                           {row["key"]: "continued" for row in records}, base_seconds + continued_receipt["wall_seconds"])
    larger, larger_seconds = fitted(128, records, 600)
    capacity = Network({"larger": Expert("larger", larger)}, {row["key"]: "larger" for row in records}, larger_seconds)
    fixed = Network({})
    for index in range(2):
        subset = [row for i, row in enumerate(records) if assignment[i] == index]
        model, seconds = fitted(64, subset, 300)
        name = f"fixed-{index}"
        fixed.experts[name] = Expert(name, model)
        fixed.routes.update({row["key"]: name for row in subset})
        fixed.training_seconds += seconds
    for title, network in (("continued", continuation), ("capacity", capacity), ("fixed", fixed)):
        for name, expert in network.experts.items():
            checkpoint = output / title / name
            save_memory(expert.model, checkpoint)
            expert.checkpoint = str(checkpoint)
            expert.artifact_sha256, expert.artifact_bytes = artifact_identity(checkpoint)
    compiler = Compiler(rustc, output / "compiler-observations")
    evaluator = TaskNetwork(encoder, compiler, records, output / "evaluations")
    validation = make_tasks(seed + 60000, "structure-validation", per_family=3, paired=True, unknown=4)
    train_ids = {row["key"] for row in records}
    validation_ids = {task.source_id for task in validation}
    if train_ids & validation_ids:
        raise ValueError("training and validation source overlap")
    dump_tasks(validation, output / "validation-tasks.json")
    executor = EvolutionExecutor(output / "actions", train_model=train, evaluate_network=evaluator.evaluate,
                                 save_model=save_memory, load_model=load_memory, model_bytes=parameter_bytes,
                                 budget=Budget(max_active_experts=2, max_active_bytes=250000, max_training_seconds=60,
                                               max_transfer_bytes=1000000),
                                 prices=Prices(storage_per_byte=.002 / 1048576,
                                               active_memory_per_byte=.01 / 1048576,
                                               training_per_second=.001, maintenance_per_second=.001,
                                               horizon_queries=1000, minimum_gain=.01, confidence_z=2.576))
    controls = {"fixed_experts": fixed, "capacity": capacity, "continued_parent": continuation}
    split = Action("split", ("parent",), ("child-0", "child-1"),
                   assignments={row["key"]: f"child-{int(assignment[i])}" for i, row in enumerate(records)},
                   options={"steps": 150})
    selected, candidate = executor.execute(split, incumbent, records, validation=validation, controls=controls)
    decisions = {"split": candidate.report}
    proposal_networks = {"split_candidate": candidate.network}
    _, merged = executor.execute(Action("merge", ("fixed-0", "fixed-1"), ("merged",), options={"steps": 300}),
                                 fixed, records, validation=validation, controls={"capacity": capacity})
    decisions["merge"] = merged.report
    _, sleeping = executor.execute(Action("sleep", ("fixed-0",)), fixed, records, validation=validation)
    decisions["sleep"] = sleeping.report
    # Wake is a functional trial from the saved sleeping shadow, irrespective of admission.
    _, waking = executor.execute(Action("wake", ("fixed-0",)), sleeping.network, records, validation=validation)
    decisions["wake"] = waking.report
    _, migrated = executor.execute(Action("migrate", ("parent",), target_host="local-roundtrip"),
                                   incumbent, records, validation=validation)
    decisions["migrate"] = migrated.report
    write(output / "EXPLORATION_COSTS.json", executor.exploration_resources())
    executor.close()
    write(output / "VALIDATION_DECISIONS.json", decisions)
    # This phase is constructed after all structural decisions and never used by a fit/gate.
    held = make_tasks(seed + 70000, "structure-held", per_family=4, paired=True, unknown=4)
    if {task.source_id for task in held} & (train_ids | validation_ids):
        raise ValueError("held source overlap")
    dump_tasks(held, output / "held-tasks.json")
    scores, rewards = {}, {}
    for title, network in {"incumbent": incumbent, "selected": selected, **controls, **proposal_networks}.items():
        calls = compiler.calls
        started = time.perf_counter()
        outcomes = evaluator.outcomes(network, held, cache=False)
        rewards[title] = np.array([row["success"] for row in outcomes], dtype=float)
        scores[title] = dict(summarize(outcomes, held), compiler_calls=compiler.calls - calls,
                             end_to_end_wall_seconds=time.perf_counter() - started,
                             active_weight_bytes=sum(parameter_bytes(e.model) for e in network.experts.values() if e.awake),
                             checkpoint_disk_bytes=sum(artifact_identity(e.checkpoint)[1] for e in network.experts.values()),
                             training_seconds=network.training_seconds, maintenance_seconds=network.maintenance_seconds)
        write(output / ("held-" + title + ".json"), outcomes)
    comparisons = {}
    for name in ("incumbent", "fixed_experts", "capacity", "continued_parent"):
        delta = rewards["split_candidate"] - rewards[name]
        quality_lower = float(delta.mean() - 2.576 * delta.std(ddof=1) / np.sqrt(len(delta)))
        candidate_cost, baseline_cost = scores["split_candidate"], scores[name]
        cost_delta = (.01 * (candidate_cost["active_weight_bytes"] - baseline_cost["active_weight_bytes"]) / 1048576
                      + .002 * (candidate_cost["checkpoint_disk_bytes"] - baseline_cost["checkpoint_disk_bytes"]) / 1048576
                      + .001 * (candidate_cost["training_seconds"] - baseline_cost["training_seconds"]) / 1000
                      + .001 * (candidate_cost["maintenance_seconds"] - baseline_cost["maintenance_seconds"]) / 1000)
        comparisons[name] = dict(quality_gain=float(delta.mean()), approximate_quality_lower_bound=quality_lower,
                                 measured_cost_delta=cost_delta, approximate_lower_net_gain=quality_lower - cost_delta)
    held_confirmation = dict(validation_admitted=candidate.report["admitted"], comparisons=comparisons,
                             confirmed=candidate.report["admitted"] and all(row["approximate_lower_net_gain"] > .01 for row in comparisons.values()),
                             scope="Held confirmation never changes the selected topology or weights.")
    write(output / "HELD_CONFIRMATION.json", held_confirmation)
    write(output / "DISK_COSTS.json", {str(path.relative_to(output)): path.stat().st_size for path in output.rglob("*") if path.is_file()})
    write(output / "RESULTS.json", dict(scores=scores, decisions={k: {"admitted": v["admitted"],
          "rejection_reasons": v["rejection_reasons"]} for k, v in decisions.items()},
          held_confirmation=held_confirmation,
          encoder=encoder.receipt(), compiler_calls=compiler.calls, compiler_cache_hits=compiler.cache_hits,
          lineage="All model-training rows come from the fixed task experiment's training partition only.",
          statistical_scope="Exploratory paired normal bounds on validation; independent held confirmation, three training seeds; no population or multiplicity guarantee."))
    print(json.dumps(dict(seed=seed, scores=scores, admitted={k: v["admitted"] for k, v in decisions.items()})), flush=True)
    return scores, decisions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--encoder", required=True, type=Path)
    parser.add_argument("--rustc", required=True)
    parser.add_argument("--seeds", default="81231,91243,101267")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(2)
    sources = {name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
               for name in ("structure_experiment.py", "evolution.py", "maintenance.py", "models.py", "features.py", "tasks.py", "task_experiment.py")}
    input_files = {str(path.relative_to(args.input)): hashlib.sha256(path.read_bytes()).hexdigest()
                   for seed in args.seeds.split(",") for path in
                   (args.input / seed / "training-matrices.npz", args.input / seed / "training-observations.json")}
    protocol = dict(schema="hepta.memory.v11.structure-protocol.v1", argv=sys.argv, sources=sources, input_files=input_files,
                    seeds=args.seeds, split_budget="300 parent steps + 2 children at 150 = 600 total steps, batch 16",
                    controls="600 continued-parent / larger-model steps; 2 fixed experts at 300 each; same training-only partition",
                    routing="nearest training-feature centroid, no true held address",
                    lineage="Split children retain all parent training sources; partitioned routes do not grant independent clean-fit owner projections.",
                    validation="new two-defect source cases, true compiler outcomes with explicitly shared output cache",
                    held="constructed only after per-seed topology decisions; uncached compiler execution",
                    utility="success rate minus .01 per MiB of active weights, .002 per MiB actual checkpoint storage and amortized observed training/maintenance time; research preference, not monetary estimate",
                    lifecycle_scope="merge/sleep/wake/local migration are executable functional candidates, not matched topology-effect claims",
                    acceptance="split must beat incumbent and all three matched controls at declared lower net gain on validation and repeat on held",
                    budget=dict(active_cells=2, active_weight_bytes=250000, additional_fit_seconds=60, transfer_bytes=1000000),
                    multiplicity="exploratory; no family-wise statistical claim")
    write(args.output / "PROTOCOL.json", protocol)
    encoder = Encoder(args.encoder)
    results = {}
    for seed in map(int, args.seeds.split(",")):
        scores, decisions = run_seed(seed, args.input, args.output / str(seed), encoder, args.rustc)
        results[str(seed)] = dict(scores=scores, admitted={k: v["admitted"] for k, v in decisions.items()})
    changed = [name for name, digest in sources.items() if hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest() != digest]
    if changed:
        raise RuntimeError("source changed during run: " + str(changed))
    if any(hashlib.sha256((args.input / name).read_bytes()).hexdigest() != digest for name, digest in input_files.items()):
        raise RuntimeError("training input bytes changed during run")
    write(args.output / "RESULTS.json", dict(protocol=protocol, results=results, complete=True, acceptance_claim=False))


if __name__ == "__main__":
    main()
