"""Post-hoc scaling audit for completed cosine-residual checkpoints.

The final residual direction is held fixed. No parameter is fitted and no seed,
alpha, threshold or checkpoint is chosen from SELECT. A fixed geometric grid
scales each saved residual around the authenticated frozen-cosine baseline.
This is exposed-development mechanism evidence, never independent task quality.
"""
from __future__ import annotations

from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[2]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

import torch

import five_causal_experiments as c
import shared_gate_cosine_residual as residual
from experiments.shared_stem_cell.execution import parameters

PROFILE = "hepta.cell.cosine-residual-shrinkage-posthoc.v1"
ORIGIN = {
    "run": 38665708709,
    "source": "14eb7234a32fd20c8fd4e677f11a241db0d00ad6",
    "path": ".github/workflows/hepta-cosine-residual-gate-v3.yml",
    "artifact": "hepta-cosine-residual-gate-v3-development",
    "artifact_id": 11942057629,
    "artifact_sha256": "23d8d35da612a45d99aafcf2f9f09eceae94b08bb3ee61cb853ac71c50d8cd90",
}
CROSSED = {
    "source": residual.ORIGINS["crossed"]["source"],
    "artifact_id": 11878031858,
    "artifact_sha256": "bb61d593ed46f3245339ca5a41a4198d3c346823c7b7a091b090274c33ab3b78",
}
ALPHAS = (0.0, 1.0 / 64, 1.0 / 32, 1.0 / 16, 1.0 / 8, 1.0 / 4, 1.0 / 2, 1.0)
ALPHA_NAMES = ("zero", "1_64", "1_32", "1_16", "1_8", "1_4", "1_2", "one")


def name_alpha(alpha):
    c.require(type(alpha) is float and alpha in ALPHAS, "unregistered residual scale")
    return ALPHA_NAMES[ALPHAS.index(alpha)]


def _index(rows, key):
    c.require(isinstance(rows, list) and rows
              and all(isinstance(row, dict) and key in row for row in rows),
              "invalid shrinkage inventory")
    result = {row[key]: row for row in rows}
    c.require(len(result) == len(rows), "duplicate shrinkage identity")
    return result


def scaled_predict(units, features, threshold, model, alpha):
    """Apply a fixed scalar to the saved residual; alpha zero is exact cosine."""
    c.require(isinstance(model, residual.ResidualGate)
              and type(alpha) is float and alpha in ALPHAS,
              "registered saved residual and scale required")
    before = parameters(model)
    rows = []
    with torch.no_grad():
        for unit in units:
            row = {"pair_id": unit["pair_id"], "status": "unavailable", "logits": None}
            if unit["status"] == "available":
                c.require(tuple(v["role"] for v in unit["variants"]) == residual.ORDER,
                          "shrinkage corner order changed")
                question = torch.stack([residual._feature(features, v["question_key"])
                                        for v in unit["variants"]])
                evidence = torch.stack([residual._feature(features, v["evidence_key"])
                                        for v in unit["variants"]])
                value = residual.base_scores(question, evidence, threshold)
                if alpha:
                    value = value + alpha * model(question, evidence).double()
                c.require(bool(torch.isfinite(value).all()), "nonfinite scaled residual")
                row.update(status="succeeded", logits=value.tolist())
            else:
                c.require(not unit["variants"], "unavailable shrinkage pair imputed")
            rows.append(row)
    c.require(before == parameters(model), "shrinkage changed saved checkpoint")
    return rows


def exact_rows_equal(left, right):
    return c.canonical(left) == c.canonical(right)


def select_train_alpha(summaries, names):
    """Apply one strict TRAIN-only rule to every saved checkpoint.

    The rule returns the smallest nonzero registered alpha for which every
    available TRAIN rectangle has both question and evidence rankings, all four
    fixed-threshold signs, per-pair separability, and a common threshold interval.
    It never reads SELECT and never chooses a seed or checkpoint.
    """
    c.require(isinstance(summaries, dict) and isinstance(names, set) and names,
              "complete shrinkage summaries and checkpoint census required")
    selected = {}
    candidates = ALPHAS[1:]
    for name in sorted(names):
        choice = None
        for alpha in candidates:
            key = name + "@" + name_alpha(alpha)
            c.require(key in summaries and set(summaries[key]) == {"train", "select"},
                      "missing shrinkage summary")
            train = summaries[key]["train"]
            crossed = train["crossed"]
            geometry = train["threshold_geometry"]
            scored = crossed["scored_pairs"]
            c.require(scored == geometry["scored_pairs"] and scored > 0,
                      "TRAIN shrinkage denominator mismatch")
            if (crossed["both_question_rankings"] == scored
                    and crossed["both_evidence_rankings"] == scored
                    and crossed["all_four_threshold_directions"] == scored
                    and geometry["per_pair_separable"] == scored
                    and geometry["common_threshold_exists"] is True):
                choice = {"alpha": alpha, "alpha_name": name_alpha(alpha),
                          "summary_key": key, "select_summary": summaries[key]["select"]}
                break
        selected[name] = choice
    return {
        "rule": "smallest_nonzero_alpha_with_all_TRAIN_question_and_evidence_rankings_all_four_fixed_signs_per_pair_separability_and_common_threshold",
        "reads_select": False,
        "seed_selection": False,
        "checkpoint_selection": False,
        "posthoc_rule_design_after_select_observation": True,
        "selected": selected,
    }


def validate_completed(root, crossed_root):
    """Bind exact successful v3 result, crossed inputs, seals and checkpoint set."""
    root, crossed_root = Path(root), Path(crossed_root)
    study, crossed_study = root / "study", crossed_root / "study"
    c.require((root / "source/tested-commit.txt").read_text().strip() == ORIGIN["source"]
              and (crossed_root / "source/tested-commit.txt").read_text().strip() == CROSSED["source"],
              "wrong shrinkage source artifacts")
    disposition = c.load(root / "execution-disposition.json")
    report = c.load(study / "report.json")
    plan = c.load(study / "plan.json")
    train = c.load(study / "train-rectangles.json")
    raw = c.load(study / "raw-logits.json")
    select = c.load(crossed_study / "crossed-inputs.json")
    seal = c.load(study / "prediction-seal.json")
    c.require(disposition == {"model_execution_completed": True, "new_reader_calls": 0,
                              "semantic_accuracy": None, "production_accepted": False}
              and report["schema"] == residual.PROFILE + ".result"
              and report["errors"] == [] and report["plan_sha256"] == c.digest(plan)
              and report["raw_sha256"] == c.file_sha(study / "raw-logits.json")
              and seal == {"sha256": report["raw_sha256"], "before_summary": True}
              and report["new_pretrained_model_loads"] == 1
              and report["new_encoder_forwards"] == 6
              and report["new_head_optimizer_updates"] == 9 * residual.STEPS
              and report["new_reader_calls"] == 0 and report["select_fit"] is False,
              "incomplete or reinterpreted residual v3 result")
    c.require(train["schema"] == residual.PROFILE + ".train-inputs"
              and select["schema"] == "hepta.cell.saved-gate-crossed-evidence.v1.inputs"
              and len(train["units"]) == 14 and len(select["units"]) == 4
              and sum(u["status"] == "available" for u in train["units"]) == 13
              and sum(u["status"] == "available" for u in select["units"]) == 3,
              "residual denominator changed")
    names = {arm + "-" + str(seed) for arm in residual.TRAINABLE_ARMS for seed in residual.SEEDS}
    c.require(set(raw) == {"cosine_frozen"} | names
              and set(report["head_parameters"]) == names
              and {p.name for p in (study / "heads").iterdir() if p.is_dir()} == names,
              "residual checkpoint census changed")
    return study, train, select, report, raw, names
