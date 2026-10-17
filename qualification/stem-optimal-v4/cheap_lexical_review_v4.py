"""Original-publisher, independent replay of cheap lexical Stem controls.

No training/prediction producer imports. Publisher source/heldout gold reopened
after immutable prelabel receipt material exists; outcome remains DENY_ALL.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stem-optimal-v1"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stem-optimal-v3"))
import stem_hard_charge_review_v3 as original
import stem_review_v1 as publisher

SCHEMA = "hepta.stem.hard-charge.lexical-control.v4"
REVIEW_SCHEMA = "hepta.stem.hard-charge.lexical-independent-review.v4"
ARMS = ("word_12_tfidf_centroid", "char_345_tfidf_centroid")
FIELDS = {"schema", "cohort", "publisher_revision", "source_plan_sha256",
          "algorithm", "temperature", "training_rows", "prediction_rows",
          "lexical_vocabulary", "rows", "cost", "source_independent_families",
          "future_windows", "production_authorized", "stem_winner_verified",
          "disposition", "authority"}


def _tokens(text, kind):
    if kind == ARMS[0]:
        tokens = re.findall("[a-z0-9]+", text.casefold())
        return tokens + [a + "\x1f" + b for a, b in zip(tokens, tokens[1:])]
    s = " ".join(text.casefold().split())
    return [s[i:i+n] for n in range(3, 6) for i in range(max(0, len(s)-n+1))]


def _reference_predict(source, arm):
    fit = source["train"]
    texts = [r["text"] for r in fit + source["heldout"]]
    bag = [Counter(_tokens(t, arm)) for t in texts]
    df = Counter(feature for row in bag[:64] for feature in row)
    publisher._require(0 < len(df) <= 100_000, "reference training lexicon invalid")
    idf = {k: 1 + math.log(65 / (1+n)) for k, n in df.items()}
    vec = []
    for counts in bag:
        weighted = {key: value * idf[key] for key, value in counts.items() if key in idf}
        norm = math.sqrt(sum(value * value for value in weighted.values()))
        vec.append({key: value/norm for key, value in weighted.items()} if norm else {})
    class_sum = [Counter() for _ in range(4)]
    for i, case in enumerate(fit):
        class_sum[case["label"]].update(vec[i])
    centers = []
    for center in class_sum:
        magnitude = math.sqrt(sum(value**2 for value in center.values()))
        publisher._require(magnitude > 0, "reference empty class center")
        centers.append({key: value/magnitude for key, value in center.items()})
    result = []
    for row in vec[64:]:
        dot = [8.0 * sum(value * center.get(k, 0) for k, value in row.items())
               for center in centers]
        shift = max(dot)
        exp = [math.exp(value-shift) for value in dot]
        result.append([value/sum(exp) for value in exp])
    return result, len(df)


def _review(train_raw, test_raw, source, receipt, *, hashes=publisher.FIXED_SHA):
    expected, gold = original.reconstruct(train_raw, test_raw, hashes)
    publisher._require(type(source) is dict and
                       source.get("schema") == "hepta.stem.charge-stress.source.v3" and
                       source.get("cohort") == original.COHORT and
                       source.get("publisher_revision") == publisher.PINNED_REV and
                       source.get("publisher_sha256") == hashes and
                       source.get("train") == expected["train"] and
                       source.get("heldout") == expected["heldout"] and
                       source.get("heldout_labels_excluded") is True and
                       source.get("production_authorized") is False,
                       "independent V3 cohort identity mismatch")
    publisher._require(publisher._sha(publisher._json({
        k: v for k, v in source.items() if k != "source_plan_sha256"
    })) == source.get("source_plan_sha256"), "unsealed V3 cohort")
    publisher._require(type(receipt) is dict and set(receipt) == FIELDS and
                       receipt["schema"] == SCHEMA and
                       receipt["cohort"] == original.COHORT and
                       receipt["publisher_revision"] == publisher.PINNED_REV and
                       receipt["source_plan_sha256"] == source["source_plan_sha256"],
                       "lexical control source substitution")
    publisher._require(receipt["algorithm"] == "fixed-train-only-unsupervised-idf"
                       and type(receipt["temperature"]) in (int, float)
                       and receipt["temperature"] == 8.0
                       and receipt["training_rows"] == 64
                       and receipt["prediction_rows"] == 32,
                       "unexpected lexical control schedule")
    publisher._require(receipt["source_independent_families"] == 1
                       and receipt["future_windows"] == 0
                       and receipt["stem_winner_verified"] is False
                       and receipt["production_authorized"] is False
                       and receipt["disposition"] == "HOLD_NO_GO"
                       and receipt["authority"] == "DENY_ALL",
                       "falsified lexical research authority")
    cost = receipt["cost"]
    publisher._require(type(cost) is dict and set(cost) == {
        "elapsed_wall_seconds", "elapsed_cpu_seconds", "maxrss_bytes",
        "neural_encoder_forward_count", "pretrained_model_loaded",
        "energy_joules", "p99_latency_ms"
    }, "unbounded/undeclared lexical cost")
    publisher._require(all(type(cost[k]) in (int, float)
                          and math.isfinite(cost[k]) and cost[k] > 0
                          for k in ("elapsed_wall_seconds", "elapsed_cpu_seconds"))
                       and type(cost["maxrss_bytes"]) is int and cost["maxrss_bytes"] > 0
                       and cost["neural_encoder_forward_count"] == 0
                       and cost["pretrained_model_loaded"] is False
                       and cost["energy_joules"] is None
                       and cost["p99_latency_ms"] is None, "fake full lifecycle meter")
    rows = receipt["rows"]
    publisher._require(type(rows) is list and len(rows) == 32, "missing cheap control scores")
    lookup = {}
    for row in rows:
        publisher._require(type(row) is dict and
                           set(row) == {"case_id", "source_sha256", "scores"} and
                           row["case_id"] in gold and
                           row["case_id"] == "heldout:" + row["source_sha256"] and
                           row["case_id"] not in lookup and
                           type(row["scores"]) is dict and set(row["scores"]) == set(ARMS),
                           "test-label exposure, duplicate case or altered scores")
        lookup[row["case_id"]] = row["scores"]
        for probs in row["scores"].values():
            publisher._require(type(probs) is list and len(probs) == 4
                               and all(type(x) in (int, float)
                                       and math.isfinite(x) and 0 <= x <= 1
                                       for x in probs) and abs(sum(probs)-1) < 1e-10,
                               "nonfinite or invalid scores")
    publisher._require(set(lookup) == set(gold), "incomplete physical lexical cohort")
    publisher._require(type(receipt["lexical_vocabulary"]) is dict and
                       set(receipt["lexical_vocabulary"]) == set(ARMS),
                       "lexical dictionary incomplete")
    scored = {}
    for arm in ARMS:
        expected_probs, vocabulary = _reference_predict(source, arm)
        publisher._require(type(receipt["lexical_vocabulary"][arm]) is int
                           and receipt["lexical_vocabulary"][arm] == vocabulary,
                           "false train-only IDF vocabulary")
        correct, brier = 0, 0.0
        for row, reference in zip(source["heldout"], expected_probs):
            observed = lookup[row["case_id"]][arm]
            publisher._require(all(abs(a-b) < 1e-12 for a, b in zip(observed, reference)),
                               "lexical output cannot be independently recomputed")
            true = gold[row["case_id"]]
            correct += int(max(range(4), key=lambda k: observed[k]) == true)
            brier += sum((value - float(k == true))**2
                         for k, value in enumerate(observed))
        scored[arm] = {"correct": correct, "n": 32,
                       "mean_multiclass_brier": brier/32,
                       "fit_only_vocabulary": vocabulary}
    return {
        "schema": REVIEW_SCHEMA, "cohort": original.COHORT,
        "publisher_original_sha_verified": hashes == publisher.FIXED_SHA,
        "independent_label_reconstruction": True,
        "independent_algorithm_replay": True,
        "case_count": 32, "cheap_controls": scored,
        "observed_cost_unattested": cost,
        "comparisons_with_neural_v3": None,
        "source_independent_families": 1, "future_windows": 0,
        "stem_winner_verified": False, "ndu_benefit_verified": False,
        "production_authorized": False, "disposition": "HOLD_NO_GO",
        "authority": "DENY_ALL",
    }


def review_original(train_raw, test_raw, source, receipt):
    return _review(train_raw, test_raw, source, receipt, hashes=publisher.FIXED_SHA)


def main():
    args = argparse.ArgumentParser()
    for name in ("train", "test", "source", "receipt", "output"):
        args.add_argument("--" + name, required=True)
    p = args.parse_args()
    result = review_original(
        Path(p.train).read_bytes(), Path(p.test).read_bytes(),
        json.loads(Path(p.source).read_text(encoding="utf-8")),
        json.loads(Path(p.receipt).read_text(encoding="utf-8"))
    )
    out = Path(p.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("xb") as file:
        file.write(publisher._json(result) + b"\n")
        file.flush()
    print(json.dumps({"review_sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
                      "disposition": "HOLD_NO_GO", "authority": "DENY_ALL"},
                     sort_keys=True))


if __name__ == "__main__":
    main()
