"""Fit and select bilingual V6 routers without reading any held evaluation data."""

import argparse
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import time

import numpy as np

from v6.encoder import MiniLMEncoder, canonical, digest
from v6.router import KINDS, LABELS, Router, measure
from v6.training_language import corpus


def diagnostics(rows, decisions):
    """Retain labeled raw errors; abstention cannot repair the wrong class."""
    raw = [
        {**decision, "operation": None if decision["raw_operation"] == "reject" else decision["raw_operation"]}
        for decision in decisions
    ]
    confusion = {
        language: {label: {other: 0 for other in LABELS} for label in LABELS}
        for language in sorted({row["language"] for row in rows})
    }
    errors = []
    for row, decision in zip(rows, decisions):
        confusion[row["language"]][row["operation"]][decision["raw_operation"]] += 1
        if decision["raw_operation"] != row["operation"]:
            errors.append(
                {
                    "id": row["id"],
                    "language": row["language"],
                    "text": row["text"],
                    "gold": row["operation"],
                    "prediction": decision["raw_operation"],
                    "accepted": decision["operation"],
                }
            )
    return {"raw_metrics": measure(rows, raw), "confusion": confusion, "raw_errors": errors}


def train(model_cache, output, seeds, additional_model_cache=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    project = Path(__file__).resolve().parent
    source_paths = [
        Path(__file__),
        *(project / "v6" / name for name in ("encoder.py", "router.py", "training_language.py")),
    ]
    source = {str(path.relative_to(project)): digest(path.read_bytes()) for path in source_paths}
    git = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=project, capture_output=True, text=True, check=True
    ).stdout.strip()
    rows, selection = corpus("train"), corpus("selection")
    if {row["text"] for row in rows} & {row["text"] for row in selection}:
        raise ValueError("training and selection literal overlap")
    (output / "TRAIN.json").write_bytes(canonical(rows) + b"\n")
    (output / "SELECTION.json").write_bytes(canonical(selection) + b"\n")
    bases, base_costs = {}, []
    caches = [model_cache] + ([additional_model_cache] if additional_model_cache is not None else [])
    for index, cache in enumerate(caches):
        name = f"base{index}"
        encoder = MiniLMEncoder(cache)
        if any(encoder.digest == other[0].digest for other in bases.values()):
            raise ValueError("additional encoder must differ from primary encoder")
        dense = encoder.encode([row["text"] for row in rows])
        selected_dense = encoder.encode([row["text"] for row in selection])
        feature_path = output / f"{name}-feature-cache.npz"
        np.savez_compressed(feature_path, train=dense, selection=selected_dense)
        bases[name] = (encoder, dense, selected_dense)
        base_costs.append(
            {
                "name": name,
                "identity": encoder.identity,
                "digest": encoder.digest,
                "bytes": encoder.base_bytes,
                "load_seconds": encoder.load_seconds,
                "encoding_calls": encoder.calls,
                "encoding_seconds": encoder.seconds,
                "feature_cache_bytes": feature_path.stat().st_size,
                "feature_arrays_bytes": dense.nbytes + selected_dense.nbytes,
            }
        )
    all_receipts = []
    for seed in seeds:
        folder = output / f"seed-{seed}"
        folder.mkdir()
        candidates = []
        for base_name, (encoder, dense, selected_dense) in bases.items():
            for kind in KINDS:
                if base_name != "base0" and kind.startswith("lexical"):
                    continue  # Lexical candidates neither use nor pay for a base.
                for strength in (0.5, 2.0, 8.0):
                    name = f"{base_name}-{kind}-c{strength:g}"
                    model = Router(encoder, kind, seed, strength)
                    fit_receipt = model.fit(rows, dense=dense)
                    trials = model.calibrate(selection, dense=selected_dense)
                    target = folder / name
                    artifact = model.save(target)
                    decisions = model.decisions(
                        [row["text"] for row in selection],
                        model.scores([row["text"] for row in selection], dense=selected_dense),
                    )
                    selected_metrics = measure(selection, decisions)
                    policy_key = list(fit_receipt["selection"]["selection_key"])
                    key = (
                        policy_key[:4]
                        + [-artifact["deployment_bytes_excluding_base"] - artifact["base_bytes"]]
                        + policy_key[4:]
                    )
                    record = {
                        "name": name,
                        "base": None if kind.startswith("lexical") else base_name,
                        "fit": fit_receipt,
                        "calibration_grid": trials,
                        "artifact": artifact,
                        "metrics": selected_metrics,
                        "diagnostics": diagnostics(selection, decisions),
                        "selection_key": key,
                    }
                    candidates.append(record)
                    print(
                        json.dumps(
                            {
                                "seed": seed,
                                "candidate": name,
                                "known": selected_metrics["known_correct_rate"],
                                "ood": selected_metrics["ood_acceptance_rate"],
                                "languages": selected_metrics["language_correct_rates"],
                            }
                        ),
                        flush=True,
                    )
        winner = max(candidates, key=lambda item: item["selection_key"])
        shutil.copytree(folder / winner["name"], folder / "selected")
        # Check an actual save/load boundary using the same admitted encoder.
        encoder, _, selected_dense = bases[winner["base"] or "base0"]
        restored = Router.load(folder / "selected", encoder, winner["artifact"]["manifest_sha256"])
        scores = restored.scores([row["text"] for row in selection], dense=selected_dense)
        if measure(selection, restored.decisions([row["text"] for row in selection], scores)) != winner["metrics"]:
            raise ValueError("saved selected model changed decisions")
        (folder / "CANDIDATES.json").write_bytes(canonical(candidates) + b"\n")
        (folder / "SELECTED.json").write_bytes(canonical(winner) + b"\n")
        all_receipts.append(
            {
                "seed": seed,
                "selected": winner["name"],
                "base": winner["base"],
                "artifact": winner["artifact"],
                "metrics": winner["metrics"],
                "actual_fits": len(candidates),
            }
        )
    receipt = {
        "schema": "hepta.memory.v6.routing-training.v1",
        "source_commit": git,
        "source_files": source,
        "seeds": seeds,
        "source_corpus_authors": "training assistant; no independent human annotations",
        "training_rows": len(rows),
        "selection_rows": len(selection),
        "train_sha256": digest(canonical(rows)),
        "selection_sha256": digest(canonical(selection)),
        "held_read": False,
        "bases": base_costs,
        "unique_base_bytes": sum(item["bytes"] for item in base_costs),
        "candidates": all_receipts,
        "fit_count": sum(r["actual_fits"] for r in all_receipts),
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu,
        "versions": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "scipy", "scikit-learn", "onnxruntime", "tokenizers")
        },
        "limitations": [
            "same author corpus across seeds; not independent linguistic samples",
            "lbfgs logistic regression is deterministic: seeds are replication checks, not independent random initializations",
            "frozen pretrained base; only classifier coefficients and lexical features are fitted",
            "selection is finite synthetic language; population risk is not certified",
        ],
    }
    receipt["directory_bytes_before_receipt"] = sum(path.stat().st_size for path in output.rglob("*") if path.is_file())
    (output / "TRAINING.json").write_bytes(canonical(receipt) + b"\n")
    print(
        json.dumps({"selected": all_receipts, "wall_seconds": receipt["wall_seconds"], "fits": receipt["fit_count"]}),
        flush=True,
    )
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-cache", required=True, type=Path)
    parser.add_argument("--additional-model-cache", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seeds", nargs="+", type=int, default=[1103, 1109, 1117, 1123, 1129])
    args = parser.parse_args()
    if not 1 <= len(args.seeds) <= 16 or len(set(args.seeds)) != len(args.seeds):
        parser.error("provide 1..16 distinct seeds")
    train(args.model_cache, args.output, args.seeds, args.additional_model_cache)
