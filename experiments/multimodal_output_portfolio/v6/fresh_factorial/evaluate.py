"""Consume one frozen final cohort once, after complete label-free replay."""

import argparse
from datetime import datetime, timezone
import io
import json
from pathlib import Path

import numpy as np

from .infer import compare_replay, validate_run
from .io import (clock, cost, cpu_environment, digest, file_hash, published_source,
                               read_json, require_owner, run_stage, seal, source_hashes, validate_data, write)
from .statistics import WEIGHTS, analyze, score_observation
from .gates import verify_model_seal, verify_training
from .models import load_observer, verify_bootstrap


LEDGER_NAME = "final-access-ndu-fresh-factorial.json"


def claim_final(data, binding):
    """Creation, even a later scoring failure, consumes this source cohort."""
    require_owner(binding, data, "data")
    ledger = Path(data) / LEDGER_NAME
    write(ledger, {"schema": "hepta.ndu-fresh-factorial.final-access.v1", **binding,
                  "at_utc": datetime.now(timezone.utc).isoformat(), "single_access_consumed": True,
                  "failure_consumes_sources": True, "authority": "DENY_ALL"})
    return ledger


def read_final_once(path, expected):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size != expected["bytes"] or expected["bytes"] > 16 << 20:
        raise ValueError("bounded final source payload is missing or changed")
    with path.open("rb") as stream:
        raw = stream.read((16 << 20) + 1)
    if digest(raw) != expected["sha256"]:
        raise ValueError("opaque pre-final payload hash differs at its first read")
    with np.load(io.BytesIO(raw), allow_pickle=False) as archive:
        if set(archive.files) != {"pixels", "labels"}:
            raise ValueError("final target archive fields differ")
        pixels, labels = archive["pixels"], archive["labels"]
    if (pixels.shape != (90, 1, 28, 56) or pixels.dtype != np.float32
            or labels.shape != (90, 2) or labels.dtype.kind not in "iu"
            or not np.isfinite(pixels).all() or pixels.min() < 0 or pixels.max() > 1
            or labels.min() < 0 or labels.max() > 9):
        raise ValueError("final target dimensions or values differ")
    return pixels, labels


def evaluate(data, training, runs, replay, protocol, source_commit, output):
    began = clock()
    plan = read_json(protocol)
    source = published_source(plan, source_commit, protocol)
    torch, environment = cpu_environment(plan)
    from ..observer import METRIC, METRIC_DIGEST, observe_tensors, read_bundle
    from ..neural import parameter_hash
    if (METRIC != plan["metric"] or METRIC_DIGEST != plan["metric_sha256"] or METRIC["weights"] != WEIGHTS
            or plan["audit_crop_predictions_per_output"] != 2):
        raise ValueError("registered metric definition changed")
    root = require_owner(plan, output, "evaluation")
    root.mkdir(parents=True, exist_ok=False)
    write(root / "source-freeze.json", source)
    model_seal = verify_model_seal(plan)
    bootstrap_root = root.parent / "bootstrap"
    generation, _ = verify_bootstrap(bootstrap_root, plan)
    receipt, cases = validate_data(data, plan)
    fitted = verify_training(training, plan)
    first, rows, states = validate_run(runs, data, fitted, plan)
    repeated, replay_rows, replay_states = validate_run(replay, data, fitted, plan, replay=True)
    compare_replay(rows, states, replay_rows, replay_states)
    replay_audit = read_json(Path(replay) / "replay.json")
    if (replay_audit["original_run_seal_sha256"] != file_hash(Path(runs) / "run-seal.json")
            or any(environment != record["environment"] for record in (receipt, fitted, first, repeated))
            or any(record["training_seal_sha256"] != file_hash(Path(training) / "training-seal.json") for record in (first, repeated))
            or any(read_json(Path(directory) / "source-freeze.json") != source for directory in (training, runs, replay))):
        raise ValueError("source, environment, fitted-model or replay bindings differ")
    observer = load_observer(bootstrap_root, "audit", plan, torch)
    observer_before = parameter_hash(observer)
    # No target payload is opened until every checkpoint/output/state replay gate above succeeds.
    binding = {"protocol_canonical_sha256": digest(plan), "source_commit": source_commit,
               "source_owner_directory": plan["source_owner_directory"],
               "generation_id": model_seal["generation_id"], "model_seal_sha256": file_hash(root.parent / "model-seal.json"),
               "data_receipt_sha256": file_hash(Path(data) / "data-receipt.json"),
               "training_seal_sha256": file_hash(Path(training) / "training-seal.json"),
               "run_seal_sha256": file_hash(Path(runs) / "run-seal.json"),
               "replay_seal_sha256": file_hash(Path(replay) / "run-seal.json"),
               "expected_target_identity": receipt["files"]["final-targets.npz"],
               "source_case_count": len(cases), "rows_ready": len(rows), "evaluation_directory": str(root.resolve())}
    ledger = claim_final(data, binding)
    try:
        targets, labels = read_final_once(Path(data) / "final-targets.npz", binding["expected_target_identity"])
        target_index = {case["case_id"]: index for index, case in enumerate(cases)}
        scored, largest_difference = [], 0.
        for row in rows:
            started = clock()
            pixels, caption, hashes = read_bundle({kind: Path(runs) / path for kind, path in row["paths"].items()})
            if hashes != row["output_sha256"]:
                raise ValueError("frozen raw output changed after final access")
            index = target_index[row["case_id"]]
            target = torch.from_numpy(targets[index:index + 1])
            truth = torch.from_numpy(labels[index:index + 1])
            observed = observe_tensors(observer, pixels, [caption], target, truth)[0]
            checked = score_observation(pixels.numpy(), caption, observed["image_digits"],
                                        targets[index:index + 1], labels[index].tolist())
            for key in (*WEIGHTS, "joint_loss", "utility"):
                delta = abs(observed[key] - checked[key])
                largest_difference = max(largest_difference, delta)
                if delta > 1e-7:
                    raise ValueError("independent emitted-output metric arithmetic differs")
            for key in ("caption_valid", "caption_digits", "caption_relation", "image_digits"):
                if observed[key] != checked[key]:
                    raise ValueError("independent caption/relationship interpretation differs")
            observed["joint_fact_correct"] = checked["joint_fact_correct"]
            scored.append({**row, "metrics": observed, "audit_observer_file_sha256": generation["observers"]["audit"]["file"]["sha256"],
                           "evaluation_cost": cost(started)})
            if len(scored) % 180 == 0:
                print(json.dumps({"final_rows_scored": len(scored), "cohort_consumed": True}), flush=True)
        if parameter_hash(observer) != observer_before or source_hashes(plan) != source["files"]:
            raise ValueError("audit observer or source changed during scoring")
        result = analyze(scored, plan)
        result.update(protocol_canonical_sha256=digest(plan), environment=environment,
                      final_access_ledger_sha256=file_hash(ledger), binding=binding,
                      arithmetic_audit={"rows_checked": len(scored), "maximum_absolute_difference": largest_difference,
                          "scope": "independent NumPy scoring arithmetic on identical frozen OCR predictions; OCR itself is not independently certified"},
                      cost=cost(began), total_audit_crop_predictions=len(scored) * 2,
                      final_targets_opened_once=True, outcome_dependent_model_selection=False,
                      experiment_scope=plan["scope"])
        write(root / "scored-rows.json", {"rows": scored})
        write(root / "summary.json", result)
        write(root / "final-access.json", read_json(ledger))
        seal_hash = seal(root, "evaluation-seal.json")
        return {"primary": result["primary"], "source_pairs": len(cases), "rows_scored": len(scored),
                "final_access_consumed": True, "evaluation_seal_sha256": seal_hash, "cost": result["cost"]}
    except Exception as error:
        write(root / "final-access-failure.json", {"final_access_consumed": True, "ledger": str(ledger),
              "error_type": type(error).__name__, "message": str(error),
              "reselection_or_repeat_evaluation_forbidden": True})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "training", "runs", "replay", "protocol", "source-commit", "output"):
        parser.add_argument("--" + name, required=True)
    print(json.dumps(run_stage(evaluate, vars(parser.parse_args())), sort_keys=True))
