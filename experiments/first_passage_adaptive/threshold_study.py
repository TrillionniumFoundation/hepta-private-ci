"""Registered same-information threshold training and one-shot confirmation."""

import argparse
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import platform
import re
import time

import numpy as np
import scipy

from .threshold_policies import (
    CONFIGURATION, fit_fixed, fit_ordinary, ordinary_thresholds, plan_context,
)
from .thresholds import (
    EvaluationCost, context_dicts, execute, make_contexts, named_noise, renewal_value,
)
from .threshold_statistics import summarize


PACKAGE = Path(__file__).resolve().parent
ROOT = PACKAGE.parents[1]
PROTOCOL = PACKAGE/"ADAPTIVE_PROTOCOL.json"
CONFIRMATION_REGISTRY = PACKAGE/"evidence"/"threshold_confirmation_registry"
SOURCE_FILES = [PACKAGE/name for name in (
    "__init__.py", "thresholds.py", "threshold_policies.py", "threshold_statistics.py",
    "threshold_study.py", "ADAPTIVE_PROTOCOL.json", "CONTRACT.md", "requirements.txt",
    "tests/test_thresholds.py", "tests/test_threshold_statistics.py", "tests/test_threshold_study.py",
    "review/paired_cluster_reference.py",
)] + [ROOT/"experiments/first_passage_cell/kernels.py"]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")


def identity():
    return {"source_sha256": {str(path.relative_to(ROOT)): digest(path) for path in SOURCE_FILES},
        "runtime": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__},
        "implementation_configuration": CONFIGURATION}


def load_protocol():
    data = json.loads(PROTOCOL.read_text())
    config = data["threshold_study"]["implementation_configuration"]
    for key in ("ordinary_initial_intercepts", "ordinary_maxiter", "ordinary_ftol",
                "ordinary_gtol", "ordinary_ridge"):
        if CONFIGURATION[key] != config[key]:
            raise ValueError("Controller configuration differs from its registration")
    if (config["fixed_and_value"]["grid_points"] != CONFIGURATION["planner_grid_size"]
            or config["fixed_and_value"]["bounded_xatol"] != CONFIGURATION["planner_xatol"]):
        raise ValueError("Planner configuration differs from its registration")
    return data


def data_binding(contexts):
    rows = context_dicts(contexts)
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return {"sha256": hashlib.sha256(payload).hexdigest(), "contexts": rows}


def load_checkpoint(path):
    saved = json.loads(Path(path).read_text())
    data = load_protocol()
    if (saved.get("schema") != "hepta.first-passage.threshold.checkpoint.v1"
            or saved["source_identity"] != identity()
            or saved["study_id"] != data["study_id"]):
        raise ValueError("Checkpoint source/protocol/runtime identity mismatch")
    if [fit["fit_seed"] for fit in saved["fits"]] != data["threshold_study"]["fit_seeds"]:
        raise ValueError("Checkpoint does not contain exactly the registered ordered fitted seeds")
    return saved


def train(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    data, source = load_protocol(), identity()
    config = data["threshold_study"]
    write_new(output/"registration.json", {"study_id": data["study_id"],
        "registered_at": datetime.now(timezone.utc).isoformat(), "source_identity": source,
        "confirmation_opened": False})
    started = time.perf_counter()
    try:
        fits = []
        for seed in config["fit_seeds"]:
            training = make_contexts(config, "train", seed)
            development = make_contexts(config, "development", seed)
            print(f"Threshold train/development: seed {seed}", flush=True)
            fixed = fit_fixed(training, config["threshold_bounds"])
            ordinary = fit_ordinary(training, development, config["threshold_bounds"])
            report_cost = EvaluationCost()
            dev_fixed = renewal_value(fixed["threshold"], development, counter=report_cost).mean()
            dev_b = ordinary_thresholds(ordinary, development, config["threshold_bounds"])
            dev_ordinary = renewal_value(dev_b, development, counter=report_cost).mean()
            fits.append({"fit_seed": seed, "fixed": fixed, "ordinary": ordinary,
                "training_data": data_binding(training), "development_data": data_binding(development),
                "development_values": {"fixed": float(dev_fixed), "ordinary": float(dev_ordinary)},
                "development_reporting_cost": asdict(report_cost)})
        if identity() != source:
            raise ValueError("Registered source changed during threshold fitting")
        saved = {"schema": "hepta.first-passage.threshold.checkpoint.v1", "study_id": data["study_id"],
            "source_identity": source, "registration_sha256": digest(output/"registration.json"),
            "fits": fits, "elapsed_seconds": time.perf_counter()-started, "confirmation_opened": False}
        write_new(output/"checkpoint.json", saved)
    except Exception as error:
        write_new(output/"failure.json", {"error_type": type(error).__name__, "error": str(error)})
        raise
    return {"checkpoint": str(output/"checkpoint.json"), "confirmation_opened": False}


def freeze(checkpoint, output):
    saved = load_checkpoint(checkpoint)
    write_new(output, {"schema": "hepta.first-passage.threshold.freeze.v1", "study_id": saved["study_id"],
        "source_identity": identity(), "checkpoint_sha256": digest(checkpoint),
        "configuration": load_protocol()["threshold_study"], "confirmation_opened": False})
    return {"freeze": str(output), "sha256": digest(output), "confirmation_opened": False}


def evaluate_seed(fit, config, raw_handle, planner_handle):
    seed = fit["fit_seed"]
    contexts = make_contexts(config, "confirmation", seed)
    begin = time.perf_counter()
    ordinary = ordinary_thresholds(fit["ordinary"], contexts, config["threshold_bounds"])
    ordinary_time = time.perf_counter()-begin
    rows = []
    arm_costs = {arm: {"policy": {**asdict(EvaluationCost()), "wall_seconds": 0.0},
        "execution": {"calls": 0, "rollouts": 0, "wall_seconds": 0.0},
        "diagnostic": {**asdict(EvaluationCost()), "wall_seconds": 0.0}}
        for arm in config["arms"]}
    arm_costs["ordinary_context_threshold"]["policy"]["wall_seconds"] = ordinary_time
    arm_costs["ordinary_context_threshold"]["policy"]["inference_batches"] = 1
    arm_costs["ordinary_context_threshold"]["policy"]["inference_contexts"] = len(contexts)
    for index, context in enumerate(contexts):
        if index % 64 == 0:
            print(f"Threshold confirmation: seed {seed}, context {index}/{len(contexts)}", flush=True)
        b_value, planner = plan_context(context, config["threshold_bounds"])
        planner["fit_seed"], planner["context_index"] = seed, index
        planner_handle.write(json.dumps(planner, separators=(",", ":"), allow_nan=False)+"\n")
        for key, value in planner["cost"].items():
            arm_costs["value_threshold"]["policy"][key] += value
        thresholds = {"fixed_threshold": fit["fixed"]["threshold"],
                      "ordinary_context_threshold": float(ordinary[index]), "value_threshold": b_value}
        noise = named_noise(context, seed_base=config["rollout_seed_base"], fit_seed=seed,
                            context_index=index, repeats=config["rollouts_per_context"])
        row = {"fit_seed": seed, "context_index": index, "stratum": context.stratum,
               "context": asdict(context), "arms": {}}
        for arm, threshold in thresholds.items():
            begin = time.perf_counter()
            result = execute(threshold, context, noise)
            arm_costs[arm]["execution"]["calls"] += 1
            arm_costs[arm]["execution"]["rollouts"] += len(result["utility"])
            arm_costs[arm]["execution"]["wall_seconds"] += time.perf_counter()-begin
            begin = time.perf_counter()
            counter = EvaluationCost()
            expected = float(renewal_value(threshold, [context], counter=counter)[0])
            for key, value in asdict(counter).items():
                arm_costs[arm]["diagnostic"][key] += value
            arm_costs[arm]["diagnostic"]["wall_seconds"] += time.perf_counter()-begin
            terminal, counts = np.unique(result["terminal"], return_counts=True)
            row["arms"][arm] = {"threshold": threshold, "analytic_value": expected,
                "mean_utility": float(result["utility"].mean()),
                "utility": result["utility"].tolist(), "hits": result["hits"].tolist(),
                "terminal_counts": dict(zip(terminal.tolist(), counts.tolist())),
                "last_hit_time": [float(t) if np.isfinite(t) else None for t in result["last_hit_time"]]}
        raw_handle.write(json.dumps(row, separators=(",", ":"), allow_nan=False)+"\n")
        rows.append(row)
    return rows, {"fit_seed": seed, "confirmation_data": data_binding(contexts), "costs": arm_costs}


@contextmanager
def compressed_writer(path):
    """Deterministic compressed raw evidence; never replace an earlier run."""
    with Path(path).open("xb") as binary:
        with gzip.GzipFile(filename="", mode="wb", fileobj=binary, mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8") as text:
                yield text


def confirm(checkpoint, frozen, output):
    saved = load_checkpoint(checkpoint)
    data = load_protocol()
    registered = json.loads(Path(frozen).read_text())
    if (registered.get("schema") != "hepta.first-passage.threshold.freeze.v1"
            or registered["study_id"] != saved["study_id"]
            or registered["checkpoint_sha256"] != digest(checkpoint)
            or registered["source_identity"] != identity()
            or registered["configuration"] != data["threshold_study"]):
        raise ValueError("Threshold confirmation source/model/configuration freeze mismatch")
    study_id = data["study_id"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", study_id):
        raise ValueError("Unsafe study registry key")
    marker = CONFIRMATION_REGISTRY/f"{study_id}.json"
    if marker.exists():
        raise FileExistsError("Threshold confirmation has already been opened for this study")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write_new(marker, {"study_id": study_id, "scope": "registered threshold comparisons",
        "opened_at": datetime.now(timezone.utc).isoformat(), "freeze_sha256": digest(frozen), "output": str(output)})
    started = time.perf_counter()
    try:
        records, receipts = [], []
        with compressed_writer(output/"rollouts.jsonl.gz") as raw:
            with compressed_writer(output/"planner_searches.jsonl.gz") as searches:
                for fit in saved["fits"]:
                    rows, receipt = evaluate_seed(fit, data["threshold_study"], raw, searches)
                    records.extend(rows)
                    receipts.append(receipt)
        expected_count = data["threshold_study"]["contexts_per_fit_seed"]["confirmation"]
        for seed in data["threshold_study"]["fit_seeds"]:
            indices = [row["context_index"] for row in records if row["fit_seed"] == seed]
            if indices != list(range(expected_count)):
                raise ValueError("Confirmation context identities or counts differ from registration")
        if identity() != registered["source_identity"]:
            raise ValueError("Frozen sources changed during confirmation")
        statistics = summarize(records, data["threshold_study"])
        calibration = {}
        for arm in data["threshold_study"]["arms"]:
            residuals = np.array([r["arms"][arm]["mean_utility"]-r["arms"][arm]["analytic_value"] for r in records])
            calibration[arm] = {"mean_MC_minus_analytic": float(residuals.mean()),
                               "context_standard_error": float(residuals.std(ddof=1)/np.sqrt(len(residuals)))}
        result = {"schema": "hepta.first-passage.threshold.confirmation.v1", "study_id": study_id,
            "source_identity": identity(), "checkpoint_sha256": digest(checkpoint), "freeze_sha256": digest(frozen),
            "statistics": statistics, "calibration": calibration, "seed_receipts": receipts,
            "raw_evidence_sha256": {name: digest(output/name) for name in ("rollouts.jsonl.gz", "planner_searches.jsonl.gz")},
            "confirmation_opened": True, "elapsed_seconds": time.perf_counter()-started,
            "cost_scope": "Utility includes per-hit task cost. Solver and training costs are separately measured; no compute or energy superiority is inferred."}
        write_new(output/"confirmation.json", result)
    except Exception as error:
        write_new(output/"failure.json", {"error_type": type(error).__name__, "error": str(error)})
        raise
    return {"confirmation": str(output/"confirmation.json"), "confirmation_opened": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    for name in ("train", "freeze", "confirm"):
        action = actions.add_parser(name)
        action.add_argument("--output", required=True)
        if name != "train":
            action.add_argument("--checkpoint", required=True)
        if name == "confirm":
            action.add_argument("--freeze", required=True)
    args = parser.parse_args()
    if args.action == "train":
        result = train(args.output)
    elif args.action == "freeze":
        result = freeze(args.checkpoint, args.output)
    else:
        result = confirm(args.checkpoint, args.freeze, args.output)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
