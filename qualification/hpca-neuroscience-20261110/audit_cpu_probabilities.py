#!/usr/bin/env python3
"""Reconcile reported *actual model inference scores*; NEVER an adoption gate.

Source archive must be separately supplied, fixed by SHA-256, and contains
operator-exposed B and constructed C, not independent evaluation.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

SCHEMA = "HPCA-REAL-CPU-LORA-CLOCK-V1"
FAMILIES = ("B_exposed_eval", "C_operator_constructed")
ARMS = ("uniform", "heterogeneous")


def _required(condition, message):
    if not condition:
        raise ValueError(message)


def _rows(score):
    rows = score["rows"]
    _required(isinstance(rows, list) and rows, "missing outcomes")
    seen = set()
    checked = []
    for row in rows:
        identity = (row["id"], row["prompt_sha256"])
        _required(all(isinstance(s, str) and s for s in identity),
                  "empty row identity")
        _required(identity not in seen, "duplicate evaluation row")
        seen.add(identity)
        label = row["truth"]
        _required(label in ("yes", "no"), "invalid label")
        p = row["p_yes"]
        _required(type(p) in (int, float) and math.isfinite(p) and 0 < p < 1,
                  "non-finite or boundary probability")
        prediction = "yes" if p >= 0.5 else "no"
        _required(row["prediction"] == prediction, "prediction/probability drift")
        _required(type(row["correct"]) is bool and
                  row["correct"] == (prediction == label),
                  "accuracy flag drift")
        checked.append((identity, label, float(p)))
    _required(len(checked) == len(rows), "truncated outcomes")
    actual_accuracy = sum((p >= 0.5) == (y == "yes") for _, y, p in checked) / len(checked)
    _required(abs(float(score["accuracy"]) - actual_accuracy) <= 1e-12,
              "headline accuracy drift")
    return checked


def _metrics(checked):
    ys = [int(label == "yes") for _, label, _ in checked]
    ps = [p for _, _, p in checked]
    return {
        "n": len(ps),
        "accuracy": sum((p >= 0.5) == bool(y) for y, p in zip(ys, ps)) / len(ps),
        "log_loss": statistics.fmean(
            -(math.log(p) if y else math.log1p(-p))
            for y, p in zip(ys, ps)
        ),
        "brier": statistics.fmean((p - y) ** 2 for y, p in zip(ys, ps)),
    }


def analyze(archive, archive_sha256):
    _required(isinstance(archive_sha256, str) and len(archive_sha256) == 64,
              "archive SHA-256 pin required")
    _required(archive["schema"] == SCHEMA, "wrong archive schema")
    _required(archive["decision"] == "HOLD_NO_GO", "unexpected previous decision")
    seeds = archive["seeds"]
    _required(isinstance(seeds, list) and seeds and
              len(set(seeds)) == len(seeds) and
              all(type(s) is int for s in seeds), "invalid seed roster")
    runs = archive["runs"]
    _required(isinstance(runs, list) and len(runs) == 2 * len(seeds),
              "missing/extra arm")
    by_key = {}
    for run in runs:
        key = (run["seed"], run["arm"])
        _required(key[0] in seeds and key[1] in ARMS and key not in by_key,
                  "duplicate/unknown seed/arm")
        _required(run["steps"] == archive["steps_per_arm"] and
                  type(run["actual_updated_parameter_elements"]) is int and
                  run["actual_updated_parameter_elements"] > 0,
                  "opportunity count invalid")
        by_key[key] = run
    for seed in seeds:
        _required(all((seed, arm) in by_key for arm in ARMS),
                  "unpaired seed")
        u, h = (by_key[(seed, arm)] for arm in ARMS)
        _required(u["actual_updated_parameter_elements"] ==
                  h["actual_updated_parameter_elements"], "update budget mismatch")
        _required(u["input_tokens_train"] == h["input_tokens_train"],
                  "token opportunity mismatch")

    families = {}
    for family in FAMILIES:
        pairs = []
        for seed in seeds:
            u, h = (by_key[(seed, arm)] for arm in ARMS)
            u_rows = _rows(u["scores"][family])
            h_rows = _rows(h["scores"][family])
            u_identity = [(identity, label) for identity, label, _ in u_rows]
            h_identity = [(identity, label) for identity, label, _ in h_rows]
            _required(u_identity == h_identity, "unpaired tasks/labels")
            for run, rows in ((u, u_rows), (h, h_rows)):
                cold_rows = _rows(run["cold_reloaded_scores"][family])
                _required([r[:2] for r in cold_rows] ==
                          [r[:2] for r in rows], "cold reload task drift")
                _required(max(abs(a[2] - b[2]) for a, b in zip(rows, cold_rows)) < 1e-7,
                          "cold reload probability drift")
            m_u, m_h = _metrics(u_rows), _metrics(h_rows)
            pairs.append({
                "seed": seed,
                "n": m_u["n"],
                "uniform": m_u,
                "heterogeneous": m_h,
                "heterogeneous_minus_uniform": {
                    name: m_h[name] - m_u[name]
                    for name in ("accuracy", "log_loss", "brier")
                }
            })
        families[family] = {
            "paired_seeds": pairs,
            "mean_heterogeneous_minus_uniform": {
                name: statistics.fmean(
                    p["heterogeneous_minus_uniform"][name] for p in pairs
                ) for name in ("accuracy", "log_loss", "brier")
            }
        }
    return {
        "schema": "HPCA-CPU-PAIRED-PROBABILITY-AUDIT-V1",
        "source_archive_sha256": archive_sha256,
        "source_schema": SCHEMA,
        "model_identity_claims": archive["identities"],
        "seed_count": len(seeds),
        "task_families": families,
        "status": "HOLD_NO_GO",
        "authority": "READ_ONLY_NOT_OWNER_ATTESTED",
        "interpretation": (
            "Real CPU model score arithmetic, with B exposed and C constructed; "
            "not independent future test, statistical efficacy or production authority."
        ),
        "open_gates": [
            "independent prospectively held-out evaluator and task C",
            "actual original-owner attestation and NoUpdate/Adopt",
            "complete energy/storage/network/failure costs",
            "full seven-lineage ACT/CTRL/MEM and Core x NDU 2x2"
        ]
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    data = args.archive.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    _required(actual == args.expected_sha256, "source archive SHA-256 changed")
    report = analyze(json.loads(data), actual)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True,
                                  allow_nan=False) + "\n", encoding="utf-8")
    print("HOLD_NO_GO; derived probability audit:", args.out)


if __name__ == "__main__":
    main()
