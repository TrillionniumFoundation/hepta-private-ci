"""Train two new observers and six matched bases; never import historical weights."""

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys

from .data_prepare import training_corpus
from .io import (clock, cost, cpu_environment, deny_final, digest, file_hash, identity, published_source,
                 read_json, require_identity, require_owner, run_stage, seal, source_hashes,
                 validate_data, verify_seal, write)
from .matching import PROFILES, recipe_controls, verify_base_reports


def generation_id(plan, data_receipt_sha256, source_commit):
    return digest({"study": plan["study_id"], "protocol": digest(plan), "data_receipt": data_receipt_sha256,
                   "source_commit": source_commit, "provenance": "new_optimizer_execution_no_historical_checkpoints"})


def verify_bootstrap(directory, plan):
    root = require_owner(plan, directory, "bootstrap")
    sealed = verify_seal(root, "bootstrap-seal.json")
    report = read_json(root / "bootstrap.json")
    start = read_json(root / "generation-start.json")
    data = Path(plan["source_owner_directory"]) / "data"
    receipt, _ = validate_data(data, plan)
    controls = read_json(root / "recipe-controls.json")["controls"]
    required = {"bootstrap.json", "generation-start.json", "recipe-controls.json", "source-freeze.json"}
    if (report["schema"] != "hepta.ndu-fresh-factorial.bootstrap.v1"
            or report["protocol_canonical_sha256"] != digest(plan)
            or report["data_receipt_sha256"] != file_hash(data / "data-receipt.json")
            or report["generation_id"] != generation_id(plan, report["data_receipt_sha256"], start["source_commit"])
            or start["generation_id"] != report["generation_id"]
            or start["protocol_canonical_sha256"] != digest(plan)
            or start["data_receipt_sha256"] != report["data_receipt_sha256"]
            or read_json(root / "source-freeze.json")["git_commit"] != start["source_commit"]
            or start["historical_weights_loaded"] is not False or report["historical_weights_loaded"] is not False
            or report["base_optimizer_updates"] != 12000 or report["observer_optimizer_updates"] != 600
            or report["audit_observer_used_for_training"] is not False
            or report["observer_source_pools_disjoint"] is not True
            or report["final_targets_opened"] is not False or report["environment"] != receipt["environment"]
            or set(report["observers"]) != {"reward", "audit"}):
        raise ValueError("fresh observer/base generation receipt is incomplete or falsely historical")
    rows = []
    for row in report["bases"]:
        stem = f"seed-{row['seed']}-{row['profile']}"
        if row["path"] != stem + ".pt" or row["report_path"] != stem + "-training.json":
            raise ValueError("fresh base checkpoint/report aliased")
        required.update((row["path"], row["report_path"]))
        require_identity(root / row["path"], row["file"])
        fit = read_json(root / row["report_path"])
        if (fit["final_snapshot_sha256"] != row["snapshot_sha256"] or fit["final_parameter_sha256"] != row["parameter_sha256"]
                or fit["fresh_generation_id"] != report["generation_id"]):
            raise ValueError("fresh base provenance binding differs")
        rows.append({"seed": row["seed"], "profile": row["profile"], "report": fit})
    verify_base_reports(rows, controls, plan)
    observer_ids = read_json(data / "observer-source.json")["source_ids"]
    for ordinal, name in enumerate(("reward", "audit")):
        row = report["observers"][name]
        checkpoint, fit_path = name + "-observer.pt", name + "-observer.json"
        if row["path"] != checkpoint or row["report_path"] != fit_path:
            raise ValueError("fresh observer checkpoint/report aliased")
        required.update((checkpoint, fit_path))
        require_identity(root / checkpoint, row["file"])
        fit = read_json(root / fit_path)
        ids = observer_ids[ordinal * 5000:(ordinal + 1) * 5000]
        if (fit["seed"] != plan["observer_training"]["seeds"][name] or fit["steps"] != 300
                or fit["train_sources"] != 4000 or fit["calibration_sources"] != 1000
                or fit["source_ids_sha256"] != hashlib.sha256("\n".join(ids).encode()).hexdigest()
                or fit["parameter_sha256"] != row["parameter_sha256"] or fit["selected_by_calibration"] is not False
                or fit["initial_parameter_sha256"] == fit["parameter_sha256"]):
            raise ValueError("fresh observer recipe/source differs or was selected on calibration")
    if set(sealed["files"]) != required or len(rows) != 6:
        raise ValueError("fresh bootstrap seal omits a required model/report or includes extras")
    return report, controls


def load_observer(directory, name, plan, torch):
    from ..observer import Recognizer
    from ..neural import parameter_hash
    report, _ = verify_bootstrap(directory, plan)
    row = report["observers"][name]
    path = Path(directory) / row["path"]
    require_identity(path, row["file"])
    model = Recognizer()
    model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True), strict=True)
    if parameter_hash(model) != row["parameter_sha256"]:
        raise ValueError("newly fitted observer does not match its pre-evaluation model seal")
    return model.cpu().eval().requires_grad_(False)


def bootstrap(data, protocol, source_commit, output):
    sys.addaudithook(deny_final)
    began = clock()
    plan = read_json(protocol)
    source = published_source(plan, source_commit, protocol)
    torch, environment = cpu_environment(plan)
    from ..neural import TrainConfig, load_snapshot, parameter_hash, train_profiles
    from ..observer import Recognizer, fit_observer
    root = require_owner(plan, output, "bootstrap")
    root.mkdir(parents=True, exist_ok=False)
    write(root / "source-freeze.json", source)
    receipt, _ = validate_data(data, plan)
    if environment != receipt["environment"]:
        raise ValueError("actual numerical environment changed before fresh training")
    data_sha = file_hash(Path(data) / "data-receipt.json")
    generation = generation_id(plan, data_sha, source_commit)
    write(root / "generation-start.json", {"generation_id": generation, "source_commit": source_commit,
        "protocol_canonical_sha256": digest(plan), "data_receipt_sha256": data_sha,
        "historical_weights_loaded": False, "new_optimizer_updates_planned": 12600})
    corpus = training_corpus(data, plan, torch, include_observer=True)
    pool, observers = corpus.splits["evaluator"], {}
    if len(set(pool.pixel_hashes)) != 10000:
        raise ValueError("observer sources contain repeated pixels")
    for ordinal, name in enumerate(("reward", "audit")):
        a, b = ordinal * 5000, (ordinal + 1) * 5000
        subset = replace(pool, images=pool.images[a:b], labels=pool.labels[a:b],
                         ids=pool.ids[a:b], pixel_hashes=pool.pixel_hashes[a:b])
        seed = plan["observer_training"]["seeds"][name]
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            initial_sha = parameter_hash(Recognizer())
        started = clock()
        model, report = fit_observer(subset, steps=300, seed=seed)
        report.update(initial_parameter_sha256=initial_sha, parameter_sha256=parameter_hash(model),
                      selected_by_calibration=False, cost=cost(started), provenance="fresh_execution")
        path = root / (name + "-observer.pt")
        with path.open("xb") as stream:
            torch.save(model.state_dict(), stream)
        restored = Recognizer()
        restored.load_state_dict(torch.load(path, map_location="cpu", weights_only=True), strict=True)
        if parameter_hash(restored) != report["parameter_sha256"]:
            raise ValueError("fresh observer reload differs")
        write(root / (name + "-observer.json"), report)
        observers[name] = {"path": path.name, "report_path": name + "-observer.json",
                           "file": identity(path), "parameter_sha256": report["parameter_sha256"]}
        del model, restored
        print(json.dumps({"observer_completed": name, "optimizer_updates": 300}), flush=True)
    # The audit observer is fitted but never supplied to base or gate training.
    controls = [recipe_controls(plan, seed, corpus.splits["train"].ids, torch) for seed in plan["seeds"]]
    write(root / "recipe-controls.json", {"controls": controls})
    bases, reports = [], []
    for seed in plan["seeds"]:
        def progress(profile, record):
            print(json.dumps({"seed": seed, "profile": profile, **record}), flush=True)
        started = clock()
        fitted, training = train_profiles(corpus, TrainConfig(seed=seed, **plan["base_training"]), progress=progress)
        pair_cost = cost(started)
        for profile in PROFILES:
            snapshot, report = fitted[profile], training[profile]
            report.update(fresh_generation_id=generation, paired_execution_cost=pair_cost)
            stem = f"seed-{seed}-{profile}"
            path = root / (stem + ".pt")
            if path.exists():
                raise ValueError("fresh base overwrite forbidden")
            snapshot.save(path)
            restored = load_snapshot(path, expected_file_sha256=file_hash(path))
            if restored.verify_integrity() != snapshot.fingerprint:
                raise ValueError("fresh conditioned base reload differs")
            write(root / (stem + "-training.json"), report)
            bases.append({"seed": seed, "profile": profile, "path": path.name,
                          "report_path": stem + "-training.json", "file": identity(path),
                          "snapshot_sha256": snapshot.fingerprint, "parameter_sha256": parameter_hash(snapshot._model)})
            reports.append({"seed": seed, "profile": profile, "report": report})
        del fitted, training
    verify_base_reports(reports, controls, plan)
    if source_hashes(plan) != source["files"]:
        raise ValueError("source changed during new optimizer execution")
    result = {"schema": "hepta.ndu-fresh-factorial.bootstrap.v1", "generation_id": generation,
        "protocol_canonical_sha256": digest(plan), "data_receipt_sha256": data_sha,
        "observers": observers, "bases": bases, "base_optimizer_updates": 12000,
        "observer_optimizer_updates": 600, "historical_weights_loaded": False,
        "audit_observer_used_for_training": False, "observer_source_pools_disjoint": True,
        "environment": environment, "cost": cost(began), "final_targets_opened": False,
        "authority": "DENY_ALL", "production_authority": False}
    write(root / "bootstrap.json", result)
    seal_sha = seal(root, "bootstrap-seal.json")
    verify_bootstrap(root, plan)
    return {"new_base_updates": 12000, "new_observer_updates": 600,
            "bootstrap_seal_sha256": seal_sha, "cost": result["cost"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "protocol", "source-commit", "output"):
        parser.add_argument("--" + name, required=True)
    print(json.dumps(run_stage(bootstrap, vars(parser.parse_args())), sort_keys=True))
