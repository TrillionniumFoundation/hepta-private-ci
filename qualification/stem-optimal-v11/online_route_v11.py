"""Fit-only calibrated *per-input* lexical-to-Encoder route, with zero model calls.

V8 ranked the entire retrospective TEST batch and was not an online policy.
V11 freezes an out-of-fold TRAIN-only margin threshold. At inference each
request is independently routed using only its own cheap prediction. Historical
BANKING77 TEST labels have already been exposed: no prospective validity.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import sys

SOURCE_SHA = "3e79b3449f3b63d1f261ae4ad9632ae4cff07262a82c5259a17d040e61929900"
SCHEMA = "hepta.stem.online-fit-only-route.v11"
ARMS = ("word_12_tfidf_centroid", "char_345_tfidf_centroid")
CHAR = ARMS[1]
T = 8.0  # Frozen BEFORE calibrating the decision boundary.
FOLDS = 4
TARGET_TRAIN_ESCALATIONS = 16  # Target 25% of 64 FIT OOF rows; not 8/32 TEST.
MAX_VOCAB = 100_000


def need(value, reason):
    if not value:
        raise ValueError(reason)


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def grams(text):
    normalized = " ".join(text.casefold().split())
    return [normalized[i:i+n] for n in (3, 4, 5)
            for i in range(max(0, len(normalized)-n+1))]


def assign_folds(fit):
    need(type(fit) is list and len(fit) == 64, "fit train-only case count")
    folds = {}
    for label in range(4):
        group = [r for r in fit if type(r.get("label")) is int and r["label"] == label]
        need(len(group) == 16, "not original balanced fit roster")
        group.sort(key=lambda r: sha(("stem-v11-fit-only-fold\x00" + r["case_id"]).encode()))
        for index, row in enumerate(group):
            need(row["case_id"] not in folds, "duplicate source ID")
            folds[row["case_id"]] = index % FOLDS
    need(len(folds) == 64, "fold assignment incomplete")
    return folds


def reference_predict(fit, queries):
    """Reference lexical scorer with vocabulary+supervision restricted to fit.

    Independent of the V4 implementation; parity with archived original V4
    64-FIT/32-TEST probabilities is mandatory before route publication.
    """
    need(type(fit) is list and len(fit) in (48, 64)
         and type(queries) is list and len(queries) > 0, "invalid fit-only encoder count")
    counts = [Counter(grams(r["text"])) for r in fit]
    df = Counter(word for bag in counts for word in bag)
    need(0 < len(df) <= MAX_VOCAB, "invalid train-only lexical vocabulary")
    idf = {word: math.log((1 + len(fit)) / (1 + n)) + 1.0
           for word, n in df.items()}

    def vector(bag):
        weighted = {word: count * idf[word] for word, count in bag.items() if word in idf}
        length = math.sqrt(sum(v * v for v in weighted.values()))
        return {word: value / length for word, value in weighted.items()} if length else {}

    fitted = [vector(bag) for bag in counts]
    prototypes = [Counter() for _ in range(4)]
    for row, features in zip(fit, fitted):
        label = row["label"]
        need(type(label) is int and 0 <= label < 4, "fit class out of range")
        prototypes[label].update(features)
    unit = []
    for proto in prototypes:
        length = math.sqrt(sum(v * v for v in proto.values()))
        need(length > 0, "empty fit-only class centroid")
        unit.append({word: value / length for word, value in proto.items()})
    answer = []
    for row in queries:
        x = vector(Counter(grams(row["text"])))
        logits = [T * sum(value * proto.get(word, 0.0) for word, value in x.items())
                  for proto in unit]
        shift = max(logits)
        exp = [math.exp(logit - shift) for logit in logits]
        probs = [v / sum(exp) for v in exp]
        need(all(math.isfinite(p) and 0 <= p <= 1 for p in probs),
             "nonfinite no-gold cheap probability")
        answer.append(probs)
    return answer


def margin(probs):
    need(type(probs) is list and len(probs) == 4 and
         all(type(x) in (float, int) and math.isfinite(x) and 0 <= x <= 1 for x in probs)
         and abs(sum(probs) - 1) <= 1e-9, "bad label-free cheap probabilities")
    first, second = sorted(probs, reverse=True)[:2]
    return first - second


def trained_threshold(fit):
    folds = assign_folds(fit)
    scores = {}
    for k in range(FOLDS):
        trained = [r for r in fit if folds[r["case_id"]] != k]
        validation = [r for r in fit if folds[r["case_id"]] == k]
        need(len(trained) == 48 and len(validation) == 16,
             "stratified calibration fold drift")
        for row, p in zip(validation, reference_predict(trained, validation)):
            scores[row["case_id"]] = margin(p)
    need(len(scores) == 64, "missing out-of-fold margins")
    ordered = sorted(scores.values())
    lo, hi = ordered[TARGET_TRAIN_ESCALATIONS - 1], ordered[TARGET_TRAIN_ESCALATIONS]
    need(lo < hi, "unresolvable exact margin tie at train-only budget boundary")
    threshold = (lo + hi) / 2
    need(math.isfinite(threshold) and 0 < threshold < 1,
         "invalid fit-only threshold")
    return threshold, scores


def build(fit, heldout, archived_cheap_rows):
    """Online per-row decisions; TEST membership or other request is not consulted.

    The 32-item collection is for retrospective observation only: it is not
    ranked to decide who receives a neural forward. Its size is not used to
    derive thresholds or a global top-K. The route could consume one request.
    """
    need(type(heldout) is list and len(heldout) == 32, "historical cohort missing")
    folds = assign_folds(fit)
    threshold, oof = trained_threshold(fit)
    pred = reference_predict(fit, heldout)
    by_id = {r["case_id"]: r for r in archived_cheap_rows}
    need(len(by_id) == len(archived_cheap_rows) == 32 and
         set(by_id) == {r["case_id"] for r in heldout},
         "original published cheap cohort mismatch")
    rows = []
    for r, p in zip(heldout, pred):
        archived = by_id[r["case_id"]]
        need(type(archived) is dict and set(archived) == {"case_id", "source_sha256", "scores"}
             and archived["source_sha256"] == r["source_sha256"]
             and set(archived["scores"]) == set(ARMS),
             "archived cheap source/arm substitution")
        target = archived["scores"][CHAR]
        need(type(target) is list and len(target) == 4 and
             all(abs(a - b) <= 1e-12 for a, b in zip(p, target)),
             "independent lexical numeric replay disagrees with frozen V4")
        m = margin(p)
        rows.append({"case_id": r["case_id"], "source_sha256": r["source_sha256"],
                     "cheap_probabilities": p, "cheap_margin": m,
                     "escalate": m <= threshold})
    selected = [r["case_id"] for r in rows if r["escalate"]]
    return {"schema": SCHEMA, "policy": "train-stratified-4fold-25pct-oof-margin-threshold",
            "source_plan_sha256": SOURCE_SHA, "temperature": T,
            "fit_fold_census": {str(i): sum(v == i for v in folds.values()) for i in range(FOLDS)},
            "fit_oof_scores_sha256": sha(canonical(oof)),
            "fit_oof_margin_boundary": threshold,
            "target_fit_escalations": TARGET_TRAIN_ESCALATIONS,
            "historical_heldout_count": 32, "actual_historical_route_count": len(selected),
            "selected_case_ids": selected, "rows": rows,
            "whole_batch_test_ranking_used": False,
            "test_labels_used_for_selection": False,
            "actual_new_pretrained_encoder_forwards": 0,
            "physical_encoder_savings_verified": False,
            "source_independent_families": 1, "future_windows": 0,
            "previous_test_gold_exposed": True,
            "production_authorized": False, "cell_split_authorized": False,
            "stem_winner_verified": False, "disposition": "HOLD_NO_GO", "authority": "DENY_ALL"}


def verify_source(source, cheap):
    need(type(source) is dict and source.get("schema") == "hepta.stem.charge-stress.source.v3"
         and source.get("source_plan_sha256") == SOURCE_SHA
         and source.get("heldout_labels_excluded") is True and
         source.get("production_authorized") is False and
         len(source.get("train", [])) == 64 and len(source.get("heldout", [])) == 32,
         "unexpected original source/label authority")
    need(type(cheap) is dict and cheap.get("schema") == "hepta.stem.hard-charge.lexical-control.v4"
         and cheap.get("source_plan_sha256") == SOURCE_SHA
         and cheap.get("authority") == "DENY_ALL"
         and cheap.get("production_authorized") is False and cheap.get("future_windows") == 0
         and cheap.get("cost", {}).get("neural_encoder_forward_count") == 0,
         "unexpected original cheap authority")
    need(sha(canonical({k: v for k, v in source.items()
                        if k != "source_plan_sha256"})) == SOURCE_SHA,
         "actual canonical publisher source does not match immutable plan")
    need(all(type(r) is dict and set(r) == {"case_id", "source_sha256", "text"}
             for r in source["heldout"]), "heldout labels exposed")
    for typ in ("train", "heldout"):
        for row in source[typ]:
            allowed = {"case_id", "source_sha256", "text", "label"} if typ == "train" else {"case_id", "source_sha256", "text"}
            need(type(row) is dict and set(row) == allowed and
                 row["case_id"] == ("fit:" if typ == "train" else "heldout:") + row["source_sha256"] and
                 sha(row["text"].encode()) == row["source_sha256"],
                 "source row bytes and case digest differ")
    return build(source["train"], source["heldout"], cheap["rows"])


def main():
    import argparse
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "stem-optimal-v5"))
    import paired_review_v5 as original
    parser = argparse.ArgumentParser()
    for key in ("manifest", "zip-dir", "output"):
        parser.add_argument("--" + key, required=True)
    args = parser.parse_args()
    lock = json.loads(Path(args.manifest).read_text())
    need(lock["schema"] == "hepta.stem.original-hard-charge.lock.v5"
         and lock["authority"] == "DENY_ALL", "wrong original archive lock")
    folder = Path(args.zip_dir)
    docs = {role: original.locked_json(folder / (role + ".zip"), lock["artifacts"], role)
            for role in ("source_v3", "source_v4", "cheap_v4")}
    need(docs["source_v3"] == docs["source_v4"], "old publisher cohorts disagree")
    result = verify_source(docs["source_v3"], docs["cheap_v4"])
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as f:
        f.write(canonical(result) + b"\n")
    print(json.dumps({"sha256": sha(output.read_bytes()), "eligible": len(result["selected_case_ids"]),
                      "authority": "DENY_ALL"}, sort_keys=True))


if __name__ == "__main__":
    main()
