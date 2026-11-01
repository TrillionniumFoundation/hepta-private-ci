"""Separate development, fit, freeze and fresh-confirmation stages."""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import platform
import resource
import time

import numpy as np
import torch

from ..digital_read_before_20261031.data import cohort, prepare_fit
from ..digital_read_before_20261031.task import ContentAdapter, Oracle
from .execution import Runtime, extend_behavior, occupancy_key, run_episode
from .models import MechanismPolicy
from .training import candidates, fit_candidate

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    if path.name.endswith(".gz"):
        raw = gzip.compress(raw, compresslevel=6, mtime=0)
    with path.open("xb") as stream:
        stream.write(raw)
    return dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))


def read_json(path):
    path = Path(path)
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.name.endswith(".gz") else raw)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hashes():
    selected = list(HERE.glob("*.py")) + list(HERE.glob("*.rs")) + [HERE / "protocol.json"]
    selected += list((HERE.parent / "digital_read_before_20261031").glob("*.py"))
    selected += [HERE.parent / "task_value_factorial_20261030/task.py",
                 HERE.parent / "task_value_factorial_20261030/UPSTREAM_FILES.json",
                 HERE.parent / "third/memory/reference.py",
                 HERE.parent / "third/memory/checkpoints/memory_full_mass_seed29.npz",
                 HERE.parent / "next/full_kernel/baseline_table.npz"]
    return {str(path.relative_to(REPO)): digest(path) for path in sorted(selected)}


def evaluate_models(models, records, adapter, confusion, protocol, fit, split, training_receipts):
    output, summary, runtime_receipts = [], [], []
    diagnostic_oracles = {}
    for identifier, policy in models.items():
        training = training_receipts.get(identifier, {})
        old_keys = {tuple(x) for x in training.get("behavior_occupancy_keys", [])}
        new_keys = old_keys | {tuple(x) for x in training.get("augmented_occupancy_keys", [])}
        for controller in ("fixed", "value"):
            prepare = time.process_time()
            runtime = None if policy is None else Runtime(policy)
            preparation = time.process_time() - prepare
            episodes = []
            for i, record in enumerate(records):
                seed = protocol["execution_seed_base"] + fit * 100000 + {"validation": 0, "iid": 10000, "ood": 20000}[split] + i
                if runtime is not None and record["id"] not in diagnostic_oracles:
                    diagnostic_oracles[record["id"]] = Oracle(read_json(Path(record["folder"]) / "public.json"), confusion)
                episode, _ = run_episode(runtime, record, adapter, confusion, controller, seed,
                                         diagnostic_oracle=diagnostic_oracles.get(record["id"]))
                episode.update(fit=fit, split=split, candidate=identifier)
                keys = [tuple(row["occupancy_key"]) for row in episode["decisions"]]
                episode["metrics"].update(behavior_strata_unseen=sum(k not in old_keys for k in keys) / len(keys),
                                          aggregated_strata_unseen=sum(k not in new_keys for k in keys) / len(keys))
                episodes.append(episode)
            keys = episodes[0]["metrics"]
            metrics = {key: float(np.mean([r["metrics"][key] for r in episodes])) for key in keys}
            summary.append(dict(fit=fit, split=split, candidate=identifier, controller=controller,
                                worlds=len(episodes), metrics=metrics))
            output.extend(episodes)
            runtime_receipts.append(dict(candidate=identifier, controller=controller,
                                         model_setup_cpu_seconds=preparation,
                                         lazy_preparation_cpu_seconds=0. if runtime is None else runtime.preparation_cpu,
                                         lazy_preparation_charged_inside_episode=True,
                                         array_storage_bytes=0 if runtime is None else runtime.storage_bytes(),
                                         transition_contexts=0 if runtime is None else len(runtime.transitions),
                                         feature_contexts=0 if runtime is None else len(runtime.features)))
    return output, summary, runtime_receipts


def train_fit(root, fit, protocol, development):
    root.mkdir(parents=True, exist_ok=False)
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    sources = source_hashes()
    write_json(root / "STARTED.json", dict(stage="development" if development else "formal_fit",
               utc=datetime.now(timezone.utc).isoformat(), source_sha256=sources,
               protocol=protocol, fit=fit, confirmation_generated=False,
               python=platform.python_version(), numpy=np.__version__, torch=torch.__version__))
    data = extend_behavior(prepare_fit(root / "data", fit, protocol))
    write_json(root / "extended_data.json.gz", data)
    adapter = ContentAdapter()
    trained, receipts = {}, {}
    for spec in candidates():
        policy, artifact, receipt = fit_candidate(spec, fit, data, adapter, protocol)
        trained[spec["id"]] = policy
        receipts[spec["id"]] = receipt
        write_json(root / "models" / (spec["id"] + ".json"), artifact)
        write_json(root / "training" / (spec["id"] + ".json.gz"), receipt)
        print(json.dumps(dict(stage="fit", fit=fit, candidate=spec["id"], updates=receipt["optimizer_updates"],
                              learning_cpu=receipt["learning_cpu_seconds"])), flush=True)
    trained["bayes"] = None
    if development:
        raw, summary, runtime_cost = evaluate_models(trained, data["validation_cohort"]["records"], adapter,
                                                    data["confusion"], protocol, fit, "validation", receipts)
        write_json(root / "validation_episodes.json.gz", raw)
        write_json(root / "validation_summary.json", summary)
        write_json(root / "validation_runtime.json", runtime_cost)
    finish = dict(fit=fit, development=development, source_sha256=sources,
                  whole_stage_cpu_seconds=time.process_time() - start_cpu,
                  whole_stage_wall_seconds=time.perf_counter() - start_wall,
                  peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  models={name: dict(path=str((root / "models" / (name + ".json")).relative_to(root)),
                                    sha256=digest(root / "models" / (name + ".json"))) for name in receipts},
                  training_totals={name: {key: r[key] for key in (
                      "learning_cpu_seconds", "setup_cpu_seconds", "optimizer_updates", "capacity",
                      "cpu_budget_overshoot", "realized_visit_records")} for name, r in receipts.items()})
    write_json(root / "FINISHED.json", finish)


def confirm_fit(root, training, freeze_path, fit, protocol):
    freeze = read_json(freeze_path)
    if source_hashes() != freeze["source_sha256"] or freeze["protocol"] != protocol:
        raise ValueError("source/protocol changed after model freeze")
    commit = freeze.get("verified_remote_commit", "")
    if len(commit) != 40 or set(commit) - set("0123456789abcdef") or fit not in freeze["fits"]:
        raise ValueError("verified published model freeze and registered fit required")
    model_ids = {c["id"] for c in candidates()}
    expected_model_keys = {f"{f}/{name}" for f in protocol["fits"] for name in model_ids}
    if freeze["fits"] != protocol["fits"] or set(freeze["models_sha256"]) != expected_model_keys:
        raise ValueError("incomplete registered model/fit freeze")
    if set(freeze["training_receipts_sha256"]) != expected_model_keys:
        raise ValueError("incomplete training receipt freeze")
    for mapping in ("training_started_sha256", "training_finished_sha256", "training_process_sha256", "training_data_sha256"):
        if set(freeze[mapping]) != {str(f) for f in protocol["fits"]}:
            raise ValueError("incomplete fit provenance freeze")
    fitted = training / f"fit_{fit}"
    if digest(fitted / "STARTED.json") != freeze["training_started_sha256"][str(fit)]:
        raise ValueError("actual training protocol receipt changed after freeze")
    data_path = fitted / "extended_data.json.gz"
    if digest(data_path) != freeze["training_data_sha256"][str(fit)]:
        raise ValueError("TRAIN data changed after model freeze")
    if digest(fitted / "FINISHED.json") != freeze["training_finished_sha256"][str(fit)]:
        raise ValueError("training completion receipt changed after model freeze")
    if digest(training / "process_receipts" / f"fit_{fit}.json") != freeze["training_process_sha256"][str(fit)]:
        raise ValueError("training process cost receipt changed after freeze")
    models, receipts = {}, {}
    for identifier in sorted(model_ids):
        path = fitted / "models" / (identifier + ".json")
        if digest(path) != freeze["models_sha256"][f"{fit}/{identifier}"]:
            raise ValueError("model changed after freeze")
        models[identifier] = MechanismPolicy.from_export(read_json(path))
        receipt_path = fitted / "training" / (identifier + ".json.gz")
        if digest(receipt_path) != freeze["training_receipts_sha256"][f"{fit}/{identifier}"]:
            raise ValueError("training cost/coverage receipt changed after freeze")
        receipts[identifier] = read_json(receipt_path)
    models["bayes"] = None
    root.mkdir(parents=True, exist_ok=False)
    write_json(root / "STARTED.json", dict(utc=datetime.now(timezone.utc).isoformat(),
               model_freeze_sha256=digest(freeze_path), published_model_commit=freeze["verified_remote_commit"],
               fit=fit, confirmation_preexisting=False))
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    data, adapter = read_json(data_path), ContentAdapter()
    all_summary, runtime_receipts = [], []
    for split in ("iid", "ood"):
        generated = cohort(root / "worlds", split, fit, protocol[f"{split}_worlds"], protocol)
        write_json(root / f"{split}_cohort.json", generated)
        raw, summary, cost = evaluate_models(models, generated["records"], adapter, data["confusion"],
                                             protocol, fit, split, receipts)
        write_json(root / f"{split}_episodes.json.gz", raw)
        all_summary.extend(summary)
        runtime_receipts.append(dict(split=split, models=cost))
        print(json.dumps(dict(stage="confirmation", fit=fit, split=split, episodes=len(raw))), flush=True)
    write_json(root / "summary.json", all_summary)
    write_json(root / "runtime.json", runtime_receipts)
    write_json(root / "FINISHED.json", dict(fit=fit, whole_stage_cpu_seconds=time.process_time()-start_cpu,
               whole_stage_wall_seconds=time.perf_counter()-start_wall,
               peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("development", "train", "confirm"))
    parser.add_argument("--fit", type=int, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=HERE / "protocol.json")
    parser.add_argument("--training", type=Path)
    parser.add_argument("--freeze", type=Path)
    args = parser.parse_args()
    protocol = read_json(args.protocol)
    torch.set_num_threads(1)
    registered = protocol["development_fits" if args.stage == "development" else "fits"]
    if args.fit not in registered:
        raise ValueError("fit is outside the registered stage")
    if args.stage == "confirm":
        confirm_fit(args.root / f"fit_{args.fit}", args.training, args.freeze, args.fit, protocol)
    else:
        train_fit(args.root / f"fit_{args.fit}", args.fit, protocol, args.stage == "development")


if __name__ == "__main__":
    main()
