"""Train-only lexical controls for the original hard-charge Stem cohort.

These are real, inexpensive text classifiers, NOT pretrained neural Encoders.
Research-only; source and label provenance are rechecked by a separate reviewer.
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
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stem-optimal-v3"))
import stem_hard_charge_v3 as cohort

SOURCE = "hepta.stem.charge-stress.source.v3"
SCHEMA = "hepta.stem.hard-charge.lexical-control.v4"
ARMS = ("word_12_tfidf_centroid", "char_345_tfidf_centroid")
SEEDLESS = "fixed-train-only-unsupervised-idf"
TEMPERATURE = 8.0
MAX_VOCAB = 100_000


def terms(text, mode):
    if mode == ARMS[0]:
        tokens = re.findall(r"[a-z0-9]+", text.casefold())
        return tokens + [tokens[i] + "\x1f" + tokens[i + 1]
                         for i in range(len(tokens) - 1)]
    normalized = " ".join(text.casefold().split())
    return [normalized[i:i+n] for n in (3, 4, 5)
            for i in range(max(0, len(normalized)-n+1))]


def _vectors(texts, mode):
    train = [Counter(terms(text, mode)) for text in texts[:64]]
    vocabulary = set().union(*(set(c) for c in train))
    if not vocabulary or len(vocabulary) > MAX_VOCAB:
        raise ValueError("train-only lexical vocabulary bound")
    document_freq = Counter(t for c in train for t in c)
    idf = {t: math.log((1 + 64) / (1 + n)) + 1.0
           for t, n in document_freq.items()}
    vectors = []
    for text in texts:
        raw = Counter(terms(text, mode))
        weighted = {t: v * idf[t] for t, v in raw.items() if t in idf}
        norm = math.sqrt(sum(x*x for x in weighted.values()))
        vectors.append({t: v/norm for t, v in weighted.items()} if norm else {})
    return vectors, len(vocabulary)


def _classify(vectors, labels):
    prototypes = [Counter() for _ in range(4)]
    for i, label in enumerate(labels):
        if type(label) is not int or not 0 <= label < 4:
            raise ValueError("fit-only label range")
        prototypes[label].update(vectors[i])
    prototype_unit = []
    for c in prototypes:
        norm = math.sqrt(sum(v*v for v in c.values()))
        if norm <= 0:
            raise ValueError("empty supervised cheap prototype")
        prototype_unit.append({k: v/norm for k, v in c.items()})
    predictions = []
    for v in vectors[64:]:
        cosine = [sum(x * p.get(t, 0.0) for t, x in v.items())
                  for p in prototype_unit]
        logits = [TEMPERATURE * x for x in cosine]
        m = max(logits)
        exps = [math.exp(x-m) for x in logits]
        total = sum(exps)
        probs = [x/total for x in exps]
        if not all(math.isfinite(x) for x in probs):
            raise ValueError("lexical control nonfinite")
        predictions.append(probs)
    return predictions


def compute(source, *, hashes=cohort.base.ORIGINAL_SHA):
    cohort.verify_source(source, hashes=hashes)
    texts = [row["text"] for row in source["train"] + source["heldout"]]
    fit_labels = [row["label"] for row in source["train"]]
    start = time.perf_counter()
    cpu_start = time.process_time()
    outcomes, vocab = {}, {}
    for mode in ARMS:
        vectors, n_vocab = _vectors(texts, mode)
        outcomes[mode] = _classify(vectors, fit_labels)
        vocab[mode] = n_vocab
    rows = []
    for j, row in enumerate(source["heldout"]):
        rows.append({"case_id": row["case_id"], "source_sha256": row["source_sha256"],
                     "scores": {mode: outcomes[mode][j] for mode in ARMS}})
    result = {
        "schema": SCHEMA, "cohort": cohort.COHORT,
        "publisher_revision": cohort.base.ORIGINAL_COMMIT,
        "source_plan_sha256": source["source_plan_sha256"],
        "algorithm": SEEDLESS, "temperature": TEMPERATURE,
        "training_rows": 64, "prediction_rows": 32,
        "lexical_vocabulary": vocab, "rows": rows,
        "cost": {
            "elapsed_wall_seconds": time.perf_counter() - start,
            "elapsed_cpu_seconds": time.process_time() - cpu_start,
            "maxrss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "neural_encoder_forward_count": 0,
            "pretrained_model_loaded": False,
            "energy_joules": None, "p99_latency_ms": None,
        },
        "source_independent_families": 1, "future_windows": 0,
        "production_authorized": False, "stem_winner_verified": False,
        "disposition": "HOLD_NO_GO", "authority": "DENY_ALL",
    }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source = json.loads(Path(args.source).read_text(encoding="utf-8"))
    result = compute(source)
    path = cohort.base._write_new(args.output, result)
    print(json.dumps({"output_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                      "authority": result["authority"], "disposition": result["disposition"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
