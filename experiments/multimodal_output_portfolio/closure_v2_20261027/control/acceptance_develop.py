"""Historical-only feasibility for selective final commitment."""

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from ...continuation_20261027.joint.run import reference_observer
from .acceptance_features import category, observed_semantics
from .protocol import preserve_sources, sha, write
from .tasks import load_tasks
from .verify_media import independent_score


SPEC = {
    "schema": "hepta.ndu.selective-semantic-acceptance-development.v1",
    "phase": "Historical fitting/validation only; no new qualification source allocated",
    "feature_visibility": "Initial actual caption, arrived scalar, actual candidate pixels/text, public missingness",
    "predictor_timing": "After candidate codec readback, before final commit and private candidate grade",
    "private_truth_role": "Training/validation supervision only",
    "threshold_candidates": [0.5, 0.7, 0.8, 0.9, 0.95, 0.97, 0.98, 0.99, 0.995, 0.999],
    "selection": "Highest validation ID coverage subject to zero incorrect semantic commits, coverage>=.25; ties lower threshold",
    "id_minimum_coverage": 0.25,
    "legacy_ece_maximum": 0.03,
    "legacy_ood_false_acceptance_maximum": 0.004999,
    "legacy_ood_one_sided_95_upper_required": True,
    "new_incorrect_semantic_commit_rate_maximum": 0.004999,
    "semantic_qualification_is_native_production_calibration": False,
    "new_test_outcomes_used": False,
    "remaining_if_feasible": "Separate source-disjoint probability calibration and then once-only fresh qualification; original failed result remains unchanged",
}


def run(assets, development, output):
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    write(output / "PROTOCOL.json", SPEC)
    preserve_sources(output / "executed-source")
    reward, audit = reference_observer(assets, "reward"), reference_observer(assets, "audit")
    heads = json.loads((development / "READOUT_FIT.json").read_text())
    records = []
    for split, filename in (("fit", "FIT.json"), ("validation", "VALIDATION.json")):
        tasks = load_tasks(development / f"{split}-inputs")
        actual = json.loads((development / filename).read_text())
        for row in actual:
            task = tasks[row["index"]]
            proposed = heads["native_by_feedback"][str(row["feedback"])]["proposal"]
            admitted = proposed and task["expires"] >= 7 and task["budget"] >= 2
            candidate = row["alternate_delivery"] if admitted else row["initial_delivery"]
            features = observed_semantics(row["initial_delivery"], candidate, row["feedback"], task["public"].observation, reward)
            grade = independent_score(audit, candidate, task["private"].pixels.numpy(), task["private"].labels[0].tolist())
            records.append({"split": split, "index": row["index"], "source_ids": row["source_ids"],
                "features": features, "strict_success": grade["strict_success"], "actual_candidate": candidate["sha256"],
                "actual_native_continuation_choice": int(admitted)})
    candidates = []
    for threshold in SPEC["threshold_candidates"]:
        summaries = {}
        for split in ("fit", "validation"):
            selected = [row for row in records if row["split"] == split]
            accepted = [row for row in selected if category(row["features"], threshold) == "selective_candidate"]
            errors = sum(not row["strict_success"] for row in accepted)
            summaries[split] = {"n": len(selected), "accepted": len(accepted), "incorrect_commits": errors,
                "coverage": len(accepted) / len(selected), "incorrect_commit_rate": errors / len(selected)}
        candidates.append({"threshold": threshold, **summaries})
    feasible = [row for row in candidates if row["validation"]["incorrect_commits"] == 0
                and row["validation"]["coverage"] >= SPEC["id_minimum_coverage"]]
    chosen = min(feasible, key=lambda row: (-row["validation"]["coverage"], row["threshold"])) if feasible else None
    write(output / "FEATURE_ROWS.json", records)
    result = {"feasible_for_fresh_calibration": chosen is not None, "selected": chosen, "all_candidates": candidates,
        "feature_rows_sha256": sha(output / "FEATURE_ROWS.json"), "readout_sha256": sha(development / "MODEL.json"),
        "qualifications_consumed": 0, "qualification_semantics": "New selective candidate commitment; does not alter the previous continuation's failed semantic admission result"}
    write(output / "RESULT.json", result)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("assets", "development", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.assets, args.development, args.output)
