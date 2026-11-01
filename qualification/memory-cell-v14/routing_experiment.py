"""Freeze, train, select on old calibration, then score the new V14 holdout.

Accept real frozen MiniLM features with checked identities, or build them with
the pinned V13 backend. No synthetic embedding fallback is provided.
"""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import time

import numpy as np

from routing import CalibratedExperts, choose_candidate, crossfit, route_diagnostics


ROOT = Path(__file__).resolve().parent


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n")


def holdout_rows(tasks):
    data = json.loads((ROOT / "routing_holdout.json").read_text())
    rows = []
    if set(data["operations"]) != set(tasks.SKILLS):
        raise ValueError("holdout operation vocabulary changed")
    for label, skill in enumerate(tasks.SKILLS):
        entry = data["operations"][skill]
        if len(entry["queries"]) != 6:
            raise ValueError("holdout requires six requests per operation")
        for number, text in enumerate(entry["queries"]):
            payload, expected = entry["goldens"][number % len(entry["goldens"])]
            rows.append(dict(id=hashlib.sha256(canonical([text, payload])).hexdigest(), text=text,
                             label=label, skill=skill, payload=payload, expected=expected,
                             split="new_held", fixture_id=f"{skill}:{number % len(entry['goldens'])}"))
    for row in data["ood"]:
        rows.append({**row, "id": hashlib.sha256(canonical(row)).hexdigest(), "label": -1,
                     "skill": "unsupported", "expected": None, "split": "new_ood"})
    if len({r["id"] for r in rows}) != len(rows) or len(rows) != 84:
        raise ValueError("duplicate or missing held requests")
    return rows


class Ridge:
    def __init__(self, X, y, classes):
        values = np.column_stack([X, np.ones(len(X))]).astype(np.float64)
        self.weights = values.T @ np.linalg.solve(values @ values.T + 0.1 * np.eye(len(X)), np.eye(classes)[y])

    def predict(self, X):
        return (np.column_stack([X, np.ones(len(X))]) @ self.weights).argmax(axis=1)


def predict(model, X, texts):
    result = model.batch_predict(texts, X) if hasattr(model, "batch_predict") else model.predict(X)
    return np.asarray(result, dtype=np.int64)


def save_model(model, destination):
    destination.mkdir()
    if isinstance(model, CalibratedExperts):
        model.network.save(destination / "network")
        write(destination / "calibration.json", model.calibration.receipt)
        parameters = sum(value.size for expert in model.network.experts for value in expert.params.values())
        parameters += model.network.router.size + model.calibration.theta.size
        arrays = [value for expert in model.network.experts for state in (expert.params, expert.m, expert.v) for value in state.values()]
        arrays += [model.network.router, model.calibration.theta]
    elif hasattr(model, "params"):
        model.save(destination / "model.npz")
        parameters = sum(value.size for value in model.params.values())
        arrays = [value for state in (model.params, model.m, model.v) for value in state.values()]
    else:
        arrays = [value for value in vars(model).values() if isinstance(value, np.ndarray)]
        np.savez_compressed(destination / "arrays.npz", **{k: v for k, v in vars(model).items() if isinstance(v, np.ndarray)})
        write(destination / "metadata.json", {k: v for k, v in vars(model).items() if not isinstance(v, np.ndarray)})
        parameters = int(getattr(model, "weights", np.empty(0)).size)
    return {"parameter_count": int(parameters), "numerical_bytes": int(sum(a.nbytes for a in arrays)),
            "artifact_bytes": sum(p.stat().st_size for p in destination.rglob("*") if p.is_file())}


def evaluate(model, X, rows, accept, tasks):
    predictions, traces, elapsed = [], [], []
    for i, row in enumerate(rows):
        started = time.perf_counter()
        label = int(predict(model, X[i:i + 1], [row["text"]])[0]) if accept[i] else None
        elapsed.append(time.perf_counter() - started)
        predictions.append(-1 if label is None else label)
        outcome = tasks.score_prediction(row, label) if label is not None else dict(output=None, error="abstained", correct=False, label_correct=False)
        if row["label"] < 0:
            outcome["correct"] = label is None
            outcome["label_correct"] = label is None
        traces.append({"id": row["id"], "prediction": label, "accepted": label is not None,
                       "is_ood": row["label"] < 0, "seconds_excluding_encoder": elapsed[-1], **outcome})
    inside = [r for r in traces if not r["is_ood"]]
    outside = [r for r in traces if r["is_ood"]]
    return {"in_domain_correct": sum(r["correct"] for r in inside), "in_domain_total": len(inside),
            "accepted_in_domain": sum(r["accepted"] for r in inside),
            "ood_rejected": sum(not r["accepted"] for r in outside), "ood_total": len(outside),
            "correct_in_domain_per_all_requests": sum(r["correct"] for r in inside) / max(1, len(inside)),
            "wall_seconds_excluding_encoder": sum(elapsed), "p50_seconds_excluding_encoder": float(np.median(elapsed)),
            "p95_seconds_excluding_encoder": float(np.quantile(elapsed, .95)), "traces": traces}, np.array(predictions)


def prepare(args, output, tasks):
    source_names = ["routing.py", "routing_experiment.py", "routing_tests.py", "routing_holdout.json", "ROUTING_PROTOCOL.json"]
    v13_names = ["adapter.py", "structural.py", "baselines.py", "tasks.py", "task_fixtures.json", "backend.py", "download_model.py"]
    files = [ROOT / name for name in source_names] + [args.v13_dir / name for name in v13_names]
    frozen = {str(p): sha(p) for p in files}
    copied = output / "EXECUTED_SOURCE"
    copied.mkdir()
    for p in files:
        (copied / ("v13-" + p.name if p.parent == args.v13_dir else p.name)).write_bytes(p.read_bytes())
    input_hashes = {} if args.inputs is None else {p.name: sha(p) for p in args.inputs.iterdir() if p.is_file()}
    write(output / "FREEZE.json", {"source_hashes": frozen, "input_file_hashes": input_hashes, "created_unix_seconds": time.time(),
          "packages": {name: importlib.metadata.version(name) for name in ("numpy", "scipy")}})
    held = holdout_rows(tasks)
    datasets, encoder = {}, None
    if args.model_dir:
        from backend import FrozenEncoder
        encoder = FrozenEncoder(args.model_dir, threads=1)
    if args.inputs:
        inventory_path = args.inputs / "INVENTORY.json"
        if inventory_path.exists():
            inventory = json.loads(inventory_path.read_text())
            for name in ("encoder_manifest.json", "train_rows.json", "train_features.npz", "calibration_rows.json", "calibration_features.npz"):
                if inventory[name]["sha256"] != sha(args.inputs / name):
                    raise ValueError("cached feature/source inventory mismatch")
        manifest = json.loads((args.inputs / "encoder_manifest.json").read_text())
        if encoder is not None and encoder.manifest_hash != manifest["encoder_hash"]:
            raise ValueError("cached and live encoder identities differ; rebuild all features without --inputs")
        for name in ("train", "calibration"):
            rows = json.loads((args.inputs / f"{name}_rows.json").read_text())
            if rows != tasks.load_split(name):
                raise ValueError("cached rows differ from the frozen original V13 split")
            with np.load(args.inputs / f"{name}_features.npz", allow_pickle=False) as cache:
                X = cache["X"].copy()
                if not np.array_equal(cache["y"], [r["label"] for r in rows]):
                    raise ValueError("cached label identity mismatch")
            datasets[name] = (X, rows)
    elif encoder is not None:
        for name in ("train", "calibration"):
            rows = tasks.load_split(name)
            datasets[name] = (encoder.encode([r["text"] for r in rows]), rows)
        manifest = {"encoder_hash": encoder.manifest_hash, "encoder": encoder.manifest}
    else:
        raise ValueError("provide --model-dir or a complete real-feature --inputs directory")
    if encoder is not None:
        held_X = encoder.encode([r["text"] for r in held])
    else:
        identity = json.loads((args.inputs / "routing_holdout_manifest.json").read_text())
        if identity["holdout_sha256"] != sha(ROOT / "routing_holdout.json") or identity["encoder_hash"] != manifest["encoder_hash"]:
            raise ValueError("held feature identity mismatch")
        path = args.inputs / "routing_holdout_features.npz"
        if identity["feature_sha256"] != sha(path):
            raise ValueError("held feature bytes changed")
        with np.load(path, allow_pickle=False) as cache:
            held_X = cache["X"].copy()
    for name, (X, rows) in {**datasets, "routing_holdout": (held_X, held)}.items():
        if X.shape != (len(rows), 384) or not np.isfinite(X).all():
            raise ValueError("invalid real encoder features")
        np.savez_compressed(output / f"{name}_features.npz", X=X, y=np.array([r["label"] for r in rows]))
        write(output / f"{name}_rows.json", rows)
    if len(datasets["train"][1]) != 120 or len(datasets["calibration"][1]) != 48:
        raise ValueError("V13 train/calibration row counts changed")
    manifest["source_version"] = hashlib.sha256(canonical(datasets["train"][1])).hexdigest()
    manifest["actual_encoder_statistics"] = None if encoder is None else encoder.stats
    manifest["cached_features_no_current_encoder_measurement"] = encoder is None
    write(output / "encoder_manifest.json", manifest)
    write(output / "routing_holdout_manifest.json", {"holdout_sha256": sha(ROOT / "routing_holdout.json"),
          "encoder_hash": manifest["encoder_hash"], "feature_sha256": sha(output / "routing_holdout_features.npz")})
    write(output / "INPUT_IDENTITIES.json", {p.name: sha(p) for p in output.iterdir() if p.is_file()})
    return datasets, held_X, held, manifest


def run_seed(seed, output, datasets, held_X, held, manifest, protocol, tasks):
    from adapter import Adapter
    from baselines import BM25, Centroid, NearestExample
    from structural import SparseExperts, interference_partition, widen
    X, rows = datasets["train"]
    XC, calibration = datasets["calibration"]
    y, yc = np.array([r["label"] for r in rows]), np.array([r["label"] for r in calibration])
    settings = protocol["training"]
    ledger, methods, selection_predictions = {}, {}, {}

    def fit(model, steps, name):
        ledger[name] = model.train(X, y, steps=steps, batch_size=settings["batch_size"], lr=settings["learning_rate"],
                                  data_id="v14-original-skills", source_version=manifest["source_version"], allow_data_change=True)
        methods[name] = model

    parent = Adapter(384, 12, settings["rank"], seed, manifest["encoder_hash"], manifest["source_version"])
    fit(parent, settings["initial_steps"], "single")
    fit(parent.clone(), settings["continuation_steps"], "continue")
    fit(widen(parent, 3), settings["continuation_steps"], "wide")
    fit(parent.clone(), settings["continuation_steps"], "merge_retrain")
    for name, factory in {"ridge": lambda: Ridge(X, y, 12), "centroid": lambda: Centroid(rows, X),
                          "nearest": lambda: NearestExample(rows, X), "bm25": lambda: BM25(rows)}.items():
        started = time.perf_counter()
        methods[name] = factory()
        ledger[name] = {"seconds": time.perf_counter() - started}
    partitions = {"fixed": [list(range(i, i + 4)) for i in (0, 4, 8)],
                  "random": [part.tolist() for part in np.split(np.random.default_rng(seed).permutation(12), 3)]}
    partitions["gradient"], ledger["gradient_partition_search"] = interference_partition(parent, X, y)
    for name, partition in partitions.items():
        network = SparseExperts(parent, partition, top_k=2)
        ledger[name] = network.train(X, y, steps=settings["expert_steps"], batch_size=settings["batch_size"],
                                    lr=settings["learning_rate"], data_id="v14-original-skills", source_version=manifest["source_version"])
        methods[name + "_raw"] = CalibratedExperts(network)
        calibrated, oof, receipts = crossfit(network, XC, yc)
        methods[name + "_calibrated"] = calibrated
        selection_predictions[name + "_calibrated"] = oof
        ledger[name + "_calibration"] = receipts
    costs, scores = {}, {}
    for name, model in methods.items():
        costs[name] = save_model(model, output / name)
        predictions = selection_predictions.get(name)
        if predictions is None:
            predictions = predict(model, XC, [r["text"] for r in calibration])
        selection_predictions[name] = predictions.tolist()
        scores[name] = sum(tasks.score_prediction(row, int(label))["correct"] for row, label in zip(calibration, predictions))
    chosen = choose_candidate(scores, {name: value["numerical_bytes"] for name, value in costs.items()})
    write(output / "SELECTION.json", {"selected": chosen, "scores": scores, "predictions": selection_predictions,
          "all_strong_controls_eligible": True, "new_holdout_scored": False, "calibration_is_small": True})
    normalized = X / np.linalg.norm(X, axis=1, keepdims=True)
    similarity = lambda values: ((values / np.linalg.norm(values, axis=1, keepdims=True)) @ normalized.T).max(axis=1)
    threshold = float(np.quantile(similarity(XC), .05))
    started = time.perf_counter()
    accepted = similarity(held_X) >= threshold
    novelty_gate_seconds = time.perf_counter() - started
    results = {}
    for name, model in methods.items():
        unrestricted, predictions = evaluate(model, held_X, held, np.ones(len(held), dtype=bool), tasks)
        selective, _ = evaluate(model, held_X, held, accepted, tasks)
        results[name] = {"unrestricted": unrestricted, "selective": selective}
        if isinstance(model, CalibratedExperts):
            results[name]["routing_diagnostic"] = route_diagnostics(model, held_X[:72], [r["label"] for r in held[:72]], predictions[:72])
            results[name]["serving_invocations"] = model.stats
    paired = {}
    for name, result in results.items():
        left = result["unrestricted"]["traces"][:72]
        paired[name] = {}
        for baseline in ("continue", "ridge", "centroid"):
            right = results[baseline]["unrestricted"]["traces"][:72]
            paired[name][baseline] = {"candidate_only_correct": sum(a["correct"] and not b["correct"] for a, b in zip(left, right)),
                                      "baseline_only_correct": sum(b["correct"] and not a["correct"] for a, b in zip(left, right))}
    report = {"seed": seed, "selected": chosen, "models": results, "costs": costs, "training_and_exploration": ledger,
              "paired_held": paired, "novelty_gate_seconds": novelty_gate_seconds,
              "novelty_cosine_threshold": threshold, "held_used_for_selection": False,
              "complete_cost_advantage_demonstrated": False, "unmeasured_costs": protocol["costs"]["unmeasured"]}
    write(output / "RESULTS.json", report)
    return {"seed": seed, "selected": chosen, "held_correct": {k: v["unrestricted"]["in_domain_correct"] for k, v in results.items()},
            "selective_correct": {k: v["selective"]["in_domain_correct"] for k, v in results.items()},
            "ood_rejected": int((~accepted[72:]).sum()), "novelty_gate_accepted_id": int(accepted[:72].sum())}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--v13-dir", type=Path, default=ROOT.parent / "memory-cell-v13")
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    args.v13_dir = args.v13_dir.resolve()
    sys.path.insert(0, str(args.v13_dir))
    import tasks
    args.output.mkdir(parents=True, exist_ok=False)
    protocol = json.loads((ROOT / "ROUTING_PROTOCOL.json").read_text())
    prepared = prepare(args, args.output, tasks)
    if args.prepare_only:
        return
    results = []
    for seed in protocol["seed"]:
        directory = args.output / f"seed-{seed}"
        directory.mkdir()
        results.append(run_seed(seed, directory, *prepared, protocol, tasks))
    write(args.output / "SUMMARY.json", {"seeds": results, "independent_held_language_requests": 72,
          "not_a_production_claim": True, "algorithm_learning_claim": False})
    print(json.dumps({"output": str(args.output), "results": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
