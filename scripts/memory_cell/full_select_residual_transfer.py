"""Post-hoc full-pool transfer audit for completed residual checkpoints.

The exact saved residual directions are replayed on the completed 296-question
full-SELECT feature pool. No parameter, seed, checkpoint, alpha or threshold is
selected from full SELECT. This is exposed-development mechanism evidence, not
independent task quality or production routing authority.
"""
from __future__ import annotations

from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[2]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

import torch

import five_causal_experiments as c
import full_select_rank_fusion as full
import shared_gate_cosine_residual as residual
import shared_gate_residual_shrinkage as shrink
from experiments.shared_stem_cell.execution import parameters, tensor_digest

PROFILE = "hepta.cell.full-select-residual-transfer-posthoc.v1"
FULL_ORIGIN = full.ORIGIN
V3_ORIGIN = shrink.ORIGIN
CROSSED_ORIGIN = shrink.CROSSED
ALPHAS = shrink.ALPHAS
ALPHA_NAMES = shrink.ALPHA_NAMES


def _index(rows, key):
    c.require(isinstance(rows, list) and rows
              and all(isinstance(row, dict) and key in row for row in rows),
              "invalid full-pool residual inventory")
    result = {row[key]: row for row in rows}
    c.require(len(result) == len(rows), "duplicate full-pool residual identity")
    return result


def method_name(checkpoint, alpha):
    c.require(isinstance(checkpoint, str) and checkpoint
              and type(alpha) is float and alpha in ALPHAS[1:],
              "registered checkpoint and nonzero alpha required")
    return checkpoint + "@" + shrink.name_alpha(alpha)


def method_census(names):
    c.require(isinstance(names, set) and names, "checkpoint census required")
    methods = [method_name(name, alpha)
               for name in sorted(names) for alpha in ALPHAS[1:]]
    c.require(len(methods) == len(names) * (len(ALPHAS) - 1)
              and len(set(methods)) == len(methods),
              "full-pool residual method collision")
    return methods


def residual_matrix(plan, index, features, model):
    """Vectorize one saved residual over every available question/candidate pair."""
    c.require(isinstance(model, residual.ResidualGate), "saved residual required")
    before_model = parameters(model)
    before_features = c.digest({k: tensor_digest(v) for k, v in sorted(features.items())})
    units = _index(plan["units"], "question_id")
    qids, ekeys = index["question_ids"], index["evidence_keys"]
    c.require(set(qids) == set(units) and len(qids) == 296 and len(ekeys) == 248,
              "full-pool residual denominator changed")
    questions, available = [], []
    for qid in qids:
        unit = units[qid]
        if unit["status"] == "available":
            questions.append(residual._feature(features, unit["question_key"]))
            available.append(True)
        else:
            c.require(unit["status"] == "unavailable_encoder_length",
                      "unknown unavailable question status")
            questions.append(torch.zeros(model.width, dtype=torch.float32))
            available.append(False)
    evidence = [residual._feature(features, key) for key in ekeys]
    question = torch.stack(questions)
    evidence = torch.stack(evidence)
    c.require(question.shape == (len(qids), model.width)
              and evidence.shape == (len(ekeys), model.width),
              "full-pool residual feature geometry")
    mask = torch.tensor(available, dtype=torch.bool)
    with torch.no_grad():
        q_low = torch.tanh(model.q_down(question))
        e_low = torch.tanh(model.e_down(evidence))
        matrix = ((q_low[:, None, :] * e_low[None, :, :])
                  * model.read[None, None, :]).sum(-1).double()
        matrix[~mask] = float("nan")
    c.require(bool(torch.isfinite(matrix[mask]).all())
              and bool(torch.isnan(matrix[~mask]).all()),
              "invalid full-pool residual matrix")
    c.require(before_model == parameters(model), "full-pool replay changed checkpoint")
    c.require(before_features == c.digest({k: tensor_digest(v)
                                           for k, v in sorted(features.items())}),
              "full-pool replay changed frozen features")
    return matrix


def scaled_matrices(cosine, direction, checkpoint):
    c.require(isinstance(cosine, torch.Tensor) and isinstance(direction, torch.Tensor)
              and cosine.shape == direction.shape and cosine.dtype == direction.dtype == torch.float64
              and cosine.device.type == direction.device.type == "cpu",
              "full-pool scale geometry")
    c.require(torch.equal(torch.isnan(cosine), torch.isnan(direction)),
              "full-pool unavailable mask changed")
    outputs = {}
    for alpha in ALPHAS[1:]:
        value = cosine + alpha * direction
        c.require(torch.equal(torch.isnan(value), torch.isnan(cosine))
                  and bool(torch.isfinite(value[~torch.isnan(value)]).all()),
                  "invalid scaled full-pool scores")
        outputs[method_name(checkpoint, alpha)] = value.contiguous()
    return outputs


def paired_train_rule(train, select, features, prior, prior_raw, models):
    """Recompute the paired grid solely to bind the strict TRAIN-only rule."""
    c.require(isinstance(models, dict) and models, "loaded checkpoint census required")
    names = set(models)
    summaries = {}
    for name in sorted(names):
        model = models[name]
        c.require(isinstance(model, residual.ResidualGate)
                  and not any(p.requires_grad for p in model.parameters()),
                  "frozen residual checkpoint required")
        for alpha in ALPHAS:
            key = name + "@" + shrink.name_alpha(alpha)
            train_rows = shrink.scaled_predict(train["units"], features,
                                               prior["fixed_threshold"], model, alpha)
            select_rows = shrink.scaled_predict(select["units"], features,
                                                prior["fixed_threshold"], model, alpha)
            if alpha == 0.0:
                c.require(shrink.exact_rows_equal(train_rows, prior_raw["cosine_frozen"]["train"])
                          and shrink.exact_rows_equal(select_rows, prior_raw["cosine_frozen"]["select"]),
                          "paired zero endpoint changed")
            if alpha == 1.0:
                c.require(shrink.exact_rows_equal(train_rows, prior_raw[name]["train"])
                          and shrink.exact_rows_equal(select_rows, prior_raw[name]["select"]),
                          "paired unit endpoint changed")
            summaries[key] = {
                "train": residual.summarize(train["units"], train_rows),
                "select": residual.summarize(select["units"], select_rows)}
    rule = shrink.select_train_alpha(summaries, names)
    expected = {"rectangle_residual-" + str(seed): "1_16" for seed in residual.SEEDS}
    observed = {name: None if row is None else row["alpha_name"]
                for name, row in rule["selected"].items()}
    c.require(all(observed.get(name) == value for name, value in expected.items())
              and all(observed.get("one_way_residual-" + str(seed)) is None
                      and observed.get("rectangle_reversed-" + str(seed)) is None
                      for seed in residual.SEEDS),
              "strict TRAIN-only shrinkage rule changed")
    return rule
