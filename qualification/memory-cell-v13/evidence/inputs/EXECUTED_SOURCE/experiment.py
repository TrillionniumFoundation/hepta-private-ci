"""Executed semantic-skill memory, retained updates and structure comparisons.

All tuning/selection uses the declared calibration split. Held outputs are saved
for every arm after selection. Deterministic executors are shared by all arms;
the learned task is instruction/project binding to an existing operation.
"""

import argparse
import hashlib
import json
from pathlib import Path
import resource
import time

import numpy as np

from adapter import Adapter
from baselines import BM25, Centroid, ExactStore, NearestExample, ProfileExactStore
from prepare_inputs import ROOT, digest, write_json
from structural import SparseExperts, balanced_partition, interference_partition, parameter_count, widen
import tasks


class RidgeClassifier:
    """Strong ordinary linear control on exactly the same pretrained features."""

    def __init__(self, X, y, classes):
        features = np.column_stack([X, np.ones(len(X))]).astype(np.float64)
        targets = np.eye(classes)[y]
        self.weights = features.T @ np.linalg.solve(
            features @ features.T + 0.1 * np.eye(len(X)), targets)

    def predict(self, X):
        return (np.column_stack([X, np.ones(len(X))]) @ self.weights).argmax(axis=1)


def load(inputs, name):
    with np.load(inputs / f"{name}_features.npz", allow_pickle=False) as saved:
        X = saved["X"].copy()
        y = saved["y"].copy() if "y" in saved else None
    rows = json.loads((inputs / f"{name}_rows.json").read_text())
    return X, y, rows


def predict(method, X, rows):
    if hasattr(method, "batch_predict"):
        return method.batch_predict([row["text"] for row in rows], X)
    return [int(value) for value in method.predict(X)]


def evaluate(method, X, rows, destination):
    started, cpu = time.perf_counter(), time.process_time()
    predictions = predict(method, X, rows)
    outcomes = []
    for row, label in zip(rows, predictions):
        if label is None:
            result = {"correct": False, "label_correct": False, "output": None,
                      "error": "unsupported_exact_address", "predicted_skill": None}
        else:
            result = tasks.score_prediction(row, tasks.SKILLS[int(label)])
        outcomes.append({"id": row["id"], "query": row["text"],
                         "expected_skill": row["skill"], "expected_output": row["expected"],
                         "prediction": None if label is None else int(label), **result})
    result = {"evaluated": len(rows), "correct": sum(row["correct"] for row in outcomes),
              "label_correct": sum(row["label_correct"] for row in outcomes),
              "accepted": sum(value is not None for value in predictions),
              "scoring_cpu_seconds": time.process_time() - cpu,
              "scoring_wall_seconds": time.perf_counter() - started,
              "encoder_cost_included": False, "predictions": outcomes}
    write_json(destination, result)
    return {key: value for key, value in result.items() if key != "predictions"}


def controls(X, y, rows):
    return {"exact_store": ExactStore(rows), "bm25": BM25(rows),
            "nearest": NearestExample(rows, X), "centroid": Centroid(rows, X),
            "ridge": RidgeClassifier(X, y, len(tasks.SKILLS))}


def fit(model, X, y, name, source_version, protocol, steps):
    settings = protocol["training"]
    return model.train(X, y, steps=steps, batch_size=settings["batch_size"],
                       lr=settings["learning_rate"], data_id=name,
                       source_version=source_version, allow_data_change=True)


def single_and_structure(seed, directory, datasets, manifest, protocol):
    X, y, rows = datasets["train"]
    XC, _, calibration = datasets["calibration"]
    XT, _, held = datasets["test"]
    source_version = manifest["source_version"]
    parent = Adapter(384, len(tasks.SKILLS), protocol["training"]["rank"], seed,
                     encoder_hash=manifest["encoder_hash"], source_version=source_version)
    before = parent.state_hash()
    initial = fit(parent, X, y, "skills-train", source_version, protocol,
                  protocol["training"]["initial_steps"])
    parent.save(directory / "single.npz")
    training = {"single": initial}
    methods = controls(X, y, rows)
    methods["single"] = parent
    continued = parent.clone()
    training["continue"] = fit(continued, X, y, "skills-train", source_version, protocol,
                              protocol["structure"]["continue_and_widen_steps"])
    methods["continue"] = continued
    wider = widen(parent, protocol["structure"]["groups"])
    training["wide"] = fit(wider, X, y, "skills-train", source_version, protocol,
                          protocol["structure"]["continue_and_widen_steps"])
    methods["wide"] = wider
    partitions = {"fixed": [list(range(start, start + 4)) for start in (0, 4, 8)],
                  "learned": balanced_partition(X, y)}
    partitions["interference"], interference = interference_partition(parent, X, y)
    permutation = np.random.default_rng(seed).permutation(len(tasks.SKILLS))
    partitions["random"] = [list(map(int, group)) for group in np.split(permutation, 3)]
    for name, partition in partitions.items():
        model = SparseExperts(parent, partition, top_k=protocol["structure"]["top_k"])
        training[name] = model.train(
            X, y, steps=protocol["structure"]["expert_steps"],
            batch_size=protocol["training"]["batch_size"],
            lr=protocol["training"]["learning_rate"], data_id="skills-train",
            source_version=source_version)
        methods[name] = model
        model.save(directory / name)
    for name in ("continue", "wide"):
        methods[name].save(directory / f"{name}.npz")
    np.save(directory / "ridge.npy", methods["ridge"].weights, allow_pickle=False)
    counts = {name: parameter_count(model) if isinstance(model, Adapter)
              else model.parameter_count for name, model in methods.items()
              if isinstance(model, (Adapter, SparseExperts))}
    assert parameter_count(wider) == sum(parameter_count(a) for a in methods["fixed"].experts)
    assert training["continue"]["examples"] == training["wide"]["examples"] == training["fixed"]["examples"] == training["learned"]["examples"]
    assert all(training[name]["examples"] == training["continue"]["examples"] for name in partitions)
    validation = {name: evaluate(model, XC, calibration, directory / f"calibration-{name}.json")
                  for name, model in methods.items()}
    # Equal quality keeps the smaller incumbent. No held output is evaluated
    # before this durable selection record is written.
    eligible = ("single", "continue", "wide", "fixed", "random", "learned", "interference")
    selected = min(eligible, key=lambda name: (-validation[name]["correct"], counts[name],
                                              eligible.index(name)))
    selection = {"selected": selected, "validation": validation,
                 "parameter_counts": counts, "partitions": partitions,
                 "test_seen": False, "initial_hash": before, "trained_hash": parent.state_hash(),
                 "training": training, "equal_additional_presentations": training["continue"]["examples"],
                 "same_flops_claim": False, "router_parameters_additional": methods["fixed"].router.size}
    selection["interference_proposal"] = interference
    selection["prospective_value"] = {
        name: {"additional_correct_per_10000_reads_vs_continue":
               10000 * (validation[name]["correct"] - validation["continue"]["correct"]) / len(calibration),
               "extra_train_seconds_vs_continue": training[name]["seconds"] - training["continue"]["seconds"],
               "candidate_proposal_seconds": interference["proposal_seconds"] if name == "interference" else None,
               "candidate_proposal_and_train_seconds": interference["proposal_seconds"] + training[name]["seconds"] if name == "interference" else None,
               "estimated_on": "calibration authored requests",
               "assumption": "future requests have this calibration distribution; not observed future traffic",
               "monetary_net_benefit_claim": False}
        for name in partitions}
    write_json(directory / "SELECTION.json", selection)
    test = {name: evaluate(model, XT, held, directory / f"test-{name}.json")
            for name, model in methods.items()}
    write_json(directory / "STRUCTURE.json", {"selection": selection, "test": test,
               "sparse_call_counts": {name: methods[name].stats for name in partitions},
               "net_benefit_established_by_functional_execution": False})
    return parent, methods, selected, {"selected": selected, "test": test,
                                      "training": training, "parameter_counts": counts}


def compose(method, matrix, cases):
    offset, outputs = 0, []
    for case in cases:
        features = matrix[offset:offset + len(case["steps"])]
        offset += len(case["steps"])
        rows = [{"text": text} for text in case["steps"]]
        labels = iter(predict(method, features, rows))
        def next_skill(_text):
            label = next(labels)
            return tasks.SKILLS[int(label)] if label is not None else "unsupported"
        try:
            result = tasks.execute_composition(case, next_skill)
        except (KeyError, ValueError) as error:
            result = {"correct": False, "error": type(error).__name__}
        outputs.append({"id": case["id"], **result})
    return {"correct": sum(row["correct"] for row in outputs),
            "evaluated": len(outputs), "outputs": outputs,
            "public_step_decomposition": True, "learned_planning_claim": False}


def continual(parent, seed, directory, datasets, manifest, protocol):
    X0, y0, rows0 = datasets["train"]
    XT, _, held0 = datasets["test"]
    models = {"replay": parent.clone(), "no_replay": parent.clone(), "frozen": parent.clone()}
    summaries = []
    for frontier in protocol["updates"]["frontiers"]:
        XP, yP, rowsP = datasets[f"profile-{frontier}-train"]
        XH, _, held = datasets[f"profile-{frontier}-test"]
        X = np.vstack([X0, XP])
        y = np.concatenate([y0, yP])
        current_rows = rows0 + rowsP
        source = digest(current_rows)
        phase = directory / f"frontier-{frontier}"
        phase.mkdir()
        training = {}
        training["replay"] = fit(models["replay"], X, y, f"profile-frontier-{frontier}", source,
                                  protocol, protocol["updates"]["steps_each"])
        training["no_replay"] = fit(models["no_replay"], XP, yP, f"profile-only-{frontier}", source,
                                     protocol, protocol["updates"]["steps_each"])
        test, retention = {}, {}
        for name, model in models.items():
            model.save(phase / f"{name}.npz")
            test[name] = evaluate(model, XH, held, phase / f"profile-{name}.json")
            retention[name] = evaluate(model, XT, held0, phase / f"retention-{name}.json")
        current_controls = controls(X, y, current_rows)
        current_controls["profile_exact"] = ProfileExactStore(tasks.profile_journal(), frontier)
        for name, model in current_controls.items():
            test[name] = evaluate(model, XH, held, phase / f"profile-{name}.json")
        result = {"frontier": frontier, "source_version": source, "training": training,
                  "profile": test, "retention": retention,
                  "no_replay_means_no_original_skill_replay": True,
                  "same_updates_not_same_examples": True,
                  "unlearning_claim": False}
        write_json(phase / "RESULTS.json", result)
        summaries.append(result)
    return summaries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, default=ROOT / "evidence/inputs")
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/run")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    protocol = json.loads((ROOT / "EXPERIMENT_PROTOCOL.json").read_text())
    manifest = json.loads((args.inputs / "encoder_manifest.json").read_text())
    frozen = json.loads((args.inputs / "FREEZE.json").read_text())
    for name, expected in frozen["source_hashes"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Frozen source changed before execution: {name}")
    started, cpu = time.perf_counter(), time.process_time()
    names = list(manifest["split_sizes"])
    datasets = {name: load(args.inputs, name) for name in names}
    matrix, _, compositions = load(args.inputs, "composition")
    hybrid_matrix, _, hybrid_rows = load(args.inputs, "hybrid")
    results = []
    for seed in protocol["seeds"]:
        directory = args.output / f"seed-{seed}"
        directory.mkdir()
        parent, methods, selected, summary = single_and_structure(
            seed, directory, datasets, manifest, protocol)
        composition = {name: compose(methods[name], matrix, compositions)
                       for name in dict.fromkeys(("single", "nearest", "bm25", "ridge", selected))}
        write_json(directory / "COMPOSITION.json", composition)
        hybrid = {name: evaluate(methods[name], hybrid_matrix, hybrid_rows,
                                 directory / f"hybrid-{name}.json")
                  for name in ("single", "nearest", "bm25", "ridge", "fixed")}
        write_json(directory / "HYBRID.json", {"source_reading": True,
                   "pure_parametric_memory_claim": False, "results": hybrid})
        updates = continual(parent, seed, directory, datasets, manifest, protocol)
        results.append({"seed": seed, **summary, "hybrid": hybrid, "composition": {
            name: {k: v for k, v in value.items() if k != "outputs"}
            for name, value in composition.items()}, "updates": updates})
        write_json(args.output / "PROGRESS.json", results)
        print(json.dumps({"seed": seed, "selected": selected,
                          "single_correct": summary["test"]["single"]["correct"],
                          "nearest_correct": summary["test"]["nearest"]["correct"]}), flush=True)
    record = {"schema": "hepta.memory-cell-v13.executed.v1", "results": results,
              "protocol_sha256": hashlib.sha256((ROOT / "EXPERIMENT_PROTOCOL.json").read_bytes()).hexdigest(),
              "source_freeze": frozen, "encoder_manifest": manifest,
              "cpu_seconds": time.process_time() - cpu,
              "wall_seconds": time.perf_counter() - started,
              "peak_rss_kib_linux": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              "three_seeds_are_not_independent_task_sets": True,
              "production_activation": False}
    write_json(args.output / "RESULTS.json", record)
    print(json.dumps({"output": str(args.output), "cpu_seconds": record["cpu_seconds"],
                      "wall_seconds": record["wall_seconds"]}), flush=True)


if __name__ == "__main__":
    main()
