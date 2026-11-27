"""Research-only paired modality necessity gate; no source/model authority.

Original frozen multimodal model predictions must be sealed before blind labels.
This compares a full observation against a pre-registered modality ablation on
identical case/source families. A positive paired estimate is still NOT evidence
of real pretrained forwards or independent publisher custody.
"""
from __future__ import annotations

from collections import Counter
from math import comb
import hashlib
import json
import math

SCHEMA = "hepta.hdcf.modality-necessity-pair.v9"
RESULT = "hepta.hdcf.modality-necessity-review.v9"
KINDS = frozenset(("image", "audio", "video"))
MAX_CASES = 4096


class Denied(ValueError):
    pass


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise Denied(message)


def _keys(value: object, expected: set[str]) -> None:
    _need(type(value) is dict and set(value) == expected, "missing or unknown fields")


def _hash(value: object) -> str:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         allow_nan=False, ensure_ascii=True).encode("ascii")
    except (ValueError, TypeError) as error:
        raise Denied("uncanonical evidence") from error
    _need(len(raw) <= 2_000_000, "oversized evidence")
    return hashlib.sha256(b"hepta.hdcf.modality-v9\0" + raw).hexdigest()


def _sha(s: object) -> None:
    _need(type(s) is str and len(s) == 64 and
          all(c in "0123456789abcdef" for c in s), "invalid SHA256")


def _id(s: object) -> None:
    _need(type(s) is str and 1 <= len(s) <= 128 and s.isascii() and
          not any(ch.isspace() for ch in s), "invalid identity")


def _prob(x: object) -> None:
    _need(type(x) in (int, float) and math.isfinite(x) and 0.0 <= x <= 1.0,
          "invalid probability")


def _prediction_map(arm: object, expected: dict[str, tuple]) -> dict[str, float]:
    _need(type(arm) is list and len(arm) == len(expected),
          "incomplete arm")
    out: dict[str, float] = {}
    for row in arm:
        _keys(row, {"id", "family", "event_sha256", "p1"})
        case = row["id"]
        _id(case)
        _id(row["family"])
        _sha(row["event_sha256"])
        _prob(row["p1"])
        _need(case in expected and case not in out and
              expected[case] == (row["family"], row["event_sha256"]),
              "arm/source identity mismatch")
        out[case] = float(row["p1"])
    return out


def seal_predictions(payload: object) -> dict:
    """Label-free immutable seal; caller asserts source and model provenance."""
    _keys(payload, {"schema", "modality", "source_digest",
                    "full_model_digest", "ablated_model_digest",
                    "cases", "full", "ablated", "work"})
    _need(payload["schema"] == SCHEMA and payload["modality"] in KINDS,
          "unknown schema/modality")
    for key in ("source_digest", "full_model_digest", "ablated_model_digest"):
        _sha(payload[key])
    cases = payload["cases"]
    _need(type(cases) is list and 16 <= len(cases) <= MAX_CASES,
          "invalid case count")
    expected: dict[str, tuple] = {}
    families = Counter()
    events = set()
    for row in cases:
        _keys(row, {"id", "family", "event_sha256"})
        _id(row["id"]); _id(row["family"]); _sha(row["event_sha256"])
        _need(row["id"] not in expected and row["event_sha256"] not in events,
              "duplicate case or event")
        expected[row["id"]] = (row["family"], row["event_sha256"])
        families[row["family"]] += 1
        events.add(row["event_sha256"])
    _need(len(families) >= 2, "one source family cannot establish diversity")
    full = _prediction_map(payload["full"], expected)
    ablated = _prediction_map(payload["ablated"], expected)
    work = payload["work"]
    _keys(work, {"full_forward_count", "ablated_forward_count",
                 "full_cpu_ns", "ablated_cpu_ns"})
    for value in work.values():
        _need(type(value) is int and value >= 0, "invalid observed work")
    # Counters here are UNSIGNED producer assertions, not host-observed cost.
    _need(work["full_forward_count"] > 0 and work["ablated_forward_count"] > 0,
          "no declared model forwards")
    # Requiring distinct predictions prevents a provably inert modality from
    # receiving a positive claim, but does not imply semantic necessity.
    _need(any(full[k] != ablated[k] for k in expected),
          "no observable ablation effect")
    return {"schema": "hepta.hdcf.modality-seal.v9",
            "seal_digest": _hash(payload), "case_count": len(expected),
            "family_count": len(families), "modality": payload["modality"],
            "sealed_predictions_only": True, "model_provenance_verified": False,
            "source_family_independence_verified": False,
            "host_cost_attested": False, "production_authorized": False}


def _paired_exact(wins: int, losses: int) -> float:
    n = wins + losses
    if n == 0:
        return 1.0
    tail = sum(comb(n, k) for k in range(min(wins, losses) + 1))
    return min(1.0, 2 * tail / (2 ** n))


def score_postseal(payload: object, seal: object, targets: object) -> dict:
    """Independent observer: no labels enter seal_predictions."""
    expected_seal = seal_predictions(payload)
    _need(seal == expected_seal, "predictions altered after seal")
    _keys(targets, {"seal_digest", "targets"})
    _need(targets["seal_digest"] == seal["seal_digest"],
          "blind label set not bound to frozen prediction")
    case_ids = {row["id"] for row in payload["cases"]}
    labels: dict[str, int] = {}
    rows = targets["targets"]
    _need(type(rows) is list and len(rows) == len(case_ids),
          "incomplete original label census")
    for row in rows:
        _keys(row, {"id", "target"})
        _id(row["id"])
        _need(row["id"] in case_ids and row["id"] not in labels and
              type(row["target"]) is int and row["target"] in (0, 1),
              "invalid target")
        labels[row["id"]] = row["target"]
    a = _prediction_map(payload["full"], {
        r["id"]: (r["family"], r["event_sha256"]) for r in payload["cases"]})
    b = _prediction_map(payload["ablated"], {
        r["id"]: (r["family"], r["event_sha256"]) for r in payload["cases"]})
    wins = losses = both = neither = 0
    for k, y in labels.items():
        f, l = (a[k] >= .5) == bool(y), (b[k] >= .5) == bool(y)
        if f and not l:
            wins += 1
        elif l and not f:
            losses += 1
        elif f:
            both += 1
        else:
            neither += 1
    # This statistical test treats cases as exchangeable. Source clusters,
    # publisher duplication and repeated actors invalidate naive inference.
    return {"schema": RESULT, "seal_digest": seal["seal_digest"],
            "n": len(labels), "full_only": wins, "ablation_only": losses,
            "both_correct": both, "both_wrong": neither,
            "full_accuracy": (wins + both) / len(labels),
            "ablation_accuracy": (losses + both) / len(labels),
            "nominal_p": _paired_exact(wins, losses),
            "no_source_independent_efficacy_claim": True,
            "modality_necessary_verified": False,
            "model_provenance_verified": False,
            "physical_cost_verified": False,
            "production_authorized": False,
            "disposition": "HOLD_NO_GO"}
