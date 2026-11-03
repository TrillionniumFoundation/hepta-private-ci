"""Fit public candidates, freeze selection, then separately admit with new data."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bootstrap
import numpy as np
from addressing.contracts import digest
from v6.encoder import MiniLMEncoder
from v9_addressing.model import CompatibilityIntentModel
from v9_addressing.native_fixture import load_suite, native_fixture
from v9_addressing.policy import contract_comparison, fit_policies
from v9_addressing.public_corpus import public_rows
from v9_addressing.runner_io import check_source_lock, load_json, retain_sources, sources, write_json


CANDIDATES = [(kind, regularization) for kind in ("semantic", "hybrid") for regularization in (2.0, 8.0, 32.0)]


def select(encoder_path, output, previous_public_selection=None):
    source, repo = sources()
    rows = public_rows()
    previous = None
    if previous_public_selection is not None:
        path = Path(previous_public_selection) / "TRAINING.json"
        prior = load_json(path)
        if (prior.get("schema") != "hepta.memory.v9.addressing-selection-result.v1"
                or prior.get("calibration_opened") is not False or prior.get("held_opened") is not False):
            raise ValueError("development history must precede independent calibration and held evaluation")
        previous = {"training_receipt_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "directory": str(Path(previous_public_selection).absolute()),
                    "head_fits": prior.get("development_cumulative_head_fits", prior["actual_head_fits"]),
                    "wall_seconds": prior.get("development_cumulative_wall_seconds", prior["total_wall_seconds"]),
                    "cpu_seconds": prior.get("development_cumulative_cpu_seconds", prior["total_cpu_seconds"])}
    write_json(output / "DESIGN.json", {"schema": "hepta.memory.v9.addressing-selection-design.v1", "source": source,
        "candidates": [{"kind": kind, "C": regularization} for kind, regularization in CANDIDATES],
        "input_sha256": {name: digest(values) for name, values in rows.items()},
        "calibration_opened": False, "held_opened": False, "previous_public_selection": previous,
        "known_limitations": ["Authored language; no iid population guarantee.", "Explicit owner-listed aliases.",
                              "Disclosed V7/V8 public train and selection are reused only for fitting; V9 has a new public selection and new independent calibration/held."]})
    retain_sources(output, source, repo)
    for name, values in rows.items():
        write_json(output / (name + ".json"), values)
    started, cpu = time.perf_counter(), time.process_time()
    encoder = MiniLMEncoder(encoder_path)
    encode_start, encode_cpu = time.perf_counter(), time.process_time()
    features = {name: encoder.encode([row["text"] for row in values]) for name, values in rows.items()}
    np.savez_compressed(output / "development-features.npz", **features)
    encoding = {"wall_seconds": time.perf_counter() - encode_start, "cpu_seconds": time.process_time() - encode_cpu,
                "rows": sum(len(values) for values in rows.values()), "numeric_bytes": sum(value.nbytes for value in features.values())}
    candidates = []
    (output / "progress").mkdir()
    for number, (kind, regularization) in enumerate(CANDIDATES):
        began, process = time.perf_counter(), time.process_time()
        model = CompatibilityIntentModel(encoder, kind, regularization)
        fitting = model.fit(rows["train"], dense=features["train"])
        predictions = model.hypotheses([row["text"] for row in rows["selection"]], dense=features["selection"])
        diagnostics = model.last_diagnostics
        raw_predictions = model.learned_hypotheses([row["text"] for row in rows["selection"]], dense=features["selection"])
        policy = fit_policies(rows["selection"], predictions)
        comparison = contract_comparison(rows["selection"], raw_predictions, predictions, policy["policies"])
        model.policies = policy["policies"]
        identity = model.save(output / f"candidate-{number:02}")
        write_json(output / f"candidate-{number:02}" / "selection-predictions.json", predictions)
        write_json(output / f"candidate-{number:02}" / "selection-head-diagnostics.json", diagnostics)
        write_json(output / f"candidate-{number:02}" / "raw-learned-predictions.json", raw_predictions)
        write_json(output / f"candidate-{number:02}" / "raw-head-diagnostics.json", model.last_diagnostics)
        write_json(output / f"candidate-{number:02}" / "CONTRACT_COMPARISON.json", comparison)
        write_json(output / f"candidate-{number:02}" / "SELECTION.json", policy)
        candidate = {"candidate": number, "directory": f"candidate-{number:02}", "kind": kind, "C": regularization,
                     "training": fitting, "selection_metrics": policy["metrics"], "selection_key": policy["selection_key"],
                     "contract_comparison": comparison,
                     "identity": identity, "wall_seconds": time.perf_counter() - began, "cpu_seconds": time.process_time() - process}
        candidates.append(candidate)
        write_json(output / "progress" / f"{number:02}.json", candidate)
        print(json.dumps({"candidate": number, "selection": policy["metrics"]}), flush=True)
    chosen = max(candidates, key=lambda value: (*value["selection_key"], -value["identity"]["deployment_bytes_excluding_base"], -value["candidate"]))
    lock = {"schema": "hepta.memory.v9.addressing-selection-lock.v1", "source": source,
            "candidate": chosen["candidate"], "directory": chosen["directory"], "identity": chosen["identity"],
            "all_candidates_sha256": digest(candidates), "input_sha256": {name: digest(values) for name, values in rows.items()},
            "calibration_opened": False, "held_opened": False, "previous_public_selection": previous}
    write_json(output / "SELECTION_LOCK.json", lock)
    result = {"schema": "hepta.memory.v9.addressing-selection-result.v1", "source": source, "candidates": candidates,
              "selected_candidate": chosen["candidate"], "encoding": encoding, "actual_head_fits": 7 * len(candidates),
              "encoder_digest": encoder.digest, "encoder_bytes": encoder.base_bytes,
              "total_wall_seconds": time.perf_counter() - started, "total_cpu_seconds": time.process_time() - cpu,
              "retained_bytes_before_final_report": sum(path.stat().st_size for path in output.rglob("*") if path.is_file()),
              "serving_admitted": False, "calibration_opened": False, "held_opened": False}
    result.update(previous_public_selection=previous,
                  development_cumulative_head_fits=7 * len(candidates) + (previous["head_fits"] if previous else 0),
                  development_cumulative_wall_seconds=result["total_wall_seconds"] + (previous["wall_seconds"] if previous else 0),
                  development_cumulative_cpu_seconds=result["total_cpu_seconds"] + (previous["cpu_seconds"] if previous else 0))
    write_json(output / "TRAINING.json", result)
    return result


def calibrate(encoder_path, selected, calibration_path, calibration_sha256, output):
    source, repo = sources()
    selected = Path(selected).absolute()
    lock = load_json(selected / "SELECTION_LOCK.json")
    check_source_lock(lock["source"], source)
    fitting = {name: load_json(selected / (name + ".json")) for name in ("train", "selection")}
    if {name: digest(values) for name, values in fitting.items()} != lock["input_sha256"]:
        raise ValueError("frozen fitting input identity changed")
    # This immutable receipt precedes the first calibration read and encoding.
    write_json(output / "MODEL_LOCK.json", {"selection_lock_sha256": hashlib.sha256((selected / "SELECTION_LOCK.json").read_bytes()).hexdigest(),
                                            "selected_identity": lock["identity"], "source": source,
                                            "calibration_input_expected_sha256": calibration_sha256,
                                            "calibration_not_yet_read": True, "held_opened": False})
    retain_sources(output, source, repo)
    seen = [row["text"] for values in fitting.values() for row in values]
    families = [row["family"] for values in fitting.values() for row in values]
    if hashlib.sha256(Path(calibration_path).read_bytes()).hexdigest() != calibration_sha256:
        raise ValueError("calibration bytes differ from the independent author lock")
    suite, rows, input_receipt = load_suite(calibration_path, "calibration", seen, families)
    with (output / "calibration-input.json").open("xb") as handle:
        handle.write(Path(calibration_path).read_bytes())
    write_json(output / "calibration-language.json", rows)
    write_json(output / "calibration-native-fixture.json", native_fixture(suite))
    started, cpu = time.perf_counter(), time.process_time()
    encoder = MiniLMEncoder(encoder_path)
    model = CompatibilityIntentModel.load(selected / lock["directory"], encoder, lock["identity"]["manifest_sha256"])
    dense = encoder.encode([row["text"] for row in rows])
    np.savez_compressed(output / "calibration-features.npz", dense=dense)
    predictions = model.hypotheses([row["text"] for row in rows], dense=dense)
    diagnostics = model.last_diagnostics
    raw_predictions = model.learned_hypotheses([row["text"] for row in rows], dense=dense)
    policy = fit_policies(rows, predictions, previous=model.policies)
    model.policies = policy["policies"]
    model.calibration = {key: value for key, value in policy.items() if key not in ("curves", "policies", "selection_key")}
    model.calibration.update(input_receipt=input_receipt, selection_identity=lock["identity"],
                             selected_policy_sha256=digest(model.policies), calibration_used_for_weights=False,
                             candidate_reselected=False, held_opened=False)
    identity = model.save(output / "model")
    write_json(output / "calibration-predictions.json", predictions)
    write_json(output / "calibration-head-diagnostics.json", diagnostics)
    write_json(output / "raw-learned-predictions.json", raw_predictions)
    write_json(output / "raw-head-diagnostics.json", model.last_diagnostics)
    comparison = contract_comparison(rows, raw_predictions, predictions, model.policies)
    write_json(output / "CONTRACT_COMPARISON.json", comparison)
    write_json(output / "CALIBRATION.json", policy)
    result = {"schema": "hepta.memory.v9.addressing-admission-result.v1", "source": source, "selected": str(selected),
              "selection_lock_sha256": hashlib.sha256((selected / "SELECTION_LOCK.json").read_bytes()).hexdigest(),
              "identity": identity, "calibration_input": input_receipt, "metrics": policy["metrics"],
              "serving_admitted": policy["empirical_gate_passed"], "actual_head_fits": 0, "contract_comparison": comparison,
              "held_opened": False, "population_risk_established": False,
              "wall_seconds": time.perf_counter() - started, "cpu_seconds": time.process_time() - cpu}
    write_json(output / "ADMISSION.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("select", "calibrate"))
    parser.add_argument("--encoder", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--calibration-sha256")
    parser.add_argument("--previous-public-selection", type=Path)
    args = parser.parse_args()
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    try:
        if args.stage == "select":
            if args.selection is not None or args.calibration is not None or args.calibration_sha256 is not None:
                raise ValueError("selection cannot receive calibration material")
            result = select(args.encoder, output, args.previous_public_selection)
        else:
            if args.selection is None or args.calibration is None or args.calibration_sha256 is None:
                raise ValueError("calibration requires an existing selection and new input")
            if args.previous_public_selection is not None:
                raise ValueError("calibration cannot change the public development history")
            result = calibrate(args.encoder, args.selection, args.calibration, args.calibration_sha256, output)
        print(json.dumps(result, sort_keys=True), flush=True)
    except Exception as error:
        write_json(output / "FAILURE.json", {"stage": args.stage, "error_type": type(error).__name__, "error": str(error),
                                             "held_opened": False, "retained_partial_evidence": True})
        raise
