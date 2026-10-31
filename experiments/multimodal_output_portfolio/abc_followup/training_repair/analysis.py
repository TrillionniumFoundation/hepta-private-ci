"""Prespecified strong-reference gate, with separate reference and dual contrasts."""

import argparse
import json
from pathlib import Path

import numpy as np

from ...abc_recovery.base_recovery import file_sha, write_json
from ...abc_recovery.statistics import crossed_bootstrap, loss_tails, paired_comparison, summarize_utility
from ..training.evaluate import METRICS
from .protocol import ALL_ARMS
from .evaluate import verify


def load_cubes(root, spec, protocol_sha):
    result = json.loads((root / "result.json").read_text())
    access = json.loads((root / "access-registration.json").read_text())
    if (result["status"] != "completed" or result["protocol_sha256"] != protocol_sha
            or access["protocol_sha256"] != protocol_sha
            or result["source_identity"] != spec["source_identity"]
            or access["source_identity"] != spec["source_identity"]
            or access["origin_role"] != spec["origin_role"]
            or access["role_assignment_sha256"] != spec["role_assignment_sha256"]
            or (access["role"], access["start"], access["count"]) != (spec["role"], spec["start"], spec["count"])):
        raise ValueError("Wrong, incomplete or relabeled source execution")
    shape = (len(spec["seeds"]), spec["count"], len(spec["views"]), spec["scenarios"])
    cubes = {judge: {arm: {metric: np.empty(shape) for metric in METRICS} for arm in ALL_ARMS}
             for judge in ("primary", "secondary")}
    expected = {(r["seed"], r["arm"]): r for r in spec["models"]}
    seen = set()
    for row in result["models"]:
        key = row["seed"], row["arm"]
        if key in seen or key not in expected or row["sha256"] != expected[key]["sha256"]:
            raise ValueError("Duplicate or foreign treatment/seed/model")
        seen.add(key)
        if file_sha(row["data_file"]) != row["data_sha256"]:
            raise ValueError("Scored output array changed")
        index = spec["seeds"].index(row["seed"])
        with np.load(row["data_file"], allow_pickle=False) as saved:
            if set(saved.files) != {f"{judge}/{metric}" for judge in cubes for metric in METRICS}:
                raise ValueError("Wrong metric census")
            for judge in cubes:
                for metric in METRICS:
                    values = saved[f"{judge}/{metric}"]
                    if values.shape != shape[1:] or not np.isfinite(values).all():
                        raise ValueError("Missing or nonfinite metric cells")
                    if metric in ("success", "complete") and not np.isin(values, (0., 1.)).all():
                        raise ValueError("Success/completion is not a binary observation")
                    cubes[judge][row["arm"]][metric][index] = values
    if seen != set(expected):
        raise ValueError("Incomplete treatment and seed census")
    return cubes


def analyze(protocol_path, output):
    spec = json.loads(protocol_path.read_text())
    verify(spec)
    root = Path(spec["output"])
    cubes = load_cubes(root, spec, file_sha(protocol_path))
    bootstrap = crossed_bootstrap(len(spec["seeds"]), spec["count"],
        replicates=spec["bootstrap"]["replicates"], seed=spec["bootstrap"]["seed"])
    comparisons = (("matched_floor_warmdual", "mean"), ("matched_floor", "mean"),
        ("old_constraint", "mean"), ("matched_floor", "old_constraint"),
        ("matched_floor_warmdual", "matched_floor"), ("matched_floor_warmdual", "old_constraint"))
    observers = {}
    for judge, arms in cubes.items():
        cells, contrasts = {}, []
        for arm, values in arms.items():
            cells[arm] = {"utility": summarize_utility(values["utility"], spec["gamma"]),
                "mean_metrics": {name: float(x.mean()) for name, x in values.items()},
                "loss_tails": loss_tails(values["joint_loss"]),
                "success_per_seed": values["success"].mean(axis=(1, 2, 3)).tolist(),
                "by_view": {view: {"CE": summarize_utility(values["utility"][:, :, i:i+1], spec["gamma"])["joint_ce"],
                    "success": float(values["success"][:, :, i].mean())} for i, view in enumerate(spec["views"])}}
        for candidate, reference in comparisons:
            primary = judge == "primary" and (candidate, reference) == ("matched_floor_warmdual", "mean")
            confidence = .975 if primary else .95
            a, b = arms[candidate], arms[reference]
            ce = paired_comparison(a["utility"], b["utility"], gamma=spec["gamma"], confidence=confidence, bootstrap=bootstrap)
            success = paired_comparison(a["success"], b["success"], estimand="success_rate", confidence=confidence, bootstrap=bootstrap)
            contrasts.append({"candidate": candidate, "reference": reference, "primary": primary,
                "CE": ce, "success": success})
        observers[judge] = {"cells": cells, "comparisons": contrasts}
    main = observers["primary"]["comparisons"][0]
    ce_pass, success_pass = main["CE"]["interval"][0] > 0, main["success"]["interval"][0] >= 0
    result = {"schema": "hepta.abc4.reference-repair-analysis.v1", "status": "completed",
        "protocol_sha256": file_sha(protocol_path), "execution_sha256": file_sha(root / "result.json"),
        "source_role": spec["role"], "origin_role": spec["origin_role"],
        "source_pairs": spec["count"], "distinct_source_images": 2 * spec["count"],
        "training_seeds": spec["seeds"], "views": spec["views"], "scenarios": spec["scenarios"],
        "selected_output_rows": len(spec["models"]) * spec["count"] * len(spec["views"]) * spec["scenarios"],
        "new_models": 10, "new_optimizer_updates": 4000, "observers": observers,
        "primary_CE_gate": bool(ce_pass), "primary_zero_margin_success_gate": bool(success_pass),
        "primary_conjunction_passed": bool(ce_pass and success_pass),
        "prior_failed_final_retained": True, "prior_rows_used_for_gradient_or_selection": False,
        "interpretation": "new separately registered round after a documented failure, not a retrospective rescue of that final",
        "bootstrap_scope": "nominal five-seed/source paired percentile intervals; no guaranteed coverage, no replay inflation",
        "global_cross_round_error_control_claimed": False, "population_constraint_certificate": False,
        "global_optimality_claimed": False}
    write_json(output, result)
    print(json.dumps({"CE": main["CE"], "success": main["success"],
                      "primary_conjunction_passed": result["primary_conjunction_passed"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    analyze(args.protocol, args.output)
