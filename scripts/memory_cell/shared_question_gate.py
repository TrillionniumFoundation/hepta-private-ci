"""Small post-Encoder question/evidence gates on frozen, separately encoded text.

This is a weak-pair DEVELOPMENT diagnostic, not a Reader replacement, calibrated
utility, independent semantic test or permission to skip the existing gate.
No target answer or arm identity enters the Encoder or the prediction API.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from pathlib import Path
import sys

# Match the native worker's repository-root bootstrap before importing its
# shared execution module. Direct script execution otherwise exposes only the
# scripts/memory_cell directory, unlike unittest discovery from the repo root.
REPOSITORY = Path(__file__).resolve().parents[2]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

import torch
from torch import nn
from torch.nn import functional as F

import five_causal_experiments as c
from experiments.shared_stem_cell.execution import measured, parameters, tensor_digest

PROFILE = "hepta.cell.shared-question-gate.v1"
REPRESENTATION = "separate-question-evidence-meanpool-v1"
ARMS = ("frozen_gate", "linear_aligned", "evidence_only", "gated_aligned", "gated_reversed")
SEEDS = (20261014, 20261015, 20261016)
STEPS = 256
LEARNING_RATE = 0.003
RANK = 8
MAXIMUM_TOKENS = 512


def public_plan(train, select):
    """Project already chosen pairs; do not search, relabel or replace donors."""
    c.require(train.get("schema") == "hepta.reader.train-question-relevance.v1"
              and select.get("schema") == "hepta.reader.select-same-source-question.v1", "wrong pinned pair plans")
    before = c.digest([train, select])
    units, features, scopes, source_splits, seen = [], {}, {}, {}, set()
    for split, plan in (("train", train), ("select", select)):
        rows = plan.get("units")
        c.require(isinstance(rows, list) and 0 < len(rows) <= 4096, "bounded pair census")
        for row in rows:
            qid, family = row["question_id"], row["family"]
            c.require(c.sha(qid) and c.text_id(family) and row["split"] == split and qid not in seen,
                      "duplicate/nonregistered question or split")
            seen.add(qid)
            c.require(scopes.setdefault(family, split) == split, "recipient family crosses partitions")
            item = {"pair_id": c.digest([split, qid]), "question_id": qid, "family": family,
                    "split": split, "status": row["status"], "variants": []}
            if row["status"] != "available":
                c.require(row["status"] in ("unavailable_donor", "unavailable_reference_or_donor")
                          and row.get("matched_request") is None and row.get("mismatched_request") is None,
                          "invalid missing pair; no fabricated source")
                units.append(item)
                continue
            donor_family = row["donor_family"]
            c.require(c.text_id(donor_family) and donor_family != family
                      and scopes.setdefault(donor_family, split) == split, "donor family crosses partitions")
            matched, mismatched = row["matched_request"], row["mismatched_request"]
            c.validate_public(matched); c.validate_public(mismatched)
            c.require(matched["evidence"] and matched["evidence"] == mismatched["evidence"]
                      and matched["options"] == mismatched["options"]
                      and matched["question"] != mismatched["question"], "not identical sources/different questions")
            c.require(all(x["modality"] == "text" for x in matched["evidence"]), "no caption-as-pixels conversion")
            for role, request, qfamily in (("matched", matched, donor_family), ("mismatched", mismatched, family)):
                components = (("question", qfamily, {"question": request["question"], "options": request["options"]}),
                              ("evidence", donor_family, {"evidence": request["evidence"]}))
                keys = []
                for kind, owner, value in components:
                    # Scope is in the cache key only, never in neural text.
                    text = c.canonical(value).decode("utf-8")
                    if kind == "evidence":
                        h = c.digest(value)
                        c.require(source_splits.setdefault(h, split) == split, "source bytes cross partitions")
                    scope = [split, owner, kind]
                    key = c.digest([REPRESENTATION, scope, text])
                    feature = {"key": key, "scope": scope, "text": text}
                    c.require(key not in features or features[key] == feature, "feature identity collision")
                    features[key] = feature
                    keys.append(key)
                item["variants"].append({"role": role, "question_key": keys[0], "evidence_key": keys[1],
                                         "public_request_sha256": c.digest(request)})
            units.append(item)
    c.require(c.digest([train, select]) == before, "upstream plans changed")
    return {"schema": PROFILE + ".inputs", "representation": REPRESENTATION, "units": units,
            "features": [features[k] for k in sorted(features)], "upstream_pair_plan_sha256": before,
            "supervision": "inherited_weak_matched_vs_cross_family_question_pair",
            "new_donor_selection": False, "test_partition_access": False,
            "reader_adequacy_established": False, "production_accepted": False}


def token_preflight(tokenizer, plan, cap=MAXIMUM_TOKENS):
    c.require(type(cap) is int and 8 <= cap <= MAXIMUM_TOKENS, "bounded original Encoder capacity")
    records = []
    for row in plan["features"]:
        ids = tokenizer(row["text"], truncation=False, add_special_tokens=True)["input_ids"]
        c.require(isinstance(ids, list) and ids and all(type(x) is int and x >= 0 for x in ids), "invalid token preflight")
        records.append({"key": row["key"], "tokens": len(ids), "token_sha256": c.digest(ids),
                        "within_cap": len(ids) <= cap})
    return {"rows": records, "all_within_cap": bool(records) and all(x["within_cap"] for x in records),
            "maximum_tokens": cap, "truncated": False, "replacement_selected": False}


def encode_once(backend, plan, preflight):
    """One frozen owner; unique complete input per scope, not cross-scope reuse."""
    c.require(preflight["all_within_cap"], "preflight failed before Encoder work")
    feature_rows = plan["features"]
    c.require(len(feature_rows) <= 16384 and len({r["key"] for r in feature_rows}) == len(feature_rows), "feature census")
    tokens = {x["key"]: x for x in preflight["rows"]}
    c.require(set(tokens) == {r["key"] for r in feature_rows}, "preflight identity changed")
    groups = defaultdict(list)
    for row in feature_rows:
        c.require(row["key"] == c.digest([REPRESENTATION, row["scope"], row["text"]]), "feature text changed")
        ids = backend.tokenizer(row["text"], truncation=False, add_special_tokens=True)["input_ids"]
        c.require(c.digest(ids) == tokens[row["key"]]["token_sha256"], "tokenizer drift")
        groups[tuple(row["scope"])].append(row)
    result, census, width = {}, [], None
    before = parameters(backend.loaded)
    c.require(not backend.loaded.training and all(not p.requires_grad for p in backend.loaded.parameters()), "unfrozen Encoder")
    for scope in sorted(groups):
        rows = groups[scope]
        batch_size = min(32, 32768 // preflight["maximum_tokens"])
        for start in range(0, len(rows), batch_size):
            selected = rows[start:start + batch_size]
            with measured() as cost:
                values = backend.encode([r["text"] for r in selected])
            c.require(isinstance(values, torch.Tensor) and values.ndim == 2
                      and values.shape[0] == len(selected) and 8 <= values.shape[1] <= 8192
                      and values.device.type == "cpu" and values.dtype == torch.float32
                      and bool(torch.isfinite(values).all())
                      and bool((values.norm(dim=1) > 0).all()), "invalid frozen Encoder features")
            c.require(width is None or width == values.shape[1], "Encoder geometry drift")
            width = values.shape[1]
            with torch.inference_mode(False):
                normal = F.normalize(values.detach().clone(), p=2, dim=1)
            for r, value in zip(selected, normal):
                result[r["key"]] = value.clone().contiguous()
            census.append({"scope": list(scope), "keys": [r["key"] for r in selected], "cost": cost,
                           "returned_tensor_bytes": values.numel()*values.element_size()})
    c.require(before == parameters(backend.loaded), "Encoder weights changed")
    backend.close()
    requests = sum(2 * len(u["variants"]) for u in plan["units"])
    return result, {"unique_feature_rows": len(result), "component_requests": requests,
                    "deduplicated_component_requests": requests-len(result),
                    "completed_encoder_batches": len(census), "batches": census, "encoder": before,
                    "normalized_feature_bytes": sum(v.numel()*v.element_size() for v in result.values()),
                    "normalization": "per_vector_L2_no_holdout_fitted_statistics",
                    "new_reader_calls": 0, "new_encoder_optimizer_updates": 0}


class QuestionGate(nn.Module):
    """Per-Cell low-rank gate; the Encoder is external and shared.

    s(q,e)=u.q+v.e+b+w.[tanh(Pq)*sigmoid(Re)].
    At384 dimensions/rank8 this has6,921 parameters, not an Encoder copy.
    Scores are uncalibrated logits; zero is a fixed diagnostic threshold.
    """
    def __init__(self, width, rank=RANK, kind="gated"):
        super().__init__()
        c.require(type(width) is int and 8 <= width <= 8192 and type(rank) is int and 1 <= rank <= width,
                  "gate geometry")
        c.require(kind in ("gated", "linear", "evidence"), "gate kind")
        self.width, self.kind = width, kind
        self.e_read = nn.Linear(width, 1, bias=True)
        nn.init.zeros_(self.e_read.weight); nn.init.zeros_(self.e_read.bias)
        if kind != "evidence":
            self.q_read = nn.Linear(width, 1, bias=False)
            nn.init.zeros_(self.q_read.weight)
        if kind == "gated":
            self.q_down = nn.Linear(width, rank, bias=False)
            self.e_gate = nn.Linear(width, rank, bias=False)
            self.read = nn.Parameter(torch.zeros(rank))

    def forward(self, question, evidence):
        c.require(isinstance(question, torch.Tensor) and isinstance(evidence, torch.Tensor)
                  and question.ndim == evidence.ndim == 2 and question.shape == evidence.shape
                  and question.shape[1] == self.width and question.shape[0] > 0
                  and question.dtype == evidence.dtype == torch.float32
                  and question.device.type == evidence.device.type == "cpu"
                  and bool(torch.isfinite(question).all()) and bool(torch.isfinite(evidence).all()), "gate input geometry/value")
        value = self.e_read(evidence).squeeze(-1)
        if self.kind != "evidence":
            value = value + self.q_read(question).squeeze(-1)
        if self.kind == "gated":
            value = value + ((torch.tanh(self.q_down(question)) * torch.sigmoid(self.e_gate(evidence))) * self.read).sum(-1)
        return value


def fit(train_q, train_e, labels, *, arm, seed, split="train", steps=STEPS):
    """Only explicit TRAIN tensors enter AdamW. No SELECT evaluation in fitting."""
    c.require(split == "train" and arm in ARMS and type(seed) is int and type(steps) is int and 1 <= steps <= STEPS,
              "unregistered fit/split/budget")
    c.require(train_q.shape == train_e.shape and train_q.ndim == 2 and len(train_q) > 1
              and isinstance(labels, torch.Tensor) and labels.shape == (len(train_q),)
              and labels.dtype == torch.float32 and set(labels.tolist()) == {0.0, 1.0}, "TRAIN labels/features")
    input_digest = c.digest([tensor_digest(x) for x in (train_q, train_e, labels)])
    kind = "linear" if arm == "linear_aligned" else ("evidence" if arm == "evidence_only" else "gated")
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        model = QuestionGate(train_q.shape[1], kind=kind)
    initial = parameters(model)
    with torch.inference_mode(False):
        q, e, y = [x.detach().clone() for x in (train_q, train_e, labels)]
    if arm == "gated_reversed":
        y = 1.0-y
    history, optimizer_bytes = [], 0
    with measured() as cost, torch.enable_grad():
        if arm != "frozen_gate":
            optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=0.01)
            for step in range(steps):
                optimizer.zero_grad(set_to_none=True)
                loss = F.binary_cross_entropy_with_logits(model(q, e), y)
                c.require(bool(torch.isfinite(loss)), "nonfinite gate loss")
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
                optimizer.step()
                history.append({"step": step+1, "loss": float(loss.detach())})
            optimizer_bytes = sum(v.numel()*v.element_size() for s in optimizer.state.values() for v in s.values() if isinstance(v, torch.Tensor))
            optimizer.zero_grad(set_to_none=True)
    model.eval().requires_grad_(False)
    c.require(input_digest == c.digest([tensor_digest(x) for x in (train_q, train_e, labels)]), "fit changed shared features")
    return model, {"arm": arm, "seed": seed, "optimizer_steps": len(history), "initial": initial,
                   "saved_model": parameters(model), "optimizer_tensor_bytes": optimizer_bytes,
                   "history": history, "cost": cost, "encoder_updated": False,
                   "labels": "weak_pair_direction" if arm != "gated_reversed" else "deliberately_reversed_weak_direction"}


def summarize(units, predictions):
    """Keep every planned pair; labels are weak, not semantic correctness."""
    c.require(isinstance(predictions, list) and len({p["pair_id"] for p in predictions}) == len(predictions), "duplicate predictions")
    index = {r["pair_id"]: r for r in predictions}
    c.require(set(index) == {r["pair_id"] for r in units}, "changed prediction denominator")
    result = []
    for split in ("train", "select"):
        selected = [u for u in units if u["split"] == split]
        margins, families, joint = [], defaultdict(list), 0
        unavailable = 0
        for unit in selected:
            row = index[unit["pair_id"]]
            if unit["status"] != "available":
                c.require(row["status"] == "unavailable" and row["logits"] is None, "missing pair imputed")
                unavailable += 1
                continue
            c.require(row["status"] == "succeeded" and isinstance(row["logits"], list) and len(row["logits"]) == 2
                      and all(c.finite(x, -1e12, 1e12) for x in row["logits"]), "missing/invalid prediction")
            a, b = row["logits"]
            margins.append(a-b); families[unit["family"]].append(a-b)
            joint += a > 0 and b < 0
        result.append({"split": split, "planned_pairs": len(selected), "scored_pairs": len(margins),
                       "unavailable_pairs": unavailable, "joint_weak_direction": joint,
                       "positive_paired_ranking": sum(x > 0 for x in margins),
                       "mean_margin": sum(margins)/len(margins) if margins else None,
                       "family_macro_margin": sum(sum(v)/len(v) for v in families.values())/len(families) if families else None,
                       "semantic_accuracy": None, "probability_calibrated": False,
                       "independent_confirmation": False, "reader_adequacy_established": False})
    return result
