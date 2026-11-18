"""Evaluate frozen current-policy students after the independent B2 seal opens."""

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import resource
import sys
import time

MODES = ("NoUpdate", "all_observed", "verified_credit")
B2_RECORDS_SHA = "26b2e625c649a73a991c681bb1949cdaf91b995d8e4bc3402b924495797d42cb"
B2_CATALOG_SHA = "c3bdb9549bfde75416675609a068d22a7400dad43655afc287dd43cb1b6eb999"
B2_LOADER_SHA = "3fb3c9ec3af2660c6dfe9f35a34f63d26185b5762ee43093fe29870c59b05fe9"
B2_COMMITMENT_SHA = "79dd9032c7f335711567e5e4ba2ad8b69a4c75f5f79658030e2e897df34743d3"


def boot(args):
    sys.path.insert(0, str(args.old_code_root / "scripts"))
    sys.path.insert(0, str(args.candidate_root))
    global credit, data, repo_execution, require_prepared, feedback, write_new, file_hash
    import current_credit as credit
    from cell_experiments import data, repo_execution
    from cell_experiments.protocol_v3 import require_prepared, feedback
    from cell_experiments.coding_sft import write_new, file_hash
    # First verify that both completed weights were frozen. Only then can any
    # late-opened panel or loader be read or imported in this process.
    weights = data._parse((args.output / "WEIGHTS_FROZEN.json").read_bytes())
    freeze = data._parse((args.output / "FREEZE.json").read_bytes())
    credit.require(weights["status"] == "MATCHED_AND_WEIGHTS_FROZEN" and
                   weights["freeze_digest"] == data.digest(freeze), "both frozen fits required")
    for mode in credit.MODES:
        manifest = data._parse((args.output / "training" / mode / "manifest.json").read_bytes())
        credit.require(credit.verify_manifest(manifest, args.artifact_root, args.old_code_root,
                       args.candidate_root) == weights["arms"][mode]["model_digest"],
                       "actual frozen weight identity differs")
    repo_execution.load_catalog("open")
    from cell_experiments.upstream_panel_v4 import load_panel
    load_panel()
    credit.require(file_hash(args.b2_loader) == B2_LOADER_SHA, "sealed B2 loader changed")
    credit.require(file_hash(args.b2_directory / "CATALOG.json") == B2_CATALOG_SHA and
                   file_hash(args.b2_directory / "prepared/records.jsonl") == B2_RECORDS_SHA,
                   "sealed B2 payload changed")
    spec = importlib.util.spec_from_file_location("cell_experiments.blind_panel_v4", args.b2_loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    b2 = module.load_panel(args.b2_directory)
    credit.require(len(b2) == 6 and all(row["split"] == "confirmation" and
                   not row["authorization"]["training_allowed"] for row in b2),
                   "six sealed evaluation-only tasks required")
    return freeze, weights, b2


def freeze_evaluation(args, training_freeze, weights, b2):
    before = time.perf_counter()
    original = data._parse(args.original_panels.read_bytes())
    panels = {"A_retention": original["A_retention"],
              "B_exposed_development": original["B_upstream"], "B2_blind_future": b2}
    credit.require(all(len(rows) == 6 for rows in panels.values()), "complete panels required")
    for rows in panels.values():
        for row in rows:
            require_prepared(row)
    receipts = {panel: [data.verify_answer(row, row["final_answer"]) for row in rows]
                for panel, rows in panels.items()}
    credit.require(all(row["success"] for rows in receipts.values() for row in rows),
                   "original strict references must pass")
    directory = args.output / "evaluation"
    directory.mkdir(exist_ok=False)
    write_new(directory / "PANELS.json", panels)
    write_new(directory / "REFERENCE_CHECKS.json", receipts)
    result = {"schema": "hepta.current-policy-credit-evaluation-freeze.v1",
        "created_at_ns": time.time_ns(), "evaluation_code_commit": args.code_commit,
        "evaluation_source_sha256": file_hash(Path(__file__)),
        "training_freeze_digest": data.digest(training_freeze),
        "weights_frozen_file_sha256": file_hash(args.output / "WEIGHTS_FROZEN.json"),
        "weights_frozen_digest": data.digest(weights),
        "models": {"NoUpdate": credit.PARENT,
                   **{mode: weights["arms"][mode]["model_digest"] for mode in credit.MODES}},
        "panels_sha256": file_hash(directory / "PANELS.json"),
        "original_panels_sha256": file_hash(args.original_panels),
        "B2_commitment_source": "a6563725a6e8f17ee21d16e5d3fbf231cfb6bbff",
        "B2_commitment_sha256": B2_COMMITMENT_SHA, "B2_records_sha256": B2_RECORDS_SHA,
        "B2_catalog_sha256": B2_CATALOG_SHA, "B2_loader_sha256": B2_LOADER_SHA,
        "calls_per_task": 2, "max_new_tokens": 384, "max_input_tokens": 4096,
        "planned_model_calls": 108, "reference_verifier_calls": 18,
        "freeze_wall_seconds": time.perf_counter() - before,
        "selection": "A-only mechanism comparison; no selection or tuning from B or B2",
        "old_B_exposure": "repeated development", "B2_exposure": "sealed from trainer until both weights frozen",
        "scientific_confirmation_qualified": False, "native_adoption": False,
        "full_system_cost_known": False}
    write_new(directory / "FREEZE.json", result)
    return result


def evaluate(args, mode, weights):
    base = args.output / "evaluation"
    freeze = data._parse((base / "FREEZE.json").read_bytes())
    credit.require(file_hash(base / "PANELS.json") == freeze["panels_sha256"] and
                   data.digest(weights) == freeze["weights_frozen_digest"] and
                   file_hash(Path(__file__)) == freeze["evaluation_source_sha256"],
                   "frozen evaluation changed")
    panels = data._parse((base / "PANELS.json").read_bytes())
    directory = base / mode
    directory.mkdir(exist_ok=False)
    write_new(directory / "STARTED.json", {"mode": mode, "freeze_digest": data.digest(freeze),
                                           "started_at_ns": time.time_ns()})
    before, cpu = time.perf_counter(), time.process_time()
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    predictor, rows = None, []
    try:
        if mode == "NoUpdate":
            manifest = data._parse((args.output / "PARENT_MODEL.json").read_bytes())
            predictor = credit.matched.Predictor(manifest, args.artifact_root, args.old_code_root)
        else:
            manifest = data._parse((args.output / "training" / mode / "manifest.json").read_bytes())
            predictor = credit.Predictor(manifest, args.artifact_root, args.old_code_root, args.candidate_root)
        credit.require(predictor.model_digest == freeze["models"][mode], "wrong loaded model")
        write_new(directory / "MODEL_LOADED.json", {"model_digest": predictor.model_digest,
            "generation_digest": predictor.generation_digest, "load_wall_seconds": time.perf_counter() - before,
            "device": predictor.device_report})
        for panel, records in panels.items():
            for index, record in enumerate(records):
                messages = require_prepared(record)
                taskdir = directory / panel / str(index)
                taskdir.mkdir(parents=True, exist_ok=False)
                write_new(taskdir / "ORIGINAL_RECORD.json", record)
                steps = []
                for attempt in range(2):
                    request = {"record_id": record["record_id"], "task": {
                        "input": record["task"]["input"], "messages": copy.deepcopy(messages)}}
                    write_new(taskdir / f"REQUEST-{attempt}.json", request)
                    prediction = predictor.predict(request)
                    write_new(taskdir / f"OUTPUT-{attempt}.json", prediction)
                    credit.require(prediction["loaded_model_digest"] == predictor.model_digest and
                                   prediction["messages_sha256"] == data.digest(messages),
                                   "observed history or loaded model changed")
                    receipt = data.verify_answer(record, prediction["answer"])
                    write_new(taskdir / f"VERIFICATION-{attempt}.json", receipt)
                    steps.append({"attempt": attempt, "request_digest": data.digest(request),
                        "output_digest": data.digest(prediction), "verification": receipt,
                        "model_call_cost": {key: prediction[key] for key in (
                            "input_tokens", "output_tokens", "wall_seconds", "hit_output_limit")}})
                    messages.extend([{"role": "assistant", "content": prediction["answer"]},
                                     {"role": "tool", "content": feedback(receipt)}])
                first, last = [step["verification"]["success"] for step in steps]
                result = {"task_id": record["task_id"], "panel": panel, "first": first,
                    "last": last, "selected": first or last, "recovered": not first and last,
                    "regressed": first and not last, "steps": steps}
                write_new(taskdir / "RESULT.json", result)
                rows.append(result)
        predictor.close()
        predictor = None
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        result = {"status": "COMPLETE", "mode": mode, "freeze_digest": data.digest(freeze),
            "rows": rows, "by_panel": {panel: {"tasks": len(records),
                **{key: sum(row[key] for row in rows if row["panel"] == panel)
                   for key in ("first", "last", "selected", "recovered", "regressed")}}
                for panel, records in panels.items()},
            "cost": {"wall_seconds": time.perf_counter() - before,
                "self_cpu_seconds": time.process_time() - cpu,
                "completed_children_cpu_seconds": after.ru_utime + after.ru_stime - children.ru_utime - children.ru_stime,
                "model_calls": len(rows) * 2, "verifier_calls": len(rows) * 2,
                **{key: sum(step["model_call_cost"][key] for row in rows for step in row["steps"])
                   for key in ("input_tokens", "output_tokens", "hit_output_limit")},
                "energy_joules": None, "full_system_cost_known": False,
                "scope": "load, all actual calls, verifiers and close; nested generation windows are not additive"},
            "B_or_B2_selection": False, "scientific_confirmation_qualified": False, "native_adoption": False}
        write_new(directory / "RESULT.json", result)
        return result
    except BaseException as error:
        write_new(directory / "FAILED.json", {"error_type": type(error).__name__, "error": str(error),
            "completed_rows": len(rows), "wall_seconds": time.perf_counter() - before,
            "self_cpu_seconds": time.process_time() - cpu, "automatic_retry": False})
        raise
    finally:
        if predictor is not None:
            predictor.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("freeze", *MODES))
    for name in ("artifact-root", "old-code-root", "candidate-root", "output", "original-panels", "b2-loader", "b2-directory"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--code-commit", required=True)
    args = parser.parse_args()
    training_freeze, weights, b2 = boot(args)
    result = (freeze_evaluation(args, training_freeze, weights, b2) if args.stage == "freeze"
              else evaluate(args, args.stage, weights))
    print(json.dumps(result, sort_keys=True, allow_nan=False))
