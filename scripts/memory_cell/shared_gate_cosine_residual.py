"""Cosine-preserving residual gates on frozen question/evidence features.

The pretrained cosine relation and its TRAIN-only scalar threshold are fixed
before this study. A zero-initialized interaction residual may be trained on
TRAIN only. SELECT is read-only. Cross-family pairs remain weak development
labels, never certified insufficiency or permission to skip a Reader call.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from pathlib import Path
import math
import re
import sys

REPOSITORY = Path(__file__).resolve().parents[2]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

import torch
from torch import nn
from torch.nn import functional as F

import five_causal_experiments as c
import reader_content_swap as swap
import shared_gate_crossed_evidence as crossed
import shared_gate_similarity as similarity
import shared_question_gate as gate
from experiments.shared_stem_cell.execution import measured, parameters, tensor_digest

PROFILE = "hepta.cell.cosine-residual-gate.v1"
ARMS = ("cosine_frozen", "one_way_residual", "rectangle_residual", "rectangle_reversed")
TRAINABLE_ARMS = ARMS[1:]
SEEDS = gate.SEEDS
STEPS = gate.STEPS
LEARNING_RATE = gate.LEARNING_RATE
RANK = gate.RANK
ORDER = crossed.ORDER
ORIGINS = {
    "heads": {"run": 38526481788, "source": "592b5b645ada09c335f942ce7ca11561d5eb2cf1",
              "path": ".github/workflows/hepta-shared-question-gate.yml",
              "artifact": "hepta-shared-question-gate-development"},
    "crossed": {"run": 38526874475, "source": "9da0908298f26fab8173a7ffa04807c9ab179ca7",
                "path": ".github/workflows/hepta-shared-gate-crossed.yml",
                "artifact": "hepta-saved-gate-crossed-evidence-check-disposition"},
    "similarity": {"run": 38529721933, "source": "5ad9270b56cb1bc3acd45dbee8b373dd702ac7be",
                   "path": ".github/workflows/hepta-shared-gate-similarity.yml",
                   "artifact": "hepta-saved-feature-similarity-check-disposition"},
}


def artifact_origin(role, run, artifacts):
    c.require(role in ORIGINS and isinstance(run, dict) and isinstance(artifacts, dict),
              "known authenticated origin required")
    expected = ORIGINS[role]
    c.require(type(run.get("id")) is int and run["id"] == expected["run"]
              and run.get("head_sha") == expected["source"] and run.get("path") == expected["path"]
              and type(run.get("run_attempt")) is int and run["run_attempt"] >= 1
              and all(run.get(k, {}).get("full_name") == "TrillionniumFoundation/hepta-private-ci"
                      for k in ("repository", "head_repository")), "wrong residual origin")
    record = dict(expected, observed_status=run.get("status"), observed_conclusion=run.get("conclusion"),
                  run_attempt=run["run_attempt"], metadata_sha256=c.digest([run, artifacts]))
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        return record | {"ready": False, "status": "deferred_fixed_origin_not_successful"}
    rows = artifacts.get("artifacts")
    c.require(isinstance(rows, list) and type(artifacts.get("total_count")) is int
              and artifacts["total_count"] == len(rows) <= 100
              and all(isinstance(a, dict) for a in rows), "incomplete artifact page")
    matches = [a for a in rows if a.get("name") == expected["artifact"]]
    c.require(len(matches) == 1, "exactly one named residual origin artifact required")
    a = matches[0]
    c.require(type(a.get("id")) is int and a["id"] > 0 and a.get("expired") is False
              and type(a.get("size_in_bytes")) is int and a["size_in_bytes"] > 0
              and re.fullmatch(r"sha256:[0-9a-f]{64}", str(a.get("digest"))) is not None
              and a.get("workflow_run", {}).get("id") == expected["run"]
              and a.get("workflow_run", {}).get("head_sha") == expected["source"],
              "artifact is not bound to fixed residual origin")
    return record | {"ready": True, "artifact_id": a["id"],
                     "artifact_sha256": a["digest"][7:], "status": "ready_for_residual_study"}


def dependency(*metadata):
    c.require(len(metadata) == 6, "three run/artifact pairs required")
    origins = {role: artifact_origin(role, metadata[2*i], metadata[2*i+1])
               for i, role in enumerate(("heads", "crossed", "similarity"))}
    return {"schema": PROFILE + ".dependency", "origins": origins,
            "ready": all(x["ready"] for x in origins.values()),
            "new_reader_calls": 0, "production_accepted": False}


def index(rows, key):
    c.require(isinstance(rows, list) and rows and all(isinstance(r, dict) and key in r for r in rows),
              "invalid residual inventory")
    out = {r[key]: r for r in rows}
    c.require(len(out) == len(rows), "duplicate residual identity")
    return out


def component(split, kind, owner, value):
    """Create a feature identity under its actual data partition.

    The crossed SELECT helper intentionally hard-codes the SELECT partition and
    must not be reused for TRAIN components. Scope remains cache metadata only;
    the neural text is still the canonical public question/options or evidence.
    """
    c.require(split in ("train", "select") and kind in ("question", "evidence")
              and c.text_id(owner), "invalid feature component scope")
    scope = [split, owner, kind]
    text = c.canonical(value).decode("utf-8")
    return {"key": c.digest([gate.REPRESENTATION, scope, text]),
            "scope": scope, "text": text}


def build_train_rectangles(public, train_plan, public_inputs):
    """Close fixed TRAIN pairs using their already registered original sources.

    No target answer enters the feature plan. Missing donors remain missing. The
    old one-way pair is BB (matched donor question) versus AB (recipient question)
    on donor evidence; AA/BA add the recipient's original evidence.
    """
    c.require(public.get("schema") == gate.PROFILE + ".inputs"
              and public.get("representation") == gate.REPRESENTATION
              and train_plan.get("schema") == "hepta.reader.train-question-relevance.v1",
              "wrong residual upstream plans")
    before = c.digest([public, train_plan, public_inputs])
    old = index([u for u in public["units"] if u["split"] == "train"], "question_id")
    source = index(train_plan["units"], "question_id")
    c.require(set(old) == set(source), "TRAIN denominator changed")
    specs = index(public["features"], "key")
    own = {}
    c.require(isinstance(public_inputs, list), "public input census missing")
    for row in public_inputs:
        if not isinstance(row, dict) or row.get("split") != "train" or row.get("condition") != "own_sources":
            continue
        c.require(isinstance(row.get("question_id"), str) and c.text_id(row.get("family")),
                  "invalid original TRAIN input identity")
        qid = c.digest(row["question_id"])
        c.require(qid not in own and isinstance(row.get("request"), dict), "duplicate original TRAIN source")
        c.validate_public(row["request"])
        c.require(row["request"]["evidence"] and all(e["modality"] == "text" for e in row["request"]["evidence"]),
                  "original TRAIN source must be nonempty text")
        own[qid] = row
    c.require(set(old) <= set(own), "original TRAIN source missing; no replacement")
    extra, units = {}, []
    for qid, prior in old.items():
        unit = source[qid]
        c.require(unit["split"] == prior["split"] == "train" and unit["family"] == prior["family"]
                  and unit["status"] == prior["status"], "TRAIN pair identity drift")
        c.require(own[qid]["family"] == unit["family"], "original TRAIN family drift")
        out = {"pair_id": prior["pair_id"], "question_id": qid, "family": prior["family"],
               "donor_question_id": unit.get("donor_question_id"), "donor_family": unit.get("donor_family"),
               "split": "train", "status": unit["status"], "variants": []}
        if unit["status"] != "available":
            c.require(unit["status"] == "unavailable_donor" and not prior["variants"],
                      "missing TRAIN pair repaired")
            units.append(out)
            continue
        c.require(c.sha(unit.get("donor_question_id")) and c.text_id(unit.get("donor_family"))
                  and unit["family"] != unit["donor_family"], "invalid fixed TRAIN donor")
        matched, mismatched = unit["matched_request"], unit["mismatched_request"]
        original = deepcopy(own[qid]["request"])
        for request in (matched, mismatched, original):
            c.validate_public(request)
        c.require(matched["evidence"] == mismatched["evidence"] and matched["evidence"]
                  and matched["options"] == mismatched["options"] == original["options"]
                  and mismatched["question"] == original["question"]
                  and matched["question"] != mismatched["question"]
                  and original["evidence"] != matched["evidence"]
                  and len(original["evidence"]) == len(matched["evidence"]),
                  "not the fixed TRAIN two-question/two-evidence rectangle")
        qa = component("train", "question", unit["family"],
                       {"question": original["question"], "options": original["options"]})
        qb = component("train", "question", unit["donor_family"],
                       {"question": matched["question"], "options": matched["options"]})
        ea = component("train", "evidence", unit["family"], {"evidence": original["evidence"]})
        eb = component("train", "evidence", unit["donor_family"], {"evidence": matched["evidence"]})
        for feature in (qa, qb, eb):
            c.require(specs.get(feature["key"]) == feature, "old TRAIN component was not encoded under fixed scope")
        c.require(prior["variants"] == [
            {"role": "matched", "question_key": qb["key"], "evidence_key": eb["key"],
             "public_request_sha256": c.digest(matched)},
            {"role": "mismatched", "question_key": qa["key"], "evidence_key": eb["key"],
             "public_request_sha256": c.digest(mismatched)}], "old TRAIN score ordering changed")
        if ea["key"] in specs:
            c.require(specs[ea["key"]] == ea, "existing own-evidence bytes differ")
        else:
            c.require(ea["key"] not in extra or extra[ea["key"]] == ea, "own-evidence feature collision")
            extra[ea["key"]] = ea
        for role, q, e in (("aa", qa, ea), ("ab", qa, eb), ("ba", qb, ea), ("bb", qb, eb)):
            out["variants"].append({"role": role, "question_key": q["key"], "evidence_key": e["key"]})
        units.append(out)
    c.require(before == c.digest([public, train_plan, public_inputs]), "residual plan mutated upstream inputs")
    return {"schema": PROFILE + ".train-inputs", "units": units,
            "additional_features": [extra[k] for k in sorted(extra)],
            "score_order": list(ORDER), "old_public_plan_sha256": c.digest(public),
            "train_plan_sha256": c.digest(train_plan), "public_inputs_sha256": c.digest(public_inputs),
            "labels": "balanced_original_source_rectangle_with_weak_cross_family_negatives",
            "new_donor_selection": False, "select_access": False,
            "semantic_accuracy": None, "production_accepted": False}


class ResidualGate(nn.Module):
    """Pure low-rank interaction residual; no additive question/evidence bias.

    r(q,e)=w.[tanh(Pq)*tanh(Re)]. The read vector starts at zero, so every
    initial score equals the fixed cosine-minus-TRAIN-threshold baseline exactly.
    At width384/rank8 this has6,152 parameters (24,608 FP32 bytes).
    """
    def __init__(self, width, rank=RANK):
        super().__init__()
        c.require(type(width) is int and 8 <= width <= 8192
                  and type(rank) is int and 1 <= rank <= width, "residual geometry")
        self.width = width
        self.q_down = nn.Linear(width, rank, bias=False)
        self.e_down = nn.Linear(width, rank, bias=False)
        self.read = nn.Parameter(torch.zeros(rank))

    def forward(self, question, evidence):
        c.require(isinstance(question, torch.Tensor) and isinstance(evidence, torch.Tensor)
                  and question.ndim == evidence.ndim == 2 and question.shape == evidence.shape
                  and question.shape[1] == self.width and question.shape[0] > 0
                  and question.dtype == evidence.dtype == torch.float32
                  and question.device.type == evidence.device.type == "cpu"
                  and bool(torch.isfinite(question).all()) and bool(torch.isfinite(evidence).all()),
                  "residual input geometry/value")
        return ((torch.tanh(self.q_down(question)) * torch.tanh(self.e_down(evidence))) * self.read).sum(-1)


def _feature(features, key):
    c.require(isinstance(features, dict) and key in features, "missing frozen residual feature")
    value = features[key]
    c.require(isinstance(value, torch.Tensor) and value.ndim == 1 and value.dtype == torch.float32
              and value.device.type == "cpu" and not value.requires_grad
              and 8 <= value.numel() <= 8192 and bool(torch.isfinite(value).all())
              and abs(float(value.double().norm()) - 1.0) <= 1e-5, "invalid frozen residual feature")
    return value


def training_batch(units, features, arm):
    c.require(arm in TRAINABLE_ARMS and units and all(u["split"] == "train" for u in units),
              "TRAIN-only registered residual arm required")
    q_rows, e_rows, labels, identities = [], [], [], []
    for unit in units:
        if unit["status"] != "available":
            c.require(not unit["variants"], "unavailable residual pair has features")
            continue
        roles = {v["role"]: v for v in unit["variants"]}
        c.require(tuple(v["role"] for v in unit["variants"]) == ORDER and set(roles) == set(ORDER),
                  "residual four-corner order changed")
        if arm == "one_way_residual":
            order, target = ("bb", "ab", "bb", "ab"), (1.0, 0.0, 1.0, 0.0)
        elif arm == "rectangle_residual":
            order, target = ORDER, (1.0, 0.0, 0.0, 1.0)
        else:
            order, target = ORDER, (0.0, 1.0, 1.0, 0.0)
        for role, y in zip(order, target):
            v = roles[role]
            q_rows.append(_feature(features, v["question_key"]))
            e_rows.append(_feature(features, v["evidence_key"]))
            labels.append(y)
            identities.append([unit["pair_id"], role])
    c.require(q_rows and len(q_rows) % 4 == 0 and set(labels) == {0.0, 1.0}, "empty/degenerate residual batch")
    return torch.stack(q_rows), torch.stack(e_rows), torch.tensor(labels, dtype=torch.float64), identities


def base_scores(question, evidence, threshold):
    c.require(c.finite(threshold, -2.0, 2.0), "invalid fixed cosine threshold")
    c.require(question.shape == evidence.shape and question.ndim == 2, "base score geometry")
    return torch.tensor([similarity.cosine(q.tolist(), e.tolist()) - threshold
                         for q, e in zip(question, evidence)], dtype=torch.float64)


def fit(units, features, threshold, *, arm, seed, steps=STEPS):
    c.require(arm in TRAINABLE_ARMS and type(seed) is int and type(steps) is int and 1 <= steps <= STEPS,
              "unregistered residual fit")
    q0, e0, y, identities = training_batch(units, features, arm)
    shared_digest = c.digest({k: tensor_digest(v) for k, v in sorted(features.items())})
    with torch.inference_mode(False):
        q, e = q0.detach().clone(), e0.detach().clone()
    fixed = base_scores(q, e, threshold)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        model = ResidualGate(q.shape[1])
    initial = parameters(model)
    with torch.no_grad():
        initial_logits = fixed + model(q, e).double()
    c.require(torch.equal(initial_logits, fixed), "zero residual did not preserve fixed cosine baseline")
    history = []
    with measured() as cost, torch.enable_grad():
        optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=0.01)
        for step in range(steps):
            optimizer.zero_grad(set_to_none=True)
            logits = fixed + model(q, e).double()
            loss = F.binary_cross_entropy_with_logits(logits, y)
            c.require(bool(torch.isfinite(loss)), "nonfinite residual loss")
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
            optimizer.step()
            history.append({"step": step + 1, "loss": float(loss.detach())})
        optimizer_bytes = sum(v.numel() * v.element_size() for state in optimizer.state.values()
                              for v in state.values() if isinstance(v, torch.Tensor))
        optimizer.zero_grad(set_to_none=True)
    model.eval().requires_grad_(False)
    c.require(shared_digest == c.digest({k: tensor_digest(v) for k, v in sorted(features.items())}),
              "residual fit changed shared features")
    return model, {"arm": arm, "seed": seed, "optimizer_steps": len(history),
                   "training_rows": len(y), "training_pair_ids": identities,
                   "initial": initial, "saved_model": parameters(model),
                   "initial_scores_equal_fixed_cosine": True,
                   "fixed_threshold": threshold, "base_scores_sha256": c.digest(fixed.tolist()),
                   "optimizer_tensor_bytes": optimizer_bytes, "history": history, "cost": cost,
                   "encoder_updated": False, "weak_labels": True,
                   "label_profile": "one_way_repeated" if arm == "one_way_residual" else
                                    "balanced_rectangle" if arm == "rectangle_residual" else
                                    "deliberately_reversed_balanced_rectangle"}


def predict(units, features, threshold, model=None):
    c.require(model is None or isinstance(model, ResidualGate), "invalid residual predictor")
    before = None if model is None else parameters(model)
    rows = []
    with torch.no_grad():
        for unit in units:
            row = {"pair_id": unit["pair_id"], "status": "unavailable", "logits": None}
            if unit["status"] == "available":
                c.require(tuple(v["role"] for v in unit["variants"]) == ORDER, "prediction corner order changed")
                q = torch.stack([_feature(features, v["question_key"]) for v in unit["variants"]])
                e = torch.stack([_feature(features, v["evidence_key"]) for v in unit["variants"]])
                value = base_scores(q, e, threshold)
                if model is not None:
                    value = value + model(q, e).double()
                c.require(bool(torch.isfinite(value).all()), "nonfinite residual prediction")
                row.update(status="succeeded", logits=value.tolist())
            else:
                c.require(not unit["variants"], "unavailable residual prediction imputed")
            rows.append(row)
    if model is not None:
        c.require(before == parameters(model), "residual prediction changed checkpoint")
    return rows


def separability(units, predictions):
    planned, observed = index(units, "pair_id"), index(predictions, "pair_id")
    c.require(set(planned) == set(observed), "residual separability denominator changed")
    details, lower, upper = [], [], []
    for key, unit in planned.items():
        row = observed[key]
        if unit["status"] != "available":
            c.require(row["status"] == "unavailable" and row["logits"] is None, "missing residual pair imputed")
            continue
        c.require(row["status"] == "succeeded" and isinstance(row["logits"], list)
                  and len(row["logits"]) == 4 and all(c.finite(x, -1e12, 1e12) for x in row["logits"]),
                  "invalid residual rectangle")
        aa, ab, ba, bb = row["logits"]
        lo, hi = max(ab, ba), min(aa, bb)
        lower.append(lo); upper.append(hi)
        details.append({"pair_id": key, "lower_rejected_max": lo, "upper_accepted_min": hi,
                        "separability_gap": hi - lo, "some_threshold_exists": lo < hi,
                        "fixed_zero_threshold_passes": aa > 0 and bb > 0 and ab < 0 and ba < 0})
    return {"planned_pairs": len(planned), "scored_pairs": len(details),
            "unavailable_pairs": len(planned) - len(details),
            "per_pair_separable": sum(x["some_threshold_exists"] for x in details),
            "fixed_zero_threshold_passes": sum(x["fixed_zero_threshold_passes"] for x in details),
            "common_threshold_lower": max(lower) if lower else None,
            "common_threshold_upper": min(upper) if upper else None,
            "common_threshold_exists": bool(lower and max(lower) < min(upper)),
            "details": details, "select_threshold_fitted": False,
            "semantic_accuracy": None, "production_accepted": False}


def summarize(units, predictions):
    return {"crossed": crossed.summarize(units, predictions),
            "threshold_geometry": separability(units, predictions)}
