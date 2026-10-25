"""Fit both gate objectives on every fresh base, then seal the entire generation."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from .data_prepare import training_corpus
from .io import (clock, cost, cpu_environment, deny_final, digest, file_hash, identity,
                 published_source, read_json, require_identity, require_owner, run_stage,
                 seal, source_hashes, validate_data, verify_seal, write)
from .matching import PROFILES, matched_gate_reports
from .models import load_observer, verify_bootstrap


def verify_training(directory, plan):
    root = require_owner(plan, directory, "training")
    bootstrap_root = Path(plan["source_owner_directory"]) / "bootstrap"
    generation, controls = verify_bootstrap(bootstrap_root, plan)
    manifest = verify_seal(root, "training-seal.json")
    result = read_json(root / "training.json")
    expected_pairs = {(seed, arm) for seed in plan["seeds"] for arm in plan["arms"]}
    base_rows = {(row["seed"], row["profile"]): row for row in generation["bases"]}
    if (result["schema"] != "hepta.ndu-fresh-factorial.training.v1"
            or result["protocol_canonical_sha256"] != digest(plan) or result["base_updates_during_gate_fit"] != 0
            or result["generation_id"] != generation["generation_id"]
            or result["bootstrap_seal_sha256"] != file_hash(bootstrap_root / "bootstrap-seal.json")
            or result["data_receipt_sha256"] != generation["data_receipt_sha256"]
            or result["gate_fits_completed"] != 12 or result["gate_optimizer_updates"] != 1440
            or {(r["seed"], r["arm"]) for r in result["models"]} != expected_pairs
            or len(result["models"]) != 12 or result["final_targets_opened"] is not False
            or result["environment"] != generation["environment"]):
        raise ValueError("fresh factorial training census or provenance incomplete")
    required = {"training.json", "source-freeze.json"}
    reports = []
    for row in result["models"]:
        stem = f"seed{row['seed']}-{row['arm']}"
        factors = plan["arms"][row["arm"]]
        if (row["path"] != stem + ".pt" or row["training_report_path"] != stem + "-training.json"
                or any(row[key] != value for key, value in factors.items())
                or row["base_sha256"] != base_rows[row["seed"], factors["base"]]["snapshot_sha256"]):
            raise ValueError("fresh factorial checkpoint/base/report path was aliased or replaced")
        required.update((row["path"], row["training_report_path"]))
        require_identity(root / row["path"], {"sha256": row["checkpoint_file_sha256"]})
        report = read_json(root / row["training_report_path"])
        if (report["combined_sha256"] != row["snapshot_sha256"] or report["base_sha256"] != row["base_sha256"]
                or report["final_gate_sha256"] != row["gate_sha256"]
                or report["fresh_generation_id"] != generation["generation_id"]
                or report["content_plan_observer_sha256"] != generation["observers"]["reward"]["parameter_sha256"]
                or report["gate_parameter_count"] != plan["gate_parameter_count"]):
            raise ValueError("fitted gate report differs from its new model generation")
        reports.append({"seed": row["seed"], "arm": row["arm"], "report": report})
    if set(manifest["files"]) != required:
        raise ValueError("training seal omits a required model/report or includes unregistered artifacts")
    matched_gate_reports(reports, controls, plan)
    return result


def model_binding(plan):
    owner = Path(plan["source_owner_directory"])
    bootstrap, _ = verify_bootstrap(owner / "bootstrap", plan)
    fitted = verify_training(owner / "training", plan)
    files = {"bootstrap/" + row["path"]: row["file"] for row in bootstrap["bases"]}
    files.update({"bootstrap/" + row["path"]: row["file"] for row in bootstrap["observers"].values()})
    files.update({"training/" + row["path"]: identity(owner / "training" / row["path"]) for row in fitted["models"]})
    if len(files) != 20:
        raise ValueError("generation seal requires two observers, six bases and twelve gates")
    return {"schema": "hepta.ndu-fresh-factorial.model-generation-seal.v1", "generation_id": bootstrap["generation_id"],
        "protocol_canonical_sha256": digest(plan), "data_receipt_sha256": bootstrap["data_receipt_sha256"],
        "bootstrap_seal_sha256": file_hash(owner / "bootstrap" / "bootstrap-seal.json"),
        "training_seal_sha256": file_hash(owner / "training" / "training-seal.json"), "model_files": files,
        "optimizer_updates": {"observers": 600, "bases": 12000, "gates": 1440},
        "historical_checkpoint_recovery": False, "final_outcomes_used": False, "model_selection": "none"}


def verify_model_seal(plan):
    owner = Path(plan["source_owner_directory"])
    sealed = read_json(owner / "model-seal.json")
    expected = model_binding(plan)
    if {key: value for key, value in sealed.items() if key != "at_utc"} != expected or not sealed.get("at_utc"):
        raise ValueError("complete append-only fresh model seal is missing or changed")
    for relative, expected_file in sealed["model_files"].items():
        require_identity(owner / relative, expected_file)
    return sealed


def train(data, protocol, source_commit, output):
    sys.addaudithook(deny_final)
    began = clock()
    plan = read_json(protocol)
    source = published_source(plan, source_commit, protocol)
    torch, environment = cpu_environment(plan)
    from ..neural import load_snapshot, parameter_hash
    from ..plan_training import ControlledSnapshot, fit_plan_head
    root = require_owner(plan, output, "training")
    bootstrap_root = Path(plan["source_owner_directory"]) / "bootstrap"
    root.mkdir(parents=True, exist_ok=False)
    write(root / "source-freeze.json", source)
    generation, controls = verify_bootstrap(bootstrap_root, plan)
    receipt, _ = validate_data(data, plan)
    corpus = training_corpus(data, plan, torch)
    if (environment != receipt["environment"] or environment != generation["environment"]
            or read_json(bootstrap_root / "source-freeze.json") != source):
        raise ValueError("actual source or numerical environment changed before gate fitting")
    reward = load_observer(bootstrap_root, "reward", plan, torch)
    reward_hash = parameter_hash(reward)
    models, reports = [], []
    for original in generation["bases"]:
        seed, base_profile = original["seed"], original["profile"]
        base = load_snapshot(bootstrap_root / original["path"], expected_file_sha256=original["file"]["sha256"])
        base_before = base.verify_integrity()
        if base_before != original["snapshot_sha256"] or base.metadata["profile"] != base_profile:
            raise ValueError("new base identity differs before gate fitting")
        for arm, factors in plan["arms"].items():
            if factors["base"] != base_profile:
                continue
            started = clock()
            fitted, report = fit_plan_head(base, corpus, reward, factors["gate"], seed, **plan["gate_fit"])
            if base.verify_integrity() != base_before or parameter_hash(reward) != reward_hash:
                raise ValueError("base or Reward A changed during fresh gate fitting")
            report.update(factorial_base_profile=base_profile, fresh_generation_id=generation["generation_id"],
                factorial_cost=cost(started), gate_parameter_count=sum(p.numel() for p in fitted._gate.parameters()))
            stem = f"seed{seed}-{arm}"
            checkpoint = root / (stem + ".pt")
            if checkpoint.exists():
                raise ValueError("fresh gate checkpoint overwrite forbidden")
            fitted.save(checkpoint)
            checkpoint_hash = file_hash(checkpoint)
            restored = ControlledSnapshot.load(checkpoint, expected_file_sha256=checkpoint_hash)
            if restored.verify_integrity() != fitted.fingerprint:
                raise ValueError("fresh factorial checkpoint reload differs")
            write(root / (stem + "-training.json"), report)
            models.append({"seed": seed, "arm": arm, **factors, "path": checkpoint.name,
                "training_report_path": stem + "-training.json", "checkpoint_file_sha256": checkpoint_hash,
                "snapshot_sha256": fitted.fingerprint, "base_sha256": base_before,
                "gate_sha256": fitted._gate_hash, "gate_parameter_count": report["gate_parameter_count"]})
            reports.append({"seed": seed, "arm": arm, "report": report})
            print(json.dumps({"gate_completed": stem, "base_unchanged": True, "optimizer_updates": 120}), flush=True)
    matched_gate_reports(reports, controls, plan)
    if source_hashes(plan) != source["files"]:
        raise ValueError("source changed during fresh gate fitting")
    verify_bootstrap(bootstrap_root, plan)
    result = {"schema": "hepta.ndu-fresh-factorial.training.v1", "protocol_canonical_sha256": digest(plan),
        "generation_id": generation["generation_id"], "bootstrap_seal_sha256": file_hash(bootstrap_root / "bootstrap-seal.json"),
        "models": models, "base_updates_during_gate_fit": 0, "gate_fits_completed": len(models),
        "gate_optimizer_updates": sum(r["report"]["optimizer_updates"] for r in reports),
        "reward_file_sha256": generation["observers"]["reward"]["file"]["sha256"],
        "data_receipt_sha256": file_hash(Path(data) / "data-receipt.json"), "environment": environment,
        "cost": cost(began), "final_targets_opened": False, "authority": "DENY_ALL", "production_authority": False}
    write(root / "training.json", result)
    seal(root, "training-seal.json")
    binding = model_binding(plan)
    write(Path(plan["source_owner_directory"]) / "model-seal.json",
          {**binding, "at_utc": datetime.now(timezone.utc).isoformat()})
    verify_model_seal(plan)
    return {"completed_gate_fits": len(models), "model_seal_sha256": file_hash(root.parent / "model-seal.json"),
            "total_new_optimizer_updates": 14040, "cost": result["cost"], "final_targets_opened": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "protocol", "source-commit", "output"):
        parser.add_argument("--" + name, required=True)
    print(json.dumps(run_stage(train, vars(parser.parse_args())), sort_keys=True))
