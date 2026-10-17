"""Train-only cross-fitted calibration of the original V3/V4 cheap lexical arms.

No model calls, no neural HEAD training, no publisher heldout labels. All
candidate temperatures and folds are committed before the 32-case output.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import resource
import time

SCHEMA = "hepta.stem.charge-lexical-calibration.v6"
SOURCE_SCHEMA = "hepta.stem.charge-stress.source.v3"
SOURCE_SHA = "3e79b3449f3b63d1f261ae4ad9632ae4cff07262a82c5259a17d040e61929900"
PUBLISHER = "57ec275d8078af65b7731c2a98be812d844a6d6b"
CSV_SHA = {"train": "b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b",
           "test": "d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d"}
INTENTS = ("card_payment_fee_charged", "cash_withdrawal_charge", "exchange_charge", "transfer_fee_charged")
ARMS = ("word_12_tfidf_centroid", "char_345_tfidf_centroid")
GRID = (0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0)
FOLD_SALT = "hepta-hard-charge-v6-fixed-four-stratified-folds\\0"
AUTHORITY = "DENY_ALL"


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def digest(b):
    return hashlib.sha256(b).hexdigest()


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def validate_source(source):
    need(type(source) is dict and set(source) == {
        "schema", "cohort", "intents", "publisher_revision", "publisher_sha256",
        "train", "heldout", "heldout_labels_excluded", "research_only",
        "production_authorized", "source_plan_sha256"}, "unexpected original source")
    need(source["schema"] == SOURCE_SCHEMA and source["cohort"] == "hard-charge-four-intents-v3"
         and source["intents"] == list(INTENTS) and source["publisher_revision"] == PUBLISHER
         and source["publisher_sha256"] == CSV_SHA and source["source_plan_sha256"] == SOURCE_SHA,
         "original publisher/cohort SHA mismatch")
    need(source["research_only"] is True and source["production_authorized"] is False
         and source["heldout_labels_excluded"] is True, "source authority or label admission")
    need(digest(canonical({k: v for k, v in source.items() if k != "source_plan_sha256"}))
         == SOURCE_SHA, "original source has changed")
    fit, held = source["train"], source["heldout"]
    need(type(fit) is list and len(fit) == 64 and type(held) is list and len(held) == 32,
         "original cohort cardinality")
    labels, all_ids = [0]*4, set()
    for kind, rows in (("fit", fit), ("heldout", held)):
        for row in rows:
            required = {"case_id", "source_sha256", "text", "label"} if kind == "fit" else {
                "case_id", "source_sha256", "text"}
            need(type(row) is dict and set(row) == required, "heldout label leakage")
            text = row["text"]
            need(type(text) is str and 0 < len(text.encode("utf-8")) <= 4096,
                 "invalid source text")
            h = digest(text.encode("utf-8"))
            need(row["source_sha256"] == h and row["case_id"] == kind + ":" + h
                 and h not in all_ids, "duplicate or invalid original source digest")
            all_ids.add(h)
            if kind == "fit":
                i = row["label"]
                need(type(i) is int and 0 <= i < 4, "fit-only label range")
                labels[i] += 1
    need(labels == [16]*4, "unbalanced original fit cohort")


def stratified_folds(fit):
    buckets = [[] for _ in range(4)]
    for i, row in enumerate(fit):
        buckets[row["label"]].append(i)
    fold = [-1]*64
    for indices in buckets:
        indices.sort(key=lambda i: digest((FOLD_SALT + fit[i]["case_id"]).encode("utf-8")))
        need(len(indices) == 16, "invalid frozen class population")
        for j, ix in enumerate(indices):
            fold[ix] = j % 4
    need(all(sum(f == k for f in fold) == 16 for k in range(4)),
         "non-stratified original fold assignment")
    return fold


def _terms(s, arm):
    if arm == ARMS[0]:
        words = re.findall(r"[a-z0-9]+", s.casefold())
        return words + [a + "\x1f" + b for a, b in zip(words, words[1:])]
    s = " ".join(s.casefold().split())
    return [s[i:i+length] for length in (3, 4, 5)
            for i in range(max(0, len(s) - length + 1))]


def _scores(train, predict, arm):
    need(arm in ARMS and len(train) > 4 and len(predict) <= 96, "invalid arm/workset")
    bags = [Counter(_terms(x["text"], arm)) for x in train + predict]
    df = Counter(word for bag in bags[:len(train)] for word in bag)
    need(0 < len(df) <= 100_000, "training-only lexical vocabulary bound")
    idf = {word: 1.0 + math.log((len(train) + 1) / (count + 1))
           for word, count in df.items()}
    vectors = []
    for bag in bags:
        weighted = {word: freq * idf[word] for word, freq in bag.items() if word in idf}
        norm = math.sqrt(sum(value * value for value in weighted.values()))
        vectors.append({k: value / norm for k, value in weighted.items()} if norm else {})
    centers = [Counter() for _ in range(4)]
    for j, row in enumerate(train):
        centers[row["label"]].update(vectors[j])
    normed = []
    for center in centers:
        magnitude = math.sqrt(sum(value * value for value in center.values()))
        need(magnitude > 0, "empty supervised centroid")
        normed.append({k: value / magnitude for k, value in center.items()})
    logits = []
    for row in vectors[len(train):]:
        logits.append([sum(value * center.get(k, 0.0) for k, value in row.items())
                       for center in normed])
    return logits, len(df)


def probs(cosines, temperature):
    logits = [temperature * x for x in cosines]
    anchor = max(logits)
    exponents = [math.exp(x-anchor) for x in logits]
    scale = sum(exponents)
    return [x/scale for x in exponents]


def calibrate(source):
    validate_source(source)
    fit = source["train"]
    folds = stratified_folds(fit)
    by_arm = {}
    for arm in ARMS:
        losses = [0.0]*len(GRID)
        for fold in range(4):
            tr = [r for i, r in enumerate(fit) if folds[i] != fold]
            cv = [r for i, r in enumerate(fit) if folds[i] == fold]
            cosines, _ = _scores(tr, cv, arm)
            for row, x in zip(cv, cosines):
                target = row["label"]
                for j, temp in enumerate(GRID):
                    p = probs(x, temp)
                    losses[j] += sum((value - float(i == target))**2
                                     for i, value in enumerate(p)) / 64.0
        selected_index = min(range(len(GRID)), key=lambda i: (losses[i], GRID[i]))
        cosines, vocab = _scores(fit, source["heldout"], arm)
        temp = GRID[selected_index]
        by_arm[arm] = {"temperature": temp, "cv_brier_by_temp": losses,
                       "full_train_vocabulary": vocab,
                       "heldout_probabilities": [probs(x, temp) for x in cosines]}
    return folds, by_arm


def produce(source):
    start = time.perf_counter()
    cpu = time.process_time()
    folds, arms = calibrate(source)
    rows = [{"case_id": row["case_id"], "source_sha256": row["source_sha256"],
             "scores": {arm: arms[arm]["heldout_probabilities"][i] for arm in ARMS}}
            for i, row in enumerate(source["heldout"])]
    return {"schema": SCHEMA, "source_plan_sha256": SOURCE_SHA,
            "publisher_revision": PUBLISHER,
            "cohort": source["cohort"], "fold_salt": FOLD_SALT,
            "stratification": "four_per_class_per_fold_fit_only",
            "temperature_grid": list(GRID),
            "fit_folds": [{"case_id": row["case_id"], "fold": folds[i]}
                          for i, row in enumerate(source["train"])],
            "calibration": {arm: {k: v for k, v in arms[arm].items()
                                  if k != "heldout_probabilities"} for arm in ARMS},
            "rows": rows, "cost": {"wall_seconds": time.perf_counter() - start,
                                  "cpu_seconds": time.process_time() - cpu,
                                  "process_maxrss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                                  "neural_forward_count": 0, "energy_joules": None,
                                  "p99_latency_ms": None},
            "heldout_label_access": False, "future_windows": 0,
            "independent_source_families": 1, "production_authorized": False,
            "stem_winner_verified": False, "disposition": "HOLD_NO_GO",
            "authority": AUTHORITY}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    doc = produce(json.loads(Path(args.source).read_text(encoding="utf-8")))
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:
        f.write(canonical(doc)+b"\n")
        f.flush()
    print(json.dumps({"sha256": digest(path.read_bytes()), "authority": AUTHORITY,
                      "disposition": "HOLD_NO_GO"}, sort_keys=True))


if __name__ == "__main__":
    main()
