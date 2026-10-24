"""Seal complete-text lexical controls using existing frozen source selections."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from cell_calibrated_curve import (_calibrate, code_hashes, inventory,
    sha_file, verify_prepared, write_json)
from cell_calibrated_evaluate import _record
from cell_calibration_v2 import (apply_calibrator_logits, group_weights,
    prior_corrected_logits, smoothed_prior, weighted_nll)
from cell_full_text_lexical import FullTextLexical
from cell_learning_metrics import probabilities
from cell_learning_models import canonical
from long_document_sources import FullSourceBank
from operational_head_view import full_normalized_text, verify_view
from run_calibrated_cells import compact_summary


def load_sources(dataset, archive=None, source_receipt=None):
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    if Path(dataset).stat().st_size > 256*1024**2 or bool(archive) != bool(source_receipt):
        raise ValueError("bounded dataset and complete optional source-bank arguments required")
    source_blob = Path(dataset).read_bytes()
    source_sha = hashlib.sha256(source_blob).hexdigest()
    data = json.loads(source_blob)
    if not 1 <= len(data["rows"]) <= 16384:
        raise ValueError("bounded complete-source cohort required")
    files = {str(Path(dataset).resolve()): source_sha}
    complete = {r["source_id"]: r["text"] for r in data["rows"]}
    if archive:
        bank = FullSourceBank(dataset, archive, source_receipt)
        complete = {r["source_id"]: r["text"] for r in bank.records()}
        bank.verify_files()
        if bank.file_hashes[str(Path(dataset).resolve())] != source_sha:
            raise ValueError("dataset changed while opening complete source bank")
        files.update(bank.file_hashes)
    rows, seen_groups, seen_text = {}, {}, {}
    for row in data["rows"]:
        text = complete[row["source_id"]]
        normalized = full_normalized_text(text)
        if row["source_id"] in rows:
            raise ValueError("duplicate source ID")
        for seen, key in ((seen_groups, row["group_id"]), (seen_text, normalized)):
            if key in seen and seen[key] != row["split"]:
                raise ValueError("complete-text source groups or normalized predictors cross splits")
            seen[key] = row["split"]
        rows[row["source_id"]] = {"source_id": row["source_id"], "group_id": row["group_id"], "text": text}
    if any(sha_file(path) != digest for path, digest in files.items()):
        raise ValueError("complete source changed during loading")
    return data, rows, files, {"wall_ns": time.perf_counter_ns()-began,
        "cpu_ns": time.process_time_ns()-cpu, "rows": len(rows),
        "retained_source_utf8_bytes": sum(len(r["text"].encode()) for r in rows.values())}


def verify_lexical_prepared(root):
    root = Path(root)
    if json.loads((root/"seal.json").read_bytes()) != {
            "schema": "hepta.full-text-lexical-preparation-seal.v1", "files": inventory(root)}:
        raise ValueError("complete-text lexical preparation changed")
    return json.loads((root/"frozen.json").read_bytes())


def validate_task_preparation(frozen, original, task, main_seal, source_rows):
    p, source = frozen["plan"], original["plan"]
    expected = {"task_id": task, "family_id": source["family_id"],
        "tuning_source_ids": source["tuning_source_ids"],
        "calibration_source_ids": source["calibration_source_ids"],
        "source_main_prepared_seal_sha256": main_seal,
        "configuration": source["configuration"], "holdout_supplied_to_preparation": False}
    if p != expected or frozen["unavailable"] != original["unavailable"]:
        raise ValueError("full-text prepared inputs differ from the frozen primary task")
    actual = [(r["seed"], r["budget"], r["training_source_ids"], r["training_labels"]) for r in frozen["runs"]]
    expected_runs = [(r["seed"], r["budget"], r["training_source_ids"],
        [source_rows[s]["labels"][task] for s in r["training_source_ids"]]) for r in original["runs"]]
    if actual != expected_runs:
        raise ValueError("full-text train source draws or labels differ from the frozen primary task")


def run_companion(dataset, main_study, output, *, phase="prepare", head_view=None,
                  archive=None, source_receipt=None):
    if phase not in ("prepare", "evaluate", "all"):
        raise ValueError("unknown lexical companion phase")
    data, public, files, load_cost = load_sources(dataset, archive, source_receipt)
    by_id = {r["source_id"]: r for r in data["rows"]}
    main, root = Path(main_study), Path(output)
    newly_created = not root.exists()
    main_plan = json.loads((main/"study-plan.json").read_bytes())
    expected_dataset = sha_file(dataset)
    if head_view:
        expected_dataset = verify_view(dataset, head_view)["head_view_dataset_sha256"]
        files.update({str(Path(head_view, name).resolve()): sha_file(Path(head_view, name))
                      for name in ("dataset.json", "receipt.json")})
    if (main_plan["dataset_sha256"] != expected_dataset
            or main_plan["code_sha256"] != code_hashes()
            or main_plan["input_modality"] != "text"):
        raise ValueError("main frozen study differs from complete-source dataset or numerical code")
    selection = json.loads((main/"selection-seal.json").read_bytes())
    if (selection["all_declared_tasks_frozen_before_any_evaluation"] is not True
            or set(selection["seals"]) != {f"{t}/prepared/seal.json" for t in main_plan["tasks"]}
            or any(sha_file(main/path) != digest for path, digest in selection["seals"].items())):
        raise ValueError("main source selections are not unchanged and sealed")
    originals = {task: verify_prepared(main/task/"prepared") for task in main_plan["tasks"]}
    current_code = {name: sha_file(Path(__file__).with_name(name)) for name in
        ("run_full_text_lexical.py", "cell_full_text_lexical.py", "operational_head_view.py", "long_document_sources.py")}
    plan = {"schema": "hepta.full-text-lexical-study.v1", "dataset_sha256": expected_dataset,
        "source_dataset_sha256": sha_file(dataset), "condition": "complete_text_lexical_companion",
        "tasks": main_plan["tasks"], "families": main_plan["families"],
        "protocol": main_plan["protocol"], "holdout_use": main_plan["holdout_use"],
        "input_modality": "text", "feature_identity": "complete_text_lexical_no_encoder",
        "main_study_plan_sha256": sha_file(main/"study-plan.json"),
        "main_selection_seal_sha256": sha_file(main/"selection-seal.json"),
        "main_prepared_seals": {t: sha_file(main/t/"prepared/seal.json") for t in originals},
        "main_code_sha256": code_hashes(), "companion_code_sha256": current_code,
        "source_files_sha256": files,
        "complete_predictor_sha256": hashlib.sha256(canonical([
            [s, hashlib.sha256(r["text"].encode()).hexdigest()] for s, r in public.items()])).hexdigest(),
        "maximum_source_utf8_bytes": 131072, "arms": ["exact", "bm25"],
        "selection": "no winner selection; reuse fixed main train/tune/cal sources and calibrator",
        "feature_extraction_cost": {"load": None, "encoding": {"encoder_forward_calls": 0}},
        "quality_qualification": False}
    if root.exists():
        if json.loads((root/"study-plan.json").read_bytes()) != plan:
            raise ValueError("existing full-text plan differs; source or implementation changed")
    else:
        if phase == "evaluate":
            raise ValueError("complete-text scoring requires frozen preparation")
        if plan["holdout_use"] == "new_operational_holdout" and any(
                (main/task/"evaluation").exists() for task in plan["tasks"]):
            raise ValueError("operational companion must be fitted before main heldout scoring")
        root.mkdir(parents=True)
        write_json(root/"study-plan.json", plan)
        write_json(root/"source-load-cost.json", load_cost)
    if phase in ("prepare", "all"):
        for task, original in originals.items():
            destination = root/task/"prepared"
            if destination.exists():
                validate_task_preparation(verify_lexical_prepared(destination), original, task,
                                          plan["main_prepared_seals"][task], by_id)
                continue
            if plan["holdout_use"] == "new_operational_holdout" and any(
                    (main/t/"evaluation").exists() for t in plan["tasks"]):
                raise ValueError("cannot fit a missing operational lexical task after main heldout scoring")
            start, cpu = time.perf_counter_ns(), time.process_time_ns()
            p = original["plan"]
            tr, cr = ([public[s] for s in p[key]] for key in ("tuning_source_ids", "calibration_source_ids"))
            if ({r["group_id"] for r in tr} & {r["group_id"] for r in cr}
                    or {full_normalized_text(r["text"]) for r in tr} & {full_normalized_text(r["text"]) for r in cr}):
                raise ValueError("complete source changes tune/calibration isolation")
            ty, cy = (np.array([by_id[r["source_id"]]["labels"][task] for r in rows]) for rows in (tr, cr))
            tw, cw = group_weights(tr), group_weights(cr)
            if any(by_id[r["source_id"]]["split"] != "calibration" for r in tr+cr):
                raise ValueError("tuning/calibration selections include a non-calibration row")
            prepared_plan = {"task_id": task, "family_id": plan["families"][task],
                "tuning_source_ids": p["tuning_source_ids"], "calibration_source_ids": p["calibration_source_ids"],
                "source_main_prepared_seal_sha256": plan["main_prepared_seals"][task],
                "configuration": plan["protocol"], "holdout_supplied_to_preparation": False}
            runs = []
            for run in original["runs"]:
                ids = run["training_source_ids"]
                rows = [public[s] for s in ids]
                y = np.array([by_id[s]["labels"][task] for s in ids])
                if any(by_id[s]["split"] != "train" for s in ids):
                    raise ValueError("full-text training selection includes a non-training source")
                with np.load(main/task/"prepared"/run["directory"]/"baseline.npz", allow_pickle=False) as saved:
                    if not np.array_equal(y, saved["labels"]):
                        raise ValueError("complete-source training labels differ from frozen primary selection")
                baseline = FullTextLexical(y, rows)
                arms = {}
                for arm in ("exact", "bm25"):
                    tune, cal = baseline.predict(arm, tr), baseline.predict(arm, cr)
                    fit = _calibrate(cal["logits"], cy, cw)
                    arms[arm] = {"calibration": fit, "trainable_parameters": 0,
                        "selection_score_not_used": weighted_nll(prior_corrected_logits(
                            tune["logits"], [.5, .5], smoothed_prior(ty, tw)), ty, tw),
                        "tuning_prediction_cost": tune["cost"], "calibration_prediction_cost": cal["cost"]}
                runs.append({"seed": run["seed"], "budget": run["budget"], "directory": run["directory"],
                    "training_source_ids": ids, "training_labels": y.tolist(), "arms": arms,
                    "baseline_fit_once_cost": baseline.fit_cost, "baseline_retained_state": baseline.memory})
            destination.mkdir(parents=True)
            frozen = {"plan": prepared_plan, "runs": runs, "unavailable": original["unavailable"],
                "wall_ns": time.perf_counter_ns()-start, "cpu_ns": time.process_time_ns()-cpu,
                "all_choices_frozen_before_companion_scoring": True}
            write_json(destination/"frozen.json", frozen)
            write_json(destination/"seal.json", {"schema": "hepta.full-text-lexical-preparation-seal.v1", "files": inventory(destination)})
        if (any(sha_file(path) != digest for path, digest in files.items())
                or code_hashes() != plan["main_code_sha256"]
                or any(sha_file(Path(__file__).with_name(n)) != digest for n, digest in current_code.items())
                or any(verify_prepared(main/t/"prepared") != original for t, original in originals.items())):
            raise ValueError("source inputs or frozen implementation changed during lexical preparation")
        frozen_selection = {"all_declared_tasks_frozen_before_any_evaluation": True,
            "seals": {f"{t}/prepared/seal.json": sha_file(root/t/"prepared/seal.json") for t in originals}}
        if (root/"selection-seal.json").exists():
            if json.loads((root/"selection-seal.json").read_bytes()) != frozen_selection:
                raise ValueError("full-text choices changed after freeze")
        else:
            write_json(root/"selection-seal.json", frozen_selection)
    if phase == "prepare":
        return {"status": "prepared", "output": str(root)}
    evaluated_selection = {"all_declared_tasks_frozen_before_any_evaluation": True,
        "seals": {f"{t}/prepared/seal.json": sha_file(root/t/"prepared/seal.json") for t in originals}}
    if json.loads((root/"selection-seal.json").read_bytes()) != evaluated_selection:
        raise ValueError("full-text selection seal changed before scoring")
    if not (root/"evaluation-source-load-cost.json").exists():
        write_json(root/"evaluation-source-load-cost.json", {
            **load_cost, "wall_ns": 0 if newly_created else load_cost["wall_ns"],
            "cpu_ns": 0 if newly_created else load_cost["cpu_ns"],
            "reused_from_same_invocation_preparation": newly_created,
            "original_preparation_load_cost": "source-load-cost.json"})
    reports = {}
    for task in plan["tasks"]:
        prepared, destination = root/task/"prepared", root/task/"evaluation"
        frozen = verify_lexical_prepared(prepared)
        validate_task_preparation(frozen, originals[task], task, plan["main_prepared_seals"][task], by_id)
        if destination.exists():
            if json.loads((destination/"seal.json").read_bytes()) != {
                    "schema": "hepta.calibrated-evaluation-seal.v1", "files": inventory(destination)}:
                raise ValueError("full-text evaluation inventory changed")
            reports[task] = json.loads((destination/"report.json").read_bytes())
            continue
        ids = [r["source_id"] for r in data["rows"] if r["split"] == "holdout" and r.get("labels", {}).get(task) is not None]
        rows, y = [public[s] for s in ids], np.array([by_id[s]["labels"][task] for s in ids])
        destination.mkdir(parents=True)
        start, cpu = time.perf_counter_ns(), time.process_time_ns()
        report = {"plan": {"family_id": plan["families"][task], "task_id": task,
            "prepared_seal_sha256": sha_file(prepared/"seal.json"), "holdout_use": plan["holdout_use"],
            "no_calibration_or_hyperparameter_fit_in_evaluation": True},
            "source_ids": ids, "group_ids": [r["group_id"] for r in rows], "labels": y.tolist(),
            "runs": [], "unavailable": frozen["unavailable"], "quality_qualified": False}
        for run in frozen["runs"]:
            location = destination/run["directory"]
            location.mkdir()
            baseline = FullTextLexical(np.array(run["training_labels"]), [public[s] for s in run["training_source_ids"]])
            result = {"seed": run["seed"], "budget": run["budget"], "directory": run["directory"],
                "selected_arm": "not_selected", "arms": {}, "baseline_reconstruction_cost": baseline.fit_cost}
            for arm, spec in run["arms"].items():
                prediction = baseline.predict(arm, rows)
                fit = spec["calibration"]
                p = probabilities(apply_calibrator_logits(prediction["logits"], fit))
                scored = _record(location, arm, prediction["logits"], p, y, prediction["eligible"], fit["prior"], plan["protocol"]["threshold"])
                scored.update(calibration=fit, trainable_parameters=0,
                    retrieved_source_ids=prediction["retrieved_source_ids"],
                    baseline_prediction_cost=prediction["cost"], predictor_scope="complete source text, maximum128KiB")
                result["arms"][arm] = scored
            report["runs"].append(result)
        report.update(wall_ns=time.perf_counter_ns()-start, cpu_ns=time.process_time_ns()-cpu,
                      fresh_process_child_cpu_ns=0)
        write_json(destination/"report.json", report)
        write_json(destination/"seal.json", {"schema": "hepta.calibrated-evaluation-seal.v1", "files": inventory(destination)})
        reports[task] = report
    if (any(sha_file(path) != digest for path, digest in files.items())
            or code_hashes() != plan["main_code_sha256"]
            or any(sha_file(Path(__file__).with_name(n)) != digest for n, digest in current_code.items())
            or any(verify_prepared(main/t/"prepared") != original for t, original in originals.items())):
        raise ValueError("complete source changed during lexical companion")
    if (json.loads((root/"selection-seal.json").read_bytes()) != evaluated_selection
            or any(sha_file(root/path) != digest for path, digest in evaluated_selection["seals"].items())):
        raise ValueError("full-text prepared selection changed during scoring")
    for task in plan["tasks"]:
        validate_task_preparation(verify_lexical_prepared(root/task/"prepared"), originals[task],
                                  task, plan["main_prepared_seals"][task], by_id)
    summary = {"plan": plan, "tasks_evaluated": list(reports), "unavailable_tasks": [],
        "unavailable_budgets": {t: r["unavailable"] for t, r in reports.items()},
        "source_load_cost_sha256": {name: sha_file(root/name) for name in
            ("source-load-cost.json", "evaluation-source-load-cost.json")},
        "selection_seal_sha256": sha_file(root/"selection-seal.json"), **compact_summary(reports)}
    if (root/"summary.json").exists():
        if json.loads((root/"summary.json").read_bytes()) != summary:
            raise ValueError("existing complete-text summary changed")
    else:
        write_json(root/"summary.json", summary)
    return summary


def verify_reuse(companion, other_study, output):
    """Bind an existing lexical result to another encoder's identical source draws."""
    root, other = Path(companion), Path(other_study)
    blobs = {str(p): p.read_bytes() for p in (root/"study-plan.json", root/"summary.json",
        root/"selection-seal.json", other/"study-plan.json", other/"selection-seal.json")}
    plan = json.loads(blobs[str(root/"study-plan.json")])
    other_plan = json.loads(blobs[str(other/"study-plan.json")])
    if json.loads(blobs[str(root/"summary.json")])["plan"] != plan:
        raise ValueError("completed lexical summary differs from its source plan")
    if any(plan[key] != other_plan[key] for key in
           ("dataset_sha256", "tasks", "families", "protocol", "holdout_use")):
        raise ValueError("lexical reuse requires matching dataset, tasks and fixed protocol")
    bindings = {path: hashlib.sha256(blob).hexdigest() for path, blob in blobs.items()}
    for base in (root, other):
        selection = json.loads(blobs[str(base/"selection-seal.json")])
        if selection != {"all_declared_tasks_frozen_before_any_evaluation": True,
                "seals": {f"{t}/prepared/seal.json": sha_file(base/t/"prepared/seal.json") for t in plan["tasks"]}}:
            raise ValueError("lexical reuse source selections are not sealed")
    for task in plan["tasks"]:
        frozen = verify_lexical_prepared(root/task/"prepared")
        target = verify_prepared(other/task/"prepared")
        for field in ("tuning_source_ids", "calibration_source_ids"):
            if frozen["plan"][field] != target["plan"][field]:
                raise ValueError("lexical reuse changes tuning/calibration source selections")
        if (frozen["unavailable"] != target["unavailable"]
                or [(r["seed"], r["budget"], r["training_source_ids"]) for r in frozen["runs"]]
                   != [(r["seed"], r["budget"], r["training_source_ids"]) for r in target["runs"]]):
            raise ValueError("lexical reuse changes frozen gradient training source draws")
        for run in frozen["runs"]:
            with np.load(other/task/"prepared"/run["directory"]/"baseline.npz", allow_pickle=False) as saved:
                if saved["labels"].tolist() != run["training_labels"]:
                    raise ValueError("lexical reuse changes training labels")
        evaluation = root/task/"evaluation"
        if json.loads((evaluation/"seal.json").read_bytes()) != {
                "schema": "hepta.calibrated-evaluation-seal.v1", "files": inventory(evaluation)}:
            raise ValueError("reused lexical prediction inventory changed")
        for path in (root/task/"prepared/seal.json", other/task/"prepared/seal.json", evaluation/"seal.json"):
            bindings[str(path)] = sha_file(path)
    if (any(sha_file(path) != digest for path, digest in plan["source_files_sha256"].items())
            or any(sha_file(path) != digest for path, digest in bindings.items())):
        raise ValueError("reused lexical complete sources or evidence bindings changed")
    report = {"schema": "hepta.full-text-lexical-reuse.v1", "source_bindings_sha256": bindings,
        "matched_training_tuning_calibration_source_selections": True,
        "numerical_refitting_count": 0, "encoder_forward_calls": 0,
        "cost_policy": "charge original lexical preparation/evaluation once; this receipt reuses sealed predictions"}
    write_json(Path(output), report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("dataset", "main-study", "output"):
        parser.add_argument(f"--{key}", required=True)
    for key in ("head-view", "archive", "source-receipt"):
        parser.add_argument(f"--{key}")
    parser.add_argument("--phase", choices=("prepare", "evaluate", "all"), default="prepare")
    args = parser.parse_args()
    result = run_companion(args.dataset, args.main_study, args.output, phase=args.phase,
        head_view=args.head_view, archive=args.archive, source_receipt=args.source_receipt)
    print(json.dumps({"status": result.get("status", "complete"), "output": args.output}), flush=True)


if __name__ == "__main__":
    main()
