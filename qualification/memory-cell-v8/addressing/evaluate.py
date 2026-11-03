"""One frozen held-language pass plus exact native fixture export.

Classifier diagnostics are separate from native execution. The corresponding
Rust qualification fixture records every actual owner/socket read, including a
candidate that did not earn production admission.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bootstrap
from addressing.contracts import digest
from addressing.model import IntentModel
from v6.encoder import MiniLMEncoder
from v8_addressing.model import SelectiveIntentModel
from v8_addressing.native_fixture import load_suite, native_fixture
from v8_addressing.policy import metrics
from v8_addressing.runner_io import check_source_lock, load_json, retain_sources, sources, write_json


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
    if (args.baseline_model is None) != (args.baseline_digest is None):
        raise ValueError("baseline directory and identity must be supplied together")
    write_json(output / "EVALUATION_LOCK.json", {"schema": "hepta.memory.v8.held-lock.v1", "source": source,
        "admission_identity": admission["identity"], "serving_admitted": admission["serving_admitted"],
        "held_input_sha256": args.held_sha256, "held_not_yet_read": True,
        "frozen_v7_baseline_digest": args.baseline_digest, "no_further_selection_or_calibration": True})
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
    model = SelectiveIntentModel.load(args.admission / "model", encoder, admission["identity"]["manifest_sha256"])
    hypotheses = model.hypotheses([row["text"] for row in rows], dense=dense)
    decisions = [model.decide(value) for value in hypotheses]
    scored = metrics(rows, hypotheses, model.policies)
    write_json(output / "held-readouts.json", [{"row": row, "decision": decision} for row, decision in zip(rows, decisions)])
    baseline = None
    if args.baseline_model is not None:
        legacy = IntentModel.load(args.baseline_model, encoder, args.baseline_digest)
        legacy_predictions = legacy.hypotheses([row["text"] for row in rows], dense=dense)
        policies = {name: {"threshold": legacy.threshold, "margin": legacy.margin} for name in model.policies}
        baseline = {"identity": args.baseline_digest, "kind": "frozen-V7-existing-model", "metrics": metrics(rows, legacy_predictions, policies),
                    "same_information_architecture_ablation": False,
                    "interpretation": "Includes the disclosed change in public training data and policy; cannot isolate architecture causality."}
        write_json(output / "baseline-readouts.json", [{"row": row, "decision": legacy.decide(value)}
                                                       for row, value in zip(rows, legacy_predictions)])
    result = {"schema": "hepta.memory.v8.held-language-result.v1", "source": source, "input": receipt,
              "identity": admission["identity"], "serving_admitted": admission["serving_admitted"],
              "metrics": scored, "frozen_v7_baseline": baseline, "actual_head_fits": 0,
              "wall_seconds": time.perf_counter() - began, "cpu_seconds": time.process_time() - cpu,
              "native_rows_executed_by_this_python_stage": 0,
              "native_fixture": "native-fixture.json", "native_fixture_sha256": hashlib.sha256((output / "native-fixture.json").read_bytes()).hexdigest(),
              "native_execution_required_even_when_not_admitted": True,
              "qualification_only": True, "final_use_authority": False, "population_risk_established": False}
    write_json(output / "HELD.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoder", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--admission", type=Path, required=True)
    parser.add_argument("--held", type=Path, required=True)
    parser.add_argument("--held-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-model", type=Path)
    parser.add_argument("--baseline-digest")
    arguments = parser.parse_args()
    destination = arguments.output.absolute()
    destination.mkdir(parents=True, exist_ok=False)
    try:
        print(json.dumps(evaluate(arguments, destination), sort_keys=True), flush=True)
    except Exception as error:
        write_json(destination / "FAILURE.json", {"error_type": type(error).__name__, "error": str(error),
                                                   "retained_partial_evidence": True, "no_post_failure_retuning": True})
        raise
