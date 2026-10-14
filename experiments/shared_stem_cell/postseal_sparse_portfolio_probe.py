"""Retrospective shared-Head/sparse-residual study over original sealed predictions.

This DOES NOT train, generate fresh predictions, validate independent sources,
create a production selection, or assert a newly blinded outcome. The public
evaluation records were previously exposed: the result is hypothesis discovery.

First compute a deterministic per-Cell portfolio from the 512 confirmation
labels ONLY; write its immutable selection BEFORE opening the evaluation label
file; then audit all 1024 original predictions and score the fixed portfolio.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path

from experiments.shared_stem_cell import postseal_historical_audit as a

SCHEMA = "hepta.retrospective-sparse-cell-portfolio.v1"
ARMS = ("bank", "shared", "residual_corrected")
EXPECTED_PER_PHASE = 512


def counts(lock):
    if (not isinstance(lock, dict) or lock.get("profile", {}).get("classes") != 4
            or lock.get("selected") != "residual_corrected"):
        raise a.AuditError("historical frozen profile required")
    params = lock.get("parameter_counts")
    if not isinstance(params, dict) or set(params) != {
            "bank", "shared", "linear_distilled", "residual_corrected"}:
        raise a.AuditError("complete original Head parameter inventory required")
    if any(type(v) is not int or v <= 0 for v in params.values()):
        raise a.AuditError("nonpositive or retyped parameter count")
    if (params["bank"] % 2 or
            (params["residual_corrected"] - params["shared"]) % 2):
        raise a.AuditError("nonintegral physical per-Cell Head inventory")
    bank = params["bank"] // 2
    residual = (params["residual_corrected"] - params["shared"]) // 2
    if (bank <= 0 or residual <= 0 or
            params["residual_corrected"] != params["shared"] + 2 * residual):
        raise a.AuditError("invalid shared/residual composition")
    return {"bank": bank, "shared": params["shared"],
            "residual_corrected": params["shared"] + residual}, {
                "bank_per_cell": bank, "shared_once": params["shared"],
                "residual_per_cell": residual, "original_bank": params["bank"]}


def freeze_from_confirmation(lock, cohort, predictions, confirmation):
    """Decision deliberately has NO report/evaluation-label argument."""
    marginal, sizes = counts(lock)
    if (not isinstance(cohort, list) or len(cohort) != 1024 or
            not isinstance(predictions, dict) or not isinstance(confirmation, dict)
            or predictions.get("case_ids") != [row["case_id"] for row in cohort]
            or not isinstance(predictions.get("predictions"), dict) or
            set(predictions["predictions"]) != {
                "bank", "shared", "residual_corrected", "linear_distilled"}):
        raise a.AuditError("incomplete sealed historical confirmation inputs")
    phases = {phase: [i for i, item in enumerate(cohort)
                      if item["split"] == phase]
              for phase in ("confirmation", "evaluation")}
    if (any(len(phases[phase]) != EXPECTED_PER_PHASE for phase in phases)
            or sum(len(v) for v in phases.values()) != len(cohort)
            or any(Counter(cohort[i]["cell"] for i in phase) != {0: 256, 1: 256}
                   for phase in phases.values())
            or len(set(row["case_id"] for row in cohort)) != len(cohort)
            or len(confirmation.get("confirmation_labels", [])) != EXPECTED_PER_PHASE
            or confirmation.get("confirmation_ids") != [
                cohort[i]["case_id"] for i in phases["confirmation"]]):
        raise a.AuditError("phase/Cell cohort identity or size changed")
    labels = confirmation["confirmation_labels"]
    classes = lock["profile"]["classes"]
    chosen, calibration = {}, {}
    for cell in (0, 1):
        relative = [j for j, pos in enumerate(phases["confirmation"])
                    if cohort[pos]["cell"] == cell]
        absolute = [phases["confirmation"][j] for j in relative]
        targets = [labels[j] for j in relative]
        views = {}
        for arm in ARMS:
            all_rows = predictions["predictions"][arm]
            if type(all_rows) is not list or len(all_rows) != 1024:
                raise a.AuditError("missing complete frozen Head predictions")
            value, _ = a.score([all_rows[i] for i in absolute], targets,
                               [cell] * len(absolute), classes)
            views[arm] = value["correct"]
        selection = min(ARMS, key=lambda arm: (-views[arm], marginal[arm], arm))
        chosen[str(cell)] = selection
        calibration[str(cell)] = {"correct_by_arm": views,
                                  "cases": len(relative), "selected": selection}
    deployed = (sizes["shared_once"] if any(v != "bank" for v in chosen.values())
                else 0)
    deployed += sum(sizes["bank_per_cell"] for v in chosen.values() if v == "bank")
    deployed += sum(sizes["residual_per_cell"] for v in chosen.values()
                    if v == "residual_corrected")
    # Baseline-correct portfolios are not automatically smaller. Record even
    # infeasible outcomes rather than changing the selected arm post-hoc.
    return {
        "schema": SCHEMA,
        "selection_rule": "per_cell_confirmation_correct_desc_then_standalone_head_params_asc",
        "candidate_arms": list(ARMS),
        "chosen_per_cell": chosen, "confirmation_per_cell": calibration,
        "parameter_components": sizes, "deployed_head_parameters": deployed,
        "bank_head_parameters": sizes["original_bank"],
        "head_bytes_if_f32": deployed * 4,
        "strict_parameter_saving": deployed < sizes["original_bank"],
        "new_training_steps": 0, "eval_labels_accessed_during_selection": False,
        "selection_is_retrospective_not_prospective": True,
        "independent_source_families_verified": False,
        "production_accepted": False,
    }


def _sealed_json(path, payload):
    """Exactly-once result publication. An existing path cannot be overwritten."""
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False) + "\n").encode()
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return a.digest(raw)


def run(archive, zip_sha256, output):
    inp = a.Input(archive, zip_sha256)
    files = ("candidate-lock.json", "cohort.json", "predictions.json",
             "confirmation.json")
    raw = {name: inp.read(a.PREFIX + name) for name in files}
    lock, cohort, pred, confirmation = (
        a.strict_json(raw[name]) for name in files)
    if (pred.get("candidate_lock_sha256") != a.digest(raw["candidate-lock.json"])
            or pred.get("cohort_sha256") != a.digest(raw["cohort.json"])
            or confirmation.get("candidate_lock_sha256") !=
            a.digest(raw["candidate-lock.json"])
            or confirmation.get("predictions_sha256") !=
            a.digest(raw["predictions.json"])
            or confirmation.get("proposed") != lock.get("selected")):
        raise a.AuditError("original pre-evaluation materials are not hash-bound")
    selection = freeze_from_confirmation(lock, cohort, pred, confirmation)
    selection["source_sha256"] = {name: a.digest(value) for name, value in raw.items()}
    selection["original_archive_sha256"] = inp.archive_sha256
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    selection_sha = _sealed_json(output / "selection.json", selection)
    # First access to the old evaluation labels is BELOW the frozen selection.
    # Since these public labels have already been exposed, no blind claim follows.
    prior = a.audit(archive, zip_sha256)
    report = a.strict_json(inp.read(a.PREFIX + "report.json"))
    if (prior["chosen"] != "bank" or report.get("retention_certified") is not False
            or report.get("production_accepted") is not False):
        raise a.AuditError("historical failed release gate must remain unchanged")
    indices = [i for i, row in enumerate(cohort) if row["split"] == "evaluation"]
    labels = report["evaluation_labels"]
    own = [pred["predictions"][selection["chosen_per_cell"][str(cohort[i]["cell"])]][i]
           for i in indices]
    base = [pred["predictions"]["bank"][i] for i in indices]
    cell_ids = [cohort[i]["cell"] for i in indices]
    classes = lock["profile"]["classes"]
    actual, flags = a.score(own, labels, cell_ids, classes)
    bank, old_flags = a.score(base, labels, cell_ids, classes)
    by_cell = []
    for cell in (0, 1):
        locations = [j for j, c in enumerate(cell_ids) if c == cell]
        wins = sum(flags[j] and not old_flags[j] for j in locations)
        losses = sum(old_flags[j] and not flags[j] for j in locations)
        by_cell.append({"cell": cell, "cases": len(locations), "gains": wins,
                        "losses": losses, "net_correct": wins - losses})
    result = {
        "schema": "hepta.retrospective-sparse-cell-portfolio-result.v1",
        "selection_sha256": selection_sha,
        "source_historical_audit_sha256": a.digest(
            json.dumps(prior, sort_keys=True, allow_nan=False).encode()),
        "original_archive_sha256": inp.archive_sha256,
        "original_bank_score": bank, "retrospective_portfolio_score": actual,
        "descriptive_paired_deltas": by_cell,
        "hypothetical_head_forwards": sum(
            2 if selection["chosen_per_cell"][str(c)] == "residual_corrected"
            else 1 for c in cell_ids),
        "actual_new_model_forward_calls": 0,
        "new_model_training": False, "new_outcome_observations": False,
        "external_independent_evaluation": False,
        "new_blind_holdout": False, "production_accepted": False,
    }
    _sealed_json(output / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--zip-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.root, args.zip_sha256, args.output)
    print(json.dumps({"retrospective_correct": result["retrospective_portfolio_score"]["correct"],
                      "bank_correct": result["original_bank_score"]["correct"],
                      "production_accepted": False}, sort_keys=True))


if __name__ == "__main__":
    main()
