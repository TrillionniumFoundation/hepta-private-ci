"""Fixed two-comparison Brier family on source pairs outside candidate construction."""

import argparse
import json
from pathlib import Path

import numpy as np

from ...abc_recovery.training_run import file_sha, write_json
from ..native.forecast import Q
from ..native.future_candidate import probability_metrics
from .boundaries import verified_data
from .protocol import IDS


def paired_intervals(advantage, pair):
    ids, counts = np.unique(pair, return_counts=True)
    if advantage.shape != (len(pair), 2) or not (counts == 2).all():
        raise ValueError("Two fixed contrasts and both futures per source are required")
    paired = np.stack([advantage[pair == key].mean(0) for key in ids])
    rng = np.random.default_rng(291018)
    draws = np.array([paired[rng.integers(0, len(ids), len(ids))].mean(0) for _ in range(4000)])
    return paired, np.quantile(draws, [.0125, .9875], axis=0)


def analyze(protocol):
    spec, data, audit = verified_data(protocol)
    output = Path(spec["analysis_output"]); output.mkdir(parents=True, exist_ok=False)
    pair, labels, ood = data["pair"], data["y"], data["ood"]
    raw, calibrated = data["raw_probability"], data["calibrated_probability"]
    loss = (raw-labels[:, None])**2
    advantage = loss[:, :1]-loss[:, 1:]
    ids = np.unique(pair)
    paired, intervals = paired_intervals(advantage, pair)
    forecast = data["forecast"][:, 0]
    actual = data["future_q24"]/Q; past = data["past_q24"]/Q
    strata = {}
    masks = {"all": np.ones(len(pair), dtype=bool), "id": ~ood, "complete_absence": ood,
             "refine_text": data["action"]==0, "couple": data["action"]==1}
    for view in spec["id_views"]:
        masks["view_"+view] = data["view"]==view
    for name, mask in masks.items():
        strata[name] = {"source_pairs": len(np.unique(pair[mask])), "future_rows": int(mask.sum()),
            "actual_joint_correctness": float(labels[mask].mean()),
            "all_heads_raw": [probability_metrics(raw[mask, j], labels[mask]) for j in range(3)],
            "all_heads_frozen_calibration": [probability_metrics(calibrated[mask, j], labels[mask]) for j in range(3)],
            "candidate_raw_brier_improvements": advantage[mask].mean(0).tolist(),
            "shared_forecast_mse": float(((forecast[mask]-actual[mask])**2).mean()),
            "persistence_mse": float(((past[mask]-actual[mask])**2).mean())}
    results = []
    for i in range(2):
        j = i+1
        result = {"candidate": IDS[j], "baseline_raw_brier": float(loss[:, 0].mean()),
            "candidate_raw_brier": float(loss[:, j].mean()), "mean_brier_improvement": float(paired[:, i].mean()),
            "paired_source_individual975_family95_interval": intervals[:, i].tolist(),
            "positive_adjusted_lower_endpoint": bool(intervals[0, i]>0),
            "maximum_raw_probability_change": float(np.abs(raw[:, j]-raw[:, 0]).max()),
            "raw_classification_changes_at_half": int(np.count_nonzero((raw[:, j]>=.5)!=(raw[:, 0]>=.5))),
            "calibrated_classification_changes_at_half": int(np.count_nonzero((calibrated[:, j]>=.5)!=(calibrated[:, 0]>=.5))),
            "calibrated_probability_threshold_changes_at_075": int(np.count_nonzero((calibrated[:, j]>=.75)!=(calibrated[:, 0]>=.75))),
            "frozen_calibration_group_changes": int(np.count_nonzero(data["calibration_group"][:, j]!=data["calibration_group"][:, 0])),
            "calibrated_probability_rows_changed": int(np.count_nonzero(calibrated[:, j]!=calibrated[:, 0])),
            "future_state_forecast_unchanged": bool(np.array_equal(data["forecast"][:, j], forecast))}
        results.append(result)
    result = {"schema": "hepta.abc4.native-candidate-reuse-result.v1", "protocol_sha256": file_sha(protocol),
        "data_sha256": file_sha(Path(spec["output"])/"data.npz"), "candidate_ids": list(IDS),
        "candidate_file_sha256": spec["file_pins"]["candidates"], "weights_sha256": spec["file_pins"]["weights"],
        "source_role": spec["source_role"], "source_pairs": len(ids), "future_rows": len(pair),
        "model_predictions": len(pair)*3, "id_source_pairs": len(np.unique(pair[~ood])),
        "absence_source_pairs": len(np.unique(pair[ood])), "new_project_independent_source_pairs": 0,
        "candidate_specific_construction_holdout": True, "candidate_source_timeline_sha256": spec["timeline_sha256"],
        "source_overlap_with_training_repair": "all1000 source pairs; retain this cross-experiment dependence, do not pool as independent replication",
        "bootstrap_draws": 4000, "comparisons": 2, "individual_confidence": .975, "nominal_family_confidence": .95,
        "source_pair_draws_shared_between_candidates": True, "candidates": results, "descriptive_strata": strata,
        "evidence_audit": audit, "refit_or_recalibration": False, "candidate_selection_or_update_applied": False,
        "authenticated_evaluator": False, "eligible_for_production_acceptance": False,
        "scope": "fixed future-correctness head predictions on newly executed branches from already project-observed sources outside candidate construction; no generated-output improvement or new project N"}
    write_json(output/"result.json", result)
    print(json.dumps({"candidates": results, "source_pairs": len(ids), "new_project_independent_source_pairs": 0}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    analyze(parser.parse_args().protocol)
