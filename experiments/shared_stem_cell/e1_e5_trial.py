"""Read-only E1/E2: real optimizer on externally sealed frozen Stem features.

The runner sees TRAIN labels only. It NEVER downloads/models/claims a producer,
reader, NDU, independent evaluation, hardware batch, or production authority.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
import math
from pathlib import Path
import time

import torch
from torch import nn
from torch.nn import functional as F

from execution import InputError, bound_file, decode, integer, measured, parameters, sha, write_once

MODELS = {
    "granite97": (384, "cls_l2", "ibm-granite/granite-embedding-97m-multilingual-r2"),
    "mmbert_small": (384, "masked_mean_l2", "jhu-clsp/mmBERT-small"),
    "embeddinggemma2_text": (256, "mrl256_l2", "google/embeddinggemma-2"),
}
PHASES = ("train", "calibration", "test", "future1", "future2", "future3", "ood")
LANGUAGES = {"en", "zh", "code"}
BUDGETS = (2048, 8192, 16384)
MODALITIES = {"text", "image", "audio", "video"}


def digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def read_json(path: Path, expected: str, limit=32 * 1024 * 1024):
    return decode(bound_file(path, expected, limit))


def vector(value, dim, label):
    if not isinstance(value, list) or len(value) != dim:
        raise InputError("wrong vector shape: " + label)
    if any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 8 for v in value):
        raise InputError("nonfinite/out-of-bounds feature: " + label)
    if math.fsum(v * v for v in value) < 1e-12:
        raise InputError("zero vector: " + label)
    return [float(v) for v in value]


def probabilities(value):
    if not isinstance(value, list) or len(value) != 2 or any(type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= 1 for v in value) or abs(sum(value) - 1) > 1e-6:
        raise InputError("invalid two-class probability")
    return [float(x) for x in value]


def ensure_keys(record, expected, entity):
    if type(record) is not dict or set(record) != set(expected):
        raise InputError("invalid " + entity + " fields")


def load_inputs(root: Path, config: dict):
    ensure_keys(config, {"schema", "models", "files", "steps", "seed", "head_budgets"}, "plan")
    if config["schema"] != "hepta.stem-e1-e5.trial.v1" or set(config["models"]) != set(MODELS):
        raise InputError("missing fixed three-way Stem matrix")
    if config["head_budgets"] != list(BUDGETS):
        raise InputError("missing fixed 2K/8K/16K budgets")
    integer(config["steps"], 1, 2048, "steps")
    integer(config["seed"], 0, 2**31 - 1, "seed")
    if set(config["files"]) != {"cases", "features", "train_labels", "nochange"}:
        raise InputError("incomplete input inventory")
    inventories = {}
    for key, (width, pooling, source) in MODELS.items():
        item = config["models"][key]
        ensure_keys(item, {"source", "revision", "weights_sha256", "preprocessor_sha256", "pooling", "width", "external_forward_receipt_sha256", "actual_pretrained_forward_claimed"}, "model")
        if (item["source"] != source or item["width"] != width or item["pooling"] != pooling
                or not isinstance(item["revision"], str) or len(item["revision"]) != 40
                or any(c not in "0123456789abcdef" for c in item["revision"])
                or any(not digest(item[x]) for x in ("weights_sha256", "preprocessor_sha256", "external_forward_receipt_sha256"))
                or item["actual_pretrained_forward_claimed"] is not True):
            raise InputError("unverified or incompatible model declaration: " + key)
        inventories[key] = item
    sources = {}
    for key, spec in config["files"].items():
        ensure_keys(spec, {"path", "sha256"}, "input file")
        rel = Path(spec["path"])
        if rel.is_absolute() or not rel.parts or ".." in rel.parts or not digest(spec["sha256"]):
            raise InputError("unbound or unsafe input path")
        target = root / rel
        if any(path.is_symlink() for path in (target, *list(target.parents)) if path == root or root in path.parents):
            raise InputError("linked input path component")
        sources[key] = read_json(target, spec["sha256"], 128 * 1024 * 1024 if key == "features" else 32 * 1024 * 1024)
        if not isinstance(sources[key], list) or not sources[key]:
            raise InputError("empty or non-list input: " + key)
    cases, groups, contents = {}, {}, {}
    per_split_time = defaultdict(list)
    cells = set()
    for row in sources["cases"]:
        ensure_keys(row, {"case_id", "group_id", "split", "observed_at", "cell_id", "scope", "generation", "language", "modality", "input_sha256", "state"}, "case")
        if (any(not isinstance(row[k], str) or not row[k] or len(row[k].encode()) > 256 for k in ("case_id", "group_id", "cell_id", "scope"))
                or row["split"] not in PHASES or row["language"] not in LANGUAGES or row["modality"] not in MODALITIES
                or not digest(row["input_sha256"]) or row["case_id"] in cases):
            raise InputError("invalid/duplicate case identity")
        integer(row["observed_at"], 0, 2**62, "observation time")
        integer(row["generation"], 1, 2**62, "generation")
        row["state"] = vector(row["state"], 64, "state")
        if row["group_id"] in groups and groups[row["group_id"]] != row["split"]:
            raise InputError("source-group leakage across windows")
        if row["input_sha256"] in contents and contents[row["input_sha256"]] != row["split"]:
            raise InputError("content leakage across windows")
        groups[row["group_id"]] = contents[row["input_sha256"]] = row["split"]
        per_split_time[row["split"]].append(row["observed_at"])
        cells.add((row["scope"], row["cell_id"]))
        cases[row["case_id"]] = row
    if len(cases) > 2048 or len(cells) > 64 or not set(PHASES) <= set(per_split_time):
        raise InputError("incomplete train/calibration/test/future/OOD cohort")
    for previous, following in zip(PHASES[:6], PHASES[1:6]):
        if max(per_split_time[previous]) >= min(per_split_time[following]):
            raise InputError("chronology violation")
    features = {}
    for row in sources["features"]:
        ensure_keys(row, {"case_id", "model_id", "input_sha256", "vector", "query_vector", "evidence_vector", "revision", "weights_sha256", "producer_receipt_sha256"}, "feature")
        key = (row["model_id"], row["case_id"])
        if (row["model_id"] not in MODELS or row["case_id"] not in cases or key in features
                or row["input_sha256"] != cases[row["case_id"]]["input_sha256"]):
            raise InputError("unmatched, duplicated or replaced feature")
        inv = inventories[row["model_id"]]
        if any(row[field] != inv[inventory_field] for field, inventory_field in (("revision", "revision"), ("weights_sha256", "weights_sha256"), ("producer_receipt_sha256", "external_forward_receipt_sha256"))):
            raise InputError("feature not bound to declared model")
        width = MODELS[row["model_id"]][0]
        for name in ("vector", "query_vector", "evidence_vector"):
            row[name] = vector(row[name], width, name)
        features[key] = row
    if set(features) != {(model, case) for model in MODELS for case in cases}:
        raise InputError("incomplete identical-case three-model feature coverage")
    labels = {}
    for row in sources["train_labels"]:
        ensure_keys(row, {"case_id", "label"}, "training label")
        if row["case_id"] not in cases or cases[row["case_id"]]["split"] != "train" or row["case_id"] in labels:
            raise InputError("future/test label attempted to enter trainer")
        labels[row["case_id"]] = integer(row["label"], 0, 1, "train label")
    if set(labels) != {k for k, r in cases.items() if r["split"] == "train"}:
        raise InputError("incomplete train labels")
    baseline = {}
    for row in sources["nochange"]:
        ensure_keys(row, {"case_id", "input_sha256", "probabilities", "nochange_source_sha256"}, "nochange")
        case = cases.get(row["case_id"])
        if not case or row["case_id"] in baseline or row["input_sha256"] != case["input_sha256"] or not digest(row["nochange_source_sha256"]):
            raise InputError("unmatched/forged nochange baseline")
        baseline[row["case_id"]] = probabilities(row["probabilities"])
    if set(baseline) != set(cases):
        raise InputError("incomplete independent nochange case coverage")
    for scope, cell in cells:
        slots = {r["split"] for r in cases.values() if (r["scope"], r["cell_id"]) == (scope, cell)}
        if "train" not in slots or "test" not in slots:
            raise InputError("every Cell needs train and true test observations")
    return cases, features, labels, baseline


class ResidualCellHead(nn.Module):
    """Zero-output residual, baseline probabilities carried outside the learned Head."""
    def __init__(self, width: int, ceiling: int, *, anchored: bool):
        super().__init__()
        rank = min(64, (ceiling - 2) // (width + 64 + 2 + 1))
        if rank < 1:
            raise InputError("Head budget too small")
        self.width = width
        self.anchored = anchored
        self.down = nn.Linear(width, rank, bias=False)
        self.gate = nn.Linear(64, rank)
        self.up = nn.Linear(rank, 2)
        if anchored:
            nn.init.zeros_(self.up.weight)
            nn.init.zeros_(self.up.bias)
        if self.parameter_count() > ceiling:
            raise InputError("unaccounted Head parameters")

    def parameter_count(self):
        return sum(p.numel() for p in self.parameters())

    def forward(self, features, states, log_baseline):
        delta = self.up(F.silu(self.down(features.detach())) * torch.sigmoid(self.gate(states.detach())))
        return (log_baseline.detach() + delta) if self.anchored else delta


def _matrix(rows, model, features, baseline):
    xs = torch.tensor([features[(model, r["case_id"])]["vector"] for r in rows], dtype=torch.float32)
    states = torch.tensor([r["state"] for r in rows], dtype=torch.float32)
    probs = torch.tensor([baseline[r["case_id"]] for r in rows], dtype=torch.float32)
    return xs, states, probs.clamp_min(1e-7).log()


def _cosine(q, e):
    return math.fsum(x * y for x, y in zip(q, e)) / (math.sqrt(math.fsum(x*x for x in q)) * math.sqrt(math.fsum(y*y for y in e)))


def fit(model, rows, x, state, base, labels, steps, seed):
    original = parameters(model)
    learned = deepcopy(model).train()
    optim = torch.optim.AdamW(learned.parameters(), lr=0.003, weight_decay=0.0)
    generator = torch.Generator().manual_seed(seed)
    train_y = torch.tensor([labels[row["case_id"]] for row in rows], dtype=torch.long)
    with measured() as meter:
        for _ in range(steps):
            indices = torch.randint(len(rows), (min(len(rows), 16),), generator=generator)
            optim.zero_grad(set_to_none=True)
            loss = F.cross_entropy(learned(x[indices], state[indices], base[indices]), train_y[indices])
            if not bool(torch.isfinite(loss)):
                raise InputError("Head training diverged")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(learned.parameters(), 1.0, error_if_nonfinite=True)
            optim.step()
    if parameters(model) != original:
        raise InputError("frozen Head changed during training")
    return learned.eval(), {"frozen": original, "learned": parameters(learned),
                            "updates": steps, "examples_processed": steps * min(len(rows), 16), **meter}


def trial(plan: Path, plan_sha: str, output: Path):
    raw = bound_file(plan, plan_sha)
    config = decode(raw)
    cases, features, labels, baseline = load_inputs(plan.parent, config)
    records, head_receipts = [], []
    ids = sorted(cases)
    grouped = defaultdict(list)
    for row in (cases[k] for k in ids):
        grouped[row["scope"], row["cell_id"]].append(row)
    with measured() as total_meter:
        for model_index, model in enumerate(MODELS):
            for cell_index, ((scope, cell), cell_rows) in enumerate(sorted(grouped.items())):
                train_rows = [r for r in cell_rows if r["split"] == "train"]
                eval_rows = [r for r in cell_rows if r["split"] != "train"]
                x, s, p = _matrix(train_rows, model, features, baseline)
                x_eval, s_eval, p_eval = _matrix(eval_rows, model, features, baseline)
                if not eval_rows:
                    raise InputError("no Cell evaluation cases")
                train_cos = [(_cosine(features[(model, r["case_id"])]["query_vector"],
                                      features[(model, r["case_id"])]["evidence_vector"]), labels[r["case_id"]]) for r in train_rows]
                thresholds = sorted({v for v, _ in train_cos} | {0.0})
                threshold = min(thresholds, key=lambda t: (sum((int(v >= t) != y) for v, y in train_cos), t))
                for budget in BUDGETS:
                    for variant in ("anchored", "from_zero"):
                        seed = config["seed"] + 100000 * model_index + 1000 * cell_index + budget + int(variant == "from_zero")
                        torch.manual_seed(seed)
                        initial = ResidualCellHead(x.shape[1], budget, anchored=(variant == "anchored")).eval()
                        with torch.no_grad():
                            if variant == "anchored" and not torch.allclose(initial(x, s, p).softmax(-1), p.exp(), atol=1e-6, rtol=0):
                                raise InputError("initial residual is not exact nochange")
                        learned, receipt = fit(initial, train_rows, x, s, p, labels, config["steps"], seed)
                        head_receipts.append({"model_id": model, "scope": scope, "cell_id": cell, "budget": budget,
                                              "variant": variant, "trainable_parameters": initial.parameter_count(), **receipt})
                        with torch.no_grad():
                            frozen = initial(x_eval, s_eval, p_eval).softmax(-1).tolist()
                            trained = learned(x_eval, s_eval, p_eval).softmax(-1).tolist()
                        arm = model + ":" + str(budget) + ":" + variant
                        for r, f, t in zip(eval_rows, frozen, trained):
                            f = probabilities(f)
                            t = probabilities(t)
                            original = baseline[r["case_id"]]
                            vectors = features[(model, r["case_id"])]
                            c = _cosine(vectors["query_vector"], vectors["evidence_vector"])
                            cosine_probability = 1 / (1 + math.exp(-5 * (c - threshold)))
                            records.append({"case_id": r["case_id"], "input_sha256": r["input_sha256"],
                                            "scope": scope, "cell_id": cell, "split": r["split"], "model_id": model,
                                            "arm": arm, "nochange_probabilities": original,
                                            "frozen_probabilities": f, "learned_probabilities": t,
                                            "cosine_probabilities": [1 - cosine_probability, cosine_probability],
                                            "cosine_train_only_threshold": threshold})
    output.parent.mkdir(parents=True, exist_ok=True)
    return write_once(output, {"schema": "hepta.stem-e1-e5.sealed-predictions.v1",
        "plan_sha256": sha(raw), "source_file_sha256s": {k: config["files"][k]["sha256"] for k in sorted(config["files"])},
        "source_model_revisions": {key: item["revision"] for key, item in sorted(config["models"].items())},
        "results": records, "head_receipts": head_receipts, "costs": total_meter,
        "feature_forward_in_this_runner": 0, "producer_weights_independently_authenticated": False,
        "independent_outcome_evaluated": False, "reader_adequacy_established": False,
        "e3_e4_real_media_qualified": False, "e5_native_worker_qualified": False,
        "production_promotion_permitted": False})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print("sealed_sha256=" + trial(args.plan, args.plan_sha256, args.output))
