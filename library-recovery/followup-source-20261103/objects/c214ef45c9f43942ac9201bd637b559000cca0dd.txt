"""Read-only equal-size Stem P0: source/receipt gates and independent blind scoring.

This module cannot load models, issue capabilities, mutate weights, or select a Stem.
It consumes *self-reported* experiment receipts, never elevating them to authority.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict

SCHEMA = "hepta.stem.equal-size.p0.v1"
AUTHORITY = "DENY_ALL"
# Fixed externally published revisions; weights/tokenizers are NOT verified by this file.
# Parameter counts are upstream approximate class sizes, not runtime tensor censuses.
MODELS = {
    "laya421": ("convaiinnovations/laya", "c5d78730f3493e4fe16d61507ef4b78eef7318cf", 421_000_000, "native"),
    "laya_typed421": ("convaiinnovations/laya-typed-decisions", "cff2845e45c4e04b89fe1b6bd5eb5b6cac56bcb4", 421_000_000, "native"),
    "ettin400": ("jhu-clsp/ettin-encoder-400m", "7662476d60abb071a5bd319c9f3074f3072c062d", 400_000_000, "head"),
    "openjev434": ("com-kotobalabs/open-jev-deberta-v3-large", "188ee67a5c93122b916e5acd5bdb0cb3623e380a", 434_000_000, "native"),
}
SHA_BYTES = 32
MAX_CASES = 8192
MAX_TOKENS = 512


class Denied(ValueError):
    """Evidence is insufficient or inconsistent. Fail closed rather than rank."""


def require(condition, message):
    if not condition:
        raise Denied(message)


def digest(value):
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise Denied("non-canonical or nonfinite evidence") from exc
    return hashlib.sha256(encoded).hexdigest()


def sha(value):
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def nat(value, *, positive=False):
    return type(value) is int and value >= (1 if positive else 0)


def strict_load(path):
    """Reject duplicate JSON object keys and nonfinite numbers before validation."""
    def unique(pairs):
        result = {}
        for k, v in pairs:
            require(k not in result, "duplicate JSON key")
            result[k] = v
        return result
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f, object_pairs_hook=unique, parse_constant=lambda _: require(False, "nonfinite JSON"))


def validate_panel(panel):
    require(type(panel) is dict and set(panel) == {"schema", "source_revision", "source_material_sha256",
                                                  "purpose", "budget", "cases", "authority",
                                                  "production_promotion_permitted", "future_window_verified"},
            "invalid panel shape")
    require(panel["schema"] == SCHEMA and panel["authority"] == AUTHORITY and
            panel["production_promotion_permitted"] is False and panel["future_window_verified"] is False,
            "panel cannot confer authority or pretend future evidence")
    require(type(panel["source_revision"]) is str and len(panel["source_revision"]) == 40 and
            all(c in "0123456789abcdef" for c in panel["source_revision"]) and
            sha(panel["source_material_sha256"]), "source must be pinned to real bytes")
    require(panel["purpose"] == "binary-support-research-only", "different tasks cannot be compared")
    b = panel["budget"]
    require(type(b) is dict and set(b) == {"max_tokens", "head_steps", "head_trainable_params",
                                            "head_seed", "head_optimizer", "precision"} and
            nat(b["max_tokens"], positive=True) and b["max_tokens"] <= MAX_TOKENS and
            nat(b["head_steps"], positive=True) and b["head_steps"] <= 4096 and
            nat(b["head_trainable_params"], positive=True) and b["head_trainable_params"] <= 100_000 and
            nat(b["head_seed"]) and b["head_optimizer"] == "sgd-lr-0.1" and
            b["precision"] == "float32", "unmatched or unbounded head budget")
    cases = panel["cases"]
    require(type(cases) is list and 3 <= len(cases) <= MAX_CASES, "invalid case count")
    ids, by_group, counts = set(), {}, defaultdict(int)
    for c in cases:
        require(type(c) is dict and set(c) == {"case_id", "group_id", "family_id", "split",
                                                  "source_sha256", "input_sha256", "token_count"},
                "case label, text, or unknown field forbidden in blind panel")
        for key in ("case_id", "group_id", "family_id"):
            v = c[key]
            require(type(v) is str and 1 <= len(v) <= 128 and v.isascii() and not any(x.isspace() for x in v),
                    "invalid bounded source identity")
        require(c["case_id"] not in ids, "duplicate case across splits")
        ids.add(c["case_id"])
        require(c["split"] in ("fit", "cal", "test") and sha(c["source_sha256"]) and
                sha(c["input_sha256"]) and nat(c["token_count"], positive=True) and
                c["token_count"] <= b["max_tokens"], "source or token-bound mismatch")
        # Same original source bytes cannot be relabeled as a different independent group.
        old = by_group.setdefault(c["source_sha256"], (c["group_id"], c["split"]))
        require(old == (c["group_id"], c["split"]), "source-group leakage")
        counts[c["split"]] += 1
    require(all(counts[s] > 0 for s in ("fit", "cal", "test")), "empty split")
    require(len({(c["group_id"], c["split"]) for c in cases}) == len({c["group_id"] for c in cases}),
            "group crosses fit/cal/test")
    return {"panel_sha256": digest(panel), "test_ids": tuple(c["case_id"] for c in cases if c["split"] == "test"),
            "fit_count": counts["fit"], "cal_count": counts["cal"], "test_count": counts["test"]}


def validate_observation(panel, record):
    plan = validate_panel(panel)
    require(type(record) is dict and set(record) == {
        "schema", "model", "repo", "revision", "basis", "panel_sha256", "artifact_weights_sha256",
        "tokenizer_sha256", "original_tensor_bytes_verified", "trainable_params", "optimizer_steps",
        "fit_rows", "encoder_calls", "load_wall_ns", "run_wall_ns", "peak_rss_bytes",
        "predictions", "predictions_sha256", "authority", "production_promotion_permitted"},
        "malformed model observation")
    model = record["model"]
    require(model in MODELS, "unregistered model")
    repo, rev, _, basis = MODELS[model]
    require(record["schema"] == SCHEMA and record["repo"] == repo and
            record["revision"] == rev and record["basis"] == basis and
            record["panel_sha256"] == plan["panel_sha256"] and
            sha(record["artifact_weights_sha256"]) and sha(record["tokenizer_sha256"]) and
            record["original_tensor_bytes_verified"] is True and
            record["authority"] == AUTHORITY and record["production_promotion_permitted"] is False,
            "wrong model, input, claimed tensor verification, or authority")
    b = panel["budget"]
    if basis == "head":
        require(record["optimizer_steps"] == b["head_steps"] and
                record["trainable_params"] == b["head_trainable_params"] and
                record["fit_rows"] == plan["fit_count"], "head training budget mismatch")
    else:
        require(record["optimizer_steps"] == 0 and record["trainable_params"] == 0 and
                record["fit_rows"] == 0, "native pretrained checkpoint cannot impersonate a matched head")
    for k in ("encoder_calls", "load_wall_ns", "run_wall_ns", "peak_rss_bytes"):
        require(nat(record[k], positive=True), "missing observed physical resource cost")
    preds = record["predictions"]
    require(type(preds) is list and len(preds) == plan["test_count"] and
            record["predictions_sha256"] == digest(preds), "absent or unsealed predictions")
    require([p.get("case_id") for p in preds if type(p) is dict] == list(plan["test_ids"]),
            "blind outputs omitted, duplicated, re-ordered or misbound")
    for p in preds:
        require(type(p) is dict and set(p) == {"case_id", "p_positive"} and
                type(p["p_positive"]) in (int, float) and math.isfinite(p["p_positive"]) and
                0 <= p["p_positive"] <= 1, "invalid binary distribution")
    return model


def evaluate(panel, records, observer):
    """Independent, postseal descriptive scoring. NEVER selects/promotes a model."""
    plan = validate_panel(panel)
    require(type(records) is list and len(records) == len(MODELS), "partial arms cannot form a four-way winner")
    named = {}
    for record in records:
        name = validate_observation(panel, record)
        require(name not in named, "duplicate model arm")
        named[name] = record
    require(set(named) == set(MODELS), "missing model arm")
    require(type(observer) is dict and set(observer) == {"schema", "panel_sha256", "source_revision",
                                                    "sealed_prediction_digests", "original_gold_sha256",
                                                    "test_targets"}, "invalid independent gold custody")
    require(observer["schema"] == SCHEMA and observer["panel_sha256"] == plan["panel_sha256"] and
            observer["source_revision"] == panel["source_revision"] and
            sha(observer["original_gold_sha256"]), "observer provenance mismatch")
    expected_seals = {m: named[m]["predictions_sha256"] for m in named}
    require(type(observer["sealed_prediction_digests"]) is dict and
            observer["sealed_prediction_digests"] == expected_seals, "gold was read without exact earlier seals")
    targets = observer["test_targets"]
    require(type(targets) is list and len(targets) == plan["test_count"], "missing original test targets")
    require([t.get("case_id") for t in targets if type(t) is dict] == list(plan["test_ids"]),
            "reordered or invented targets")
    for t in targets:
        require(type(t) is dict and set(t) == {"case_id", "label"} and type(t["label"]) is int and
                t["label"] in (0, 1), "invalid held human label")
    score = {}
    for name in MODELS:
        ps = [r["p_positive"] for r in named[name]["predictions"]]
        ys = [t["label"] for t in targets]
        score[name] = {"accuracy": sum((p >= 0.5) == bool(y) for p, y in zip(ps, ys)) / len(ys),
                       "brier": sum((p-y)**2 for p, y in zip(ps, ys)) / len(ys),
                       "original_test_case_count": len(ys),
                       "basis": MODELS[name][3],
                       "run_wall_ns_self_reported": named[name]["run_wall_ns"]}
    return {"schema": SCHEMA, "panel_sha256": plan["panel_sha256"], "results": score,
            "promotion_permitted": False, "selected_model": None, "physical_cell_split_authorized": False,
            "disposition": "HOLD_NO_GO", "limitation": "Different native/learned regimes; unauthenticated cost, no prospective/negative-transfer/target-host proofs"}


def main(argv=None):
    """Read three physically separate JSON artifacts; emit create-only aggregate no-go."""
    import argparse
    import os
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Hepta read-only same-size P0 observer")
    parser.add_argument("--panel", required=True)
    parser.add_argument("--sealed", required=True)
    parser.add_argument("--gold", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    for input_path in (args.panel, args.sealed, args.gold):
        require(Path(input_path).is_file() and not Path(input_path).is_symlink(),
                "refuse missing or symlinked custody input")
    result = evaluate(strict_load(args.panel), strict_load(args.sealed), strict_load(args.gold))
    out = Path(args.out)
    require(out.parent.is_dir() and not out.is_symlink(), "invalid output parent")
    data = (json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(out, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        try:
            out.unlink()
        except OSError:
            pass
        raise
    print(f"HOLD_NO_GO: {len(MODELS)} research arms described, no model promoted")


if __name__ == "__main__":
    main()
