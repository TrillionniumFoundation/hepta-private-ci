"""Retire failed historical calibration, then freeze a new public selector."""

import argparse
import json
from pathlib import Path

import numpy as np

from .acceptance_head import predicted
from .protocol import preserve_sources, sha, write


SPEC = {
    "schema": "hepta.ndu.public-selector-refinement.v2",
    "retirement": "acceptance-calibration-001 failed its nonvacuity gate and is now development only; its original result remains immutable",
    "fixed_head": "Previously fitted ridge10 public reward-observer outcome head; no weight refit",
    "selection_inputs": "Historical fit256, validation128, and retired calibration ID256 only",
    "head_threshold_grid": [round(float(x), 2) for x in np.arange(.5, 1, .05)],
    "public_probability_grid": [round(float(x), 2) for x in np.arange(.8, 1, .01)],
    "eligibility": "Arrived nonzero scalar, matching candidate caption, public reward CNN argmax agreement, both images not declared absent",
    "criterion": "Zero incorrect selections and coverage>=.25 in each of the three historical groups; maximize minimum group coverage, then total selections, then larger public threshold, then larger head threshold",
    "calibration_required": "A disjoint historical source cohort with a new random namespace must calibrate probabilities before any new qualification source is assigned",
    "qualification_outputs_used": False,
    "production_authority_changed": False,
}


def run(head_development, retired_calibration, output):
    output.mkdir(parents=True, exist_ok=False)
    write(output / "PROTOCOL.json", SPEC)
    preserve_sources(output / "executed-source")
    model_path = head_development / "SELECTED_MODEL.json"
    model = json.loads(model_path.read_text())
    data = np.load(head_development / "PUBLIC_FEATURES.npz")
    probabilities = predicted(model, data["features"])
    groups = {}
    for role in ("fit", "validation"):
        chosen = data["role"] == role
        groups[role] = {"eligible": data["eligible"][chosen], "head": probabilities[chosen],
            "public": data["features"][chosen, 3], "outcome": data["outcome"][chosen]}
    retired_rows = json.loads((retired_calibration / "ROWS.json").read_text())
    retired_id = [r for r in retired_rows if not r["declared_ood"]]
    groups["retired_calibration_id"] = {
        "eligible": np.asarray([r["public_features"]["feedback_known"]
            and r["public_features"]["caption_matches_inferred_order"]
            and r["public_features"]["public_image_argmax_agrees"] for r in retired_id]),
        "head": np.asarray([r["raw_head_probability"] for r in retired_id]),
        "public": np.asarray([r["public_features"]["minimum_inferred_digit_probability"] for r in retired_id]),
        "outcome": np.asarray([r["strict_success"] for r in retired_id])}
    candidates = []
    for head in SPEC["head_threshold_grid"]:
        for public in SPEC["public_probability_grid"]:
            candidate = {"head_threshold": head, "minimum_public_digit_probability": public, "groups": {}}
            for name, values in groups.items():
                selected = values["eligible"] & (values["head"] >= head) & (values["public"] >= public)
                candidate["groups"][name] = {"n": len(selected), "selected": int(selected.sum()),
                    "coverage": float(selected.mean()), "incorrect": int(np.sum(selected & (values["outcome"] == 0)))}
            candidate["feasible"] = all(g["incorrect"] == 0 and g["coverage"] >= .25 for g in candidate["groups"].values())
            candidates.append(candidate)
    feasible = [c for c in candidates if c["feasible"]]
    selected = min(feasible, key=lambda c: (-min(g["coverage"] for g in c["groups"].values()),
        -sum(g["selected"] for g in c["groups"].values()), -c["minimum_public_digit_probability"],
        -c["head_threshold"])) if feasible else None
    result = {"selected": selected, "all_candidates": candidates,
        "historical_only": True, "new_qualification_pairs_consumed": 0,
        "retired_calibration_rows_sha256": sha(retired_calibration / "ROWS.json"),
        "retired_calibration_result_sha256": sha(retired_calibration / "RESULT.json"),
        "old_head_model_sha256": sha(model_path)}
    write(output / "RESULT.json", result)
    if selected:
        selector = {"head_threshold": selected["head_threshold"],
            "minimum_public_digit_probability": selected["minimum_public_digit_probability"],
            "head_model_sha256": sha(model_path), "head_model": model,
            "selection_result_sha256": sha(output / "RESULT.json"), "calibrated": False}
        write(output / "SELECTOR.json", selector)
        write(output / "FROZEN_SELECTOR.json", {"selector_sha256": sha(output / "SELECTOR.json"),
            "protocol_sha256": sha(output / "PROTOCOL.json"), "independent_calibration_outputs_computed": False,
            "qualification_outputs_computed": False})
    print(json.dumps({k: v for k, v in result.items() if k != "all_candidates"}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("head-development", "retired-calibration", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.head_development, args.retired_calibration, args.output)
