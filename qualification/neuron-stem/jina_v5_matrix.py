#!/usr/bin/env python3
"""Pre-registered, feasible Jina v5 shadow experiment matrix.

Does not execute models or claim that planned measurements exist.
"""
import argparse
import json
from pathlib import Path

from jina_v5 import MODELS
from qualified_eval import HEADS, BUDGETS, SCALES, write_json

SHOTS = (8, 32, 128)
DIMS = (256, 512)
REPRESENTATIONS = ("joint", "state")
MODALITY_LOADS = ("vision", "audio", "omni")


def minimum_head_parameters(head, width, classes=2):
    if head == "linear":
        return width * classes + classes
    if head == "film":
        return 2 * width + width * classes + classes
    if head in ("rank8", "rank16"):
        rank = 8 if head == "rank8" else 16
        return width * rank + rank + rank * classes + classes
    if head == "mlp":
        return width + 1 + classes + classes  # 1 hidden unit
    if head == "swiglu":
        return 2 * (width + 1) + classes + classes
    raise ValueError("unregistered Cell Head")


def plan(registry):
    models = registry["jina_v5_models"]
    if {m["id"] for m in models} != set(MODELS):
        raise ValueError("registry's complete Jina model family is required")
    for entry in models:
        spec = MODELS[entry["id"]]
        if (entry["repository"], entry["parameters"], entry["embedding_dimension"]) != (
                spec.repository, spec.parameters, spec.dimensions):
            raise ValueError("registry/model-spec drift")
    heads, scale, modality = [], [], []
    for m in models:
        spec = MODELS[m["id"]]
        if spec.omni:
            for mode in MODALITY_LOADS:
                for dimension in DIMS:
                    modality.append({
                        "model": m["id"], "paired_text_model": "jina-v5-text-" + spec.family,
                        "modality_loading": mode, "dimension": dimension,
                        "mode": "genuine_paired_media_retrieval",
                        "activation": "shadow", "promotion": False})
            continue
        for rep in REPRESENTATIONS:
            for dimension in DIMS:
                for head in HEADS:
                    for budget in BUDGETS:
                        if minimum_head_parameters(head, dimension) > budget:
                            continue
                        for shots in SHOTS:
                            heads.append({
                                "model": m["id"], "feature_dimension": dimension,
                                "representation": rep, "task_adapter": "classification",
                                "head": head, "maximum_head_parameters": budget,
                                "shots": shots, "scope": "cell_head_only",
                                "activation": "shadow", "promotion": False})
        for cells in sorted(SCALES):
            for active in (.05, .25, 1.):
                for repeat in (0., .5, .9):
                    for similarity in ("low", "medium", "high"):
                        scale.append({
                            "model": m["id"], "logical_cells": cells,
                            "active_fraction": active,
                            "input_repeat_fraction": repeat,
                            "task_similarity": similarity,
                            "active_cell_coverage_required": True,
                            "activation": "shadow", "promotion": False})
    return {
        "schema": "hepta.jina-v5-precommitted-shadow-matrix.v1",
        "description": "Feasible arms only; planning is not measurement",
        "head_arms": heads, "resource_arms": scale,
        "multimodal_arms": modality,
        "main_quality_metric": "held_out_future_paired_accuracy_and_brier",
        "bootstrap_unit": "(scope_id,group_id)",
        "future_minimum_independent_groups": 30,
        "pre_registered_quality_gate": {
            "accuracy_gain_lower95_gt": 0, "brier_delta_upper95_lt": 0,
            "max_task_brier_regression": 0.01},
        "independent_ndu_signature_verified": False,
        "production_promotion_permitted": False,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--models", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    if Path(args.out).exists():
        raise ValueError("refusing to overwrite a frozen qualification plan")
    registry = json.loads(Path(args.models).read_text(encoding="utf-8"))
    write_json(args.out, plan(registry))


if __name__ == "__main__":
    main()
