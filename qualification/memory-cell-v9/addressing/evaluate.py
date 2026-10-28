"""One source-locked V9 held pass with frozen V7/V8 comparisons and native export."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bootstrap
sys.path.insert(0, str(bootstrap.QUALIFICATION / "memory-cell-v8/addressing"))
import numpy as np
from addressing.model import IntentModel
from v6.encoder import MiniLMEncoder
from v8_addressing.model import SelectiveIntentModel
from v9_addressing.model import CompatibilityIntentModel
from v9_addressing.native_fixture import load_suite, native_fixture
from v9_addressing.policy import metrics
from v9_addressing.runner_io import check_source_lock, load_json, retain_sources, sources, write_json


def evaluate(args, output):
    source, repo = sources()
    admission = load_json(args.admission / "ADMISSION.json")
    selection = load_json(args.selection / "SELECTION_LOCK.json")
    check_source_lock(admission["source"], source)
    check_source_lock(selection["source"], source)
    if hashlib.sha256((args.selection / "SELECTION_LOCK.json").read_bytes()).hexdigest() != admission["selection_lock_sha256"]:
        raise ValueError("admission belongs to a different frozen selection")
    fitting = [row for name in ("train", "selection") for row in load_json(args.selection / (name + ".json"))]
    calibration = load_json(args.admission / "calibration-language.json")
    if re.fullmatch(r"[0-9a-f]{64}", args.held_sha256) is None:
        raise ValueError("an author-frozen held input digest is required")
    baseline_specs = [("v7", IntentModel, args.baseline_model, args.baseline_digest),
                      ("v8", SelectiveIntentModel, args.baseline_v8_model, args.baseline_v8_digest)]
    if any((directory is None) != (identity is None) for _, _, directory, identity in baseline_specs):
        raise ValueError("each baseline directory and identity must be supplied together")
    write_json(output / "EVALUATION_LOCK.json", {"schema": "hepta.memory.v9.held-lock.v1", "source": source,
        "admission_identity": admission["identity"], "serving_admitted": admission["serving_admitted"],
        "held_input_sha256": args.held_sha256, "held_not_yet_read": True,
        "frozen_baseline_digests": {name: identity for name, _, _, identity in baseline_specs},
        "no_further_selection_or_calibration": True})
    retain_sources(output, source, repo)
    if hashlib.sha256(args.held.read_bytes()).hexdigest() != args.held_sha256:
        raise ValueError("held bytes differ from the prior author lock")
    suite, rows, receipt = load_suite(args.held, "held", [row["text"] for row in (*fitting, *calibration)],
                                     [*[row["family"] for row in fitting], *admission["calibration_input"]["families"]],
                                     admission["calibration_input"]["all_native_normalized_text_sha256"])
    with (output / "held-input.json").open("xb") as handle:
        handle.write(args.held.read_bytes())
    write_json(output / "held-language.json", rows)
    write_json(output / "native-fixture.json", native_fixture(suite))
    began, cpu = time.perf_counter(), time.process_time()
    encoder = MiniLMEncoder(args.encoder)
    dense = encoder.encode([row["text"] for row in rows])
    np.savez_compressed(output / "held-features.npz", dense=dense)
    model = CompatibilityIntentModel.load(args.admission / "model", encoder, admission["identity"]["manifest_sha256"])
    hypotheses = model.hypotheses([row["text"] for row in rows], dense=dense)
    decisions = [model.decide(value) for value in hypotheses]
    scored = metrics(rows, hypotheses, model.policies)
    write_json(output / "held-readouts.json", [{"row": row, "decision": decision, "head_diagnostics": diagnostic}
               for row, decision, diagnostic in zip(rows, decisions, model.last_diagnostics)])
    baselines = {}
    for name, model_class, directory, identity in baseline_specs:
        if directory is None:
            continue
        legacy = model_class.load(directory, encoder, identity)
        predictions = legacy.hypotheses([row["text"] for row in rows], dense=dense)
        policies = legacy.policies if name == "v8" else {
            operation: {"threshold": legacy.threshold, "margin": legacy.margin} for operation in model.policies}
        baselines[name] = {"identity": identity, "kind": "frozen-existing-" + name, "metrics": metrics(rows, predictions, policies),
                           "same_information_architecture_ablation": False,
                           "interpretation": "Public fitting data and policies differ; this does not isolate architecture causality."}
        write_json(output / ("baseline-" + name + "-readouts.json"),
                   [{"row": row, "decision": legacy.decide(value)} for row, value in zip(rows, predictions)])
    result = {"schema": "hepta.memory.v9.held-language-result.v1", "source": source, "input": receipt,
              "identity": admission["identity"], "serving_admitted": admission["serving_admitted"],
              "metrics": scored, "frozen_baselines": baselines, "actual_head_fits": 0,
              "wall_seconds": time.perf_counter() - began, "cpu_seconds": time.process_time() - cpu,
              "native_rows_executed_by_this_python_stage": 0, "native_fixture": "native-fixture.json",
              "native_fixture_sha256": hashlib.sha256((output / "native-fixture.json").read_bytes()).hexdigest(),
              "offline_feature_sha256": hashlib.sha256((output / "held-features.npz").read_bytes()).hexdigest(),
              "native_execution_required_even_when_not_admitted": True,
              "qualification_only": True, "final_use_authority": False, "population_risk_established": False}
    write_json(output / "HELD.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("encoder", "selection", "admission", "held", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--held-sha256", required=True)
    parser.add_argument("--baseline-model", type=Path)
    parser.add_argument("--baseline-digest")
    parser.add_argument("--baseline-v8-model", type=Path)
    parser.add_argument("--baseline-v8-digest")
    arguments = parser.parse_args()
    destination = arguments.output.absolute()
    destination.mkdir(parents=True, exist_ok=False)
    try:
        print(json.dumps(evaluate(arguments, destination), sort_keys=True), flush=True)
    except Exception as error:
        write_json(destination / "FAILURE.json", {"error_type": type(error).__name__, "error": str(error),
                                                   "retained_partial_evidence": True, "no_post_failure_retuning": True})
        raise
