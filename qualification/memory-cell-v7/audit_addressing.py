"""Audit saved V7 language decisions and costs without running a model.

This module reads frozen artifacts only. It never imports the learner, encoder,
planner, or author generator, changes labels, or executes memory fixtures.
"""

from collections import Counter
import hashlib
import json
import math
import unicodedata


RUNS = ("v7-addressing-development-01", "v7-addressing-development-02", "v7-addressing-formal-01")
OPERATIONS = ("current", "history", "semantic", "procedure", "change", "apply")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def metrics(rows, decisions):
    known = [i for i, row in enumerate(rows) if row["operation"] in OPERATIONS]
    ood = [i for i, row in enumerate(rows) if row["operation"] == "reject"]
    correct = sum(decisions[i]["operation"] == rows[i]["operation"] for i in known)
    wrong = sum(decisions[i]["operation"] not in (None, rows[i]["operation"]) for i in known)
    accepted = sum(decisions[i]["operation"] is not None for i in ood)
    language = {}
    for name in sorted({row["language"] for row in rows}):
        subset = [i for i in known if rows[i]["language"] == name]
        if subset:
            language[name] = sum(decisions[i]["operation"] == rows[i]["operation"] for i in subset) / len(subset)
    return {"known_rows": len(known), "known_correct": correct, "known_wrong_accepted": wrong,
            "known_correct_rate": correct / max(len(known), 1), "known_wrong_rate": wrong / max(len(known), 1),
            "ood_rows": len(ood), "ood_accepted": accepted, "ood_acceptance_rate": accepted / max(len(ood), 1),
            "language_known_correct_rates": language}


def stored_policy(hypotheses, threshold, margin):
    return [{"operation": h["raw_operation"] if h["raw_operation"] in OPERATIONS
             and h["score"] >= threshold and h["margin"] >= margin else None} for h in hypotheses]


def abstract_gold(row):
    """Check author arithmetic only; this is not native memory execution."""
    expected = row["expected"]
    entity = next(item for item in row["memory_fixture"]["entities"] if item["entity"] == expected["canonical_entity"])
    events = entity["events"]
    latest = max(events, key=lambda event: event["date"])["value"]
    semantic, program = entity["current_semantic"], entity["current_procedure"]
    operation = expected["operation"]
    if operation == "current":
        return latest
    if operation == "semantic":
        return semantic
    if operation == "procedure":
        return program
    if operation == "apply":
        require(program["fixture_kind"] == "affine_then_upper_cap", "unknown abstract program")
        return min(latest * semantic["factor"] + semantic["bias"], semantic["limit"])
    boundary = row["request"]["at" if operation == "history" else "since"]
    prior = max((event for event in events if event["date"] <= boundary), key=lambda event: event["date"])["value"]
    return prior if operation == "history" else latest - prior


def audit(base, repo):
    costs, models, selection_checks = [], [], 0
    for name in RUNS:
        root = base / name
        training = read(root / "TRAINING.json")
        require(training["source"] == read(root / "DESIGN.json"), name + " design differs")
        require(training["candidates"] == read(root / "PROGRESS.json"), name + " progress differs")
        lock = read(root / "SELECTION_LOCK.json")
        require(sha(canonical(training["candidates"])) == lock["all_candidates_sha256"], name + " selection lock differs")
        for relative, expected in training["source"]["source_files"].items():
            require(sha((root / "execution-sources" / relative).read_bytes()) == expected, name + " source snapshot differs")
        rows = read(root / "selection.json")
        require(sha(canonical(rows)) == lock["selection_sha256"], name + " selection input differs")
        heads, candidates = [], []
        for candidate in training["candidates"]:
            directory = root / candidate["directory"]
            manifest = read(directory / "manifest.json")
            manifest_hash = sha((directory / "manifest.json").read_bytes())
            require(manifest_hash == candidate["identity"]["manifest_sha256"], name + " candidate identity differs")
            weights = (directory / "weights.npz").read_bytes()
            require(sha(weights) == manifest["weights_sha256"] and len(weights) == manifest["weights_bytes"], name + " candidate weights differ")
            hypotheses = read(directory / "selection-hypotheses.json")
            selection = read(directory / "SELECTION.json")
            require(len(hypotheses) == len(rows), "selection hypotheses count differs")
            require(selection["selected"] == candidate["selection"], "stored selected policy differs")
            for trial in selection["trials"]:
                require(metrics(rows, stored_policy(hypotheses, trial["threshold"], trial["margin"])) == trial["metrics"], "stored selection counts differ")
                selection_checks += 1
            require(max(selection["trials"], key=lambda trial: trial["selection_key"]) == selection["selected"], "policy selection is not recorded argmax")
            for head in candidate["training"]["heads"]:
                require(head["actual_fit"] is True and all(math.isfinite(head[field]) and head[field] >= 0 for field in ("cpu_seconds", "wall_seconds")), "invalid fit receipt")
                heads.append({"candidate": candidate["candidate"], "kind": candidate["kind"], "C": candidate["C"], **head})
            candidates.append({"candidate": candidate["candidate"], "kind": candidate["kind"], "C": candidate["C"],
                               "cpu_seconds": candidate["cpu_seconds"], "wall_seconds": candidate["wall_seconds"]})
            models.append({"run": name, "directory": candidate["directory"], "manifest_sha256": manifest_hash,
                           "weights_sha256": sha(weights), "weights_bytes": len(weights), "kind": manifest["kind"], "C": manifest["C"],
                           "selection_sha256": sha((directory / "SELECTION.json").read_bytes()),
                           "selection_hypotheses_sha256": sha((directory / "selection-hypotheses.json").read_bytes())})
        require(len(heads) == training["actual_head_fits"] == 12, "actual fit count differs")
        chosen = max(training["candidates"], key=lambda c: (*c["selection"]["selection_key"], -c["identity"]["deployment_bytes_excluding_base"], -c["candidate"]))
        require(chosen["candidate"] == training["selected_candidate"] == lock["selected_candidate"], "candidate selection differs")
        selected = root / ("selected-unadmitted" if training.get("serving_admitted") is False else "selected")
        selected_manifest = read(selected / "manifest.json")
        require(sha((selected / "manifest.json").read_bytes()) == training["selected_identity"]["manifest_sha256"], "selected identity differs")
        selected_weights = (selected / "weights.npz").read_bytes()
        require(sha(selected_weights) == selected_manifest["weights_sha256"] and len(selected_weights) == selected_manifest["weights_bytes"], "selected weights differ")
        require(selected_weights == (root / chosen["directory"] / "weights.npz").read_bytes(), "selection/calibration changed fitted weights")
        models.append({"run": name, "directory": selected.name, "manifest_sha256": training["selected_identity"]["manifest_sha256"],
                       "weights_sha256": selected_manifest["weights_sha256"], "weights_bytes": selected_manifest["weights_bytes"],
                       "kind": selected_manifest["kind"], "C": selected_manifest["C"],
                       "calibration": selected_manifest["calibration"], "serving_admitted": selected_manifest["calibration"] is not None})
        if training["calibration"] is not None:
            calibration = read(root / "CALIBRATION.json")
            calibration_rows = read(root / "calibration.json")
            observations = read(root / "calibration-readouts.json")
            require(calibration == training["calibration"] == selected_manifest["calibration"], "calibration report differs")
            require(sha(canonical(calibration_rows)) == calibration["calibration_sha256"], "calibration input identity differs")
            require([row["id"] for row in calibration_rows] == [row["id"] for row in observations], "calibration row IDs differ")
            require(metrics(calibration_rows, [row["decision"] for row in observations]) == calibration["metrics"], "calibration counts differ")
        costs.append({"run": name, "training_receipt_sha256": sha((root / "TRAINING.json").read_bytes()),
                      "source_commit": training["source"]["source_commit"], "source_committed_at_execution": training["source"]["execution_source_is_committed"],
                      "head_fit_calls": len(heads), "head_receipts": heads, "candidate_inclusive_receipts": candidates,
                      "head_cpu_seconds": sum(head["cpu_seconds"] for head in heads), "head_wall_seconds": sum(head["wall_seconds"] for head in heads),
                      "encoding": training["encoding"], "calibration_cost": training.get("calibration_cost"),
                      "calibration_outcome": training["calibration"], "selected_manifest_sha256": training["selected_identity"]["manifest_sha256"],
                      "run_cpu_seconds_before_final_report": training["total_cpu_seconds_before_final_report"],
                      "run_wall_seconds_before_final_report": training["total_wall_seconds_before_final_report"],
                      "recorded_retained_bytes_before_final_report": training["retained_bytes_before_final_report"]})

    author = base / "v7-independent-eval-author"
    for relative, binding in read(author / "VALIDATION.json")["files"].items():
        raw = (author / relative).read_bytes()
        require(len(raw) == binding["bytes"] and sha(raw) == binding["sha256"], "author file identity differs")
    held = read(author / "held.json")
    root = base / "v7-addressing-held-01"
    result, execution = read(root / "RESULT.json"), read(root / "EXECUTION.json")
    lock_path = repo / "qualification/memory-cell-v7/evidence/addressing-HELD_LOCK.json"
    locked = read(lock_path)
    require(result["lock_sha256"] == sha(lock_path.read_bytes()), "held lock identity differs")
    require(result["held_sha256"] == locked["held_sha256"] == sha((author / "held.json").read_bytes()), "held corpus identity differs")
    require(result["evaluator_sha256"] == sha((repo / "qualification/memory-cell-v7/address_eval.py").read_bytes()), "evaluator source differs")
    require(result["model_digest"] == locked["model"]["manifest_sha256"] == costs[-1]["selected_manifest_sha256"], "held model differs")
    require(execution["held_opened"] is False and result["held_opened"] is True, "execution records inconsistent")
    intents = [row for part in sorted(root.glob("intent-readouts-*.json")) for row in read(part)]
    entities = [row for part in sorted(root.glob("entity-readouts-*.json")) for row in read(part)]
    require(len(intents) == len(held["intent_rows"]) == 360 and len(entities) == len(held["entity_rows"]) == 80, "held row count differs")
    for original, saved in zip(held["intent_rows"], intents):
        require(all(saved[key] == value for key, value in original.items()), "intent original label or text changed")
        normalized = unicodedata.normalize("NFKC", original["text"].replace("{entity}", "entity").replace("{at}", "date").replace("{since}", "date")).casefold().strip()
        require(saved["normalized_text"] == normalized, "intent normalization differs")
        decision = saved["decision"]
        require(decision["threshold"] == locked["threshold"] and decision["required_margin"] == 0.0, "held policy changed")
        require(stored_policy([saved["hypothesis"]], decision["threshold"], decision["required_margin"])[0]["operation"] == decision["operation"], "saved decision inconsistent with frozen threshold")
    decisions = [row["decision"] for row in intents]
    require(metrics(intents, decisions) == result["intent_gate"], "held aggregate counts differ")
    for field in ("operation", "language", "family"):
        for value, reported in result["intent_by_" + field].items():
            subset = [row for row in intents if row[field] == value]
            require(metrics(subset, [row["decision"] for row in subset]) == reported, "held subgroup counts differ")
    positive, negative = [], []
    for original, saved in zip(held["entity_rows"], entities):
        require(saved["id"] == original["id"] and saved["expected"] == original["expected"] and saved["original_request"] == original["request"], "entity original fields changed")
        corrected = dict(original["request"])
        corrected.pop("schema")
        corrected["max_cells"] = min(corrected["max_cells"], 8)
        require(saved["diagnostic_request"] == corrected, "diagnostic changed more than declared uniform budget")
        require(saved["strict_resolution"] == {"entity": None, "error": "invalid max cells"}, "strict rejection differs")
        name = unicodedata.normalize("NFKC", original["request"]["entity"]).casefold().strip()
        matches = {entry["entity"] for entry in original["registry"]["entities"]
                   if name in {unicodedata.normalize("NFKC", alias).casefold().strip() for alias in (entry["entity"], *entry["aliases"])}}
        expected = original["expected"]
        if expected["canonical_entity"] is not None:
            require(matches == {expected["canonical_entity"]}, "author unique alias gold differs")
            require(expected["result"] == abstract_gold(original), "author abstract arithmetic gold differs")
            positive.append(saved)
        else:
            require(len(matches) != 1 and expected["result"] is None, "author rejection gold differs")
            negative.append(saved)
    accepted = [row for row in positive if row["diagnostic_plan"]["status"] == "accepted"]
    correct_plans = [row for row in accepted if row["diagnostic_plan"]["plan"]["operation"] == row["expected"]["operation"]
                     and row["diagnostic_plan"]["request"]["entity"] == row["expected"]["canonical_entity"]]
    require(len(correct_plans) == result["diagnostic_known_alias_complete_plan"]["correct_operation_and_owner"] == 11, "diagnostic correct plan count differs")
    alias_correct = sum(row["diagnostic_resolution"]["entity"] == row["expected"]["canonical_entity"] for row in positive)
    negative_accepted = sum(row["diagnostic_resolution"]["entity"] is not None for row in negative)
    require((len(positive), len(negative), alias_correct, negative_accepted) == (40, 40, 40, 0), "diagnostic resolution count differs")
    require(result["head_fit_calls"] == result["parameter_or_policy_changes"] == result["native_fixture_execution"]["executed"] == 0, "held record claims unexpected execution")
    known = [row for row in intents if row["operation"] in OPERATIONS]
    ood_accepts = [row for row in intents if row["operation"] == "reject" and row["decision"]["operation"] is not None]
    cost_summary = {"schema": "hepta.memory.v7.language-cost-audit.v1", "runs": costs,
                    "run_count": len(costs), "actual_head_fit_calls": sum(run["head_fit_calls"] for run in costs),
                    "training_inclusive_cpu_seconds": sum(run["run_cpu_seconds_before_final_report"] for run in costs),
                    "training_inclusive_wall_seconds": sum(run["run_wall_seconds_before_final_report"] for run in costs),
                    "head_fit_only_cpu_seconds": sum(run["head_cpu_seconds"] for run in costs),
                    "head_fit_only_wall_seconds": sum(run["head_wall_seconds"] for run in costs),
                    "held_cpu_seconds_including_load": result["cpu_seconds_including_load"],
                    "held_wall_seconds_including_load": result["wall_seconds_including_load"],
                    "shared_frozen_encoder_bytes": read(base / RUNS[-1] / "TRAINING.json")["base_bytes"],
                    "accounting": ["Run totals include candidate fitting, development encoding, selection and any calibration; do not add nested head/candidate costs again.",
                                   "CPU is recorded Python process_time; wall is recorded perf_counter. Final report serialization, source preservation after training, archiving, environment installation, downloads and human work are excluded.",
                                   "36 head fits are three executions of six candidates with two heads each, not 36 independent language models or independent replications.",
                                   "Base encoder is frozen and its pretraining cost is unmeasured. No full-system cost claim is made."]}
    model_index = {"schema": "hepta.memory.v7.language-model-index.v1", "models": models,
                   "candidate_models": 18, "selected_models": 3,
                   "unique_weight_payloads": len({model["weights_sha256"] for model in models}),
                   "selected_policy_can_differ_despite_identical_weights": True}
    review = {"schema": "hepta.memory.v7.language-evidence-review.v1", "reviewer_scope": "Saved evidence and evaluator source audit; no model execution or label changes.",
              "stored_selection_policies_recounted": selection_checks, "source_snapshot_hashes_match_all_three_runs": True,
              "held_input_and_readout_labels_unchanged": True, "held_readout_rows": 440, "new_model_calls": 0,
              "new_head_fit_calls": 0, "labels_changed": 0, "held_intent": result["intent_gate"],
              "known_abstained": sum(row["decision"]["operation"] is None for row in known),
              "known_explicit_capability_rejections": sum(row["hypothesis"].get("capability_reason") is not None for row in known),
              "known_raw_supported_but_below_threshold_or_margin": sum(row["hypothesis"]["raw_operation"] in OPERATIONS and row["decision"]["operation"] is None for row in known),
              "ood_false_accepts": [{key: row[key] for key in ("id", "text", "family", "decision")} for row in ood_accepts],
              "original_entity_requests": {"rows": 80, "all_max_cells": 32, "runtime_max_cells": 8, "budget_rejections": 80},
              "predeclared_uniform_budget_diagnostic": {"known_aliases": 40, "correct_canonical_entities": alias_correct,
                   "unknown_or_ambiguous": 40, "incorrectly_resolved": negative_accepted,
                   "accepted_positive_plans": len(accepted), "correct_operation_and_entity_plans": len(correct_plans),
                   "native_answers_executed": 0},
              "author_abstract_fixture_gold_matches": 40, "abstract_gold_check_is_native_execution": False,
              "primary_known_gate_passed": False, "sample_ood_gate_passed": True, "complete_original_protocol_passed": False,
              "population_risk_established": False,
              "findings": [
                  "80/240 (33.33%) is correct accepted intent coverage: all 160 abstentions remain in the denominator. Zero accepted wrong known intents is not 100% task accuracy.",
                  "Four OOD intents are accepted (4/120, 3.33%). They remain errors even if a later lookup or execution would fail; their fixed labels are consistent with unsupported percentage, causal explanation and synthetic-input requests.",
                  "The 360-row intent experiment substitutes entity/date markers and evaluates the composite intent/shape classifier plus fixed capability rules. It does not exercise actual alias/date binding or native memory execution for those rows.",
                  "All 80 original entity requests fail the max_cells boundary before name resolution. Negative-case syntax rejection is not evidence of unknown/ambiguous-name detection.",
                  "The pre-held lock separately declared uniform max_cells<=8 diagnostics. Its 40/40 exact alias resolutions and 40/40 negative rejections apply to synthetic owner-listed registries, not open-world entity linking or authenticated owner access.",
                  "The reported 11/40 complete plans mean correct operation and canonical entity only. They do not include memory values, native arithmetic, version admission, or final owner checks.",
                  "The abstract semantic fixture has factor/bias/limit instead of native factor/label, and its saved program representation is not native V1. The original complete-runtime protocol was not executed; all 440 rows retain executed=0.",
                  "Author VALIDATION passed its own structural checks, but did not validate max_cells against the runtime 1..8 bound. Preserve that original verdict together with this incompatibility rather than revising it.",
                  "Development-01 weak calibration (61/120 known, 1/120 OOD), development-02 unadmitted selection, and formal calibration (69/180 known, 6/240 OOD, one wrong accepted known) are retained. None is replaced by the final held result.",
                  "The binomial tolerance calculation needs independent identically distributed calibration sampling for its stated conditional population guarantee; arbitrary exchangeability alone is insufficient. These authored families establish neither assumption, and original reports correctly keep population_risk_established=false.",
                  "The initial development source snapshots were not committed at execution; development-01's later byte-preserving copy receipt remains archived. The formal run records committed source and all preserved source hashes match.",
              ]}
    return cost_summary, model_index, review
