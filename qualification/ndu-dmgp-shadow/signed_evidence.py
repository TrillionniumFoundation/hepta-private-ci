#!/usr/bin/env python3
"""Fail-closed off-line verifier for externally signed NDU-DMGP trial receipts.

This qualified-input *audit* cannot grant runtime, selection, model release, or
production authority. Trust anchors and the frozen objective digest come from
outside the untrusted trial file. OpenSSL (Ed25519) is required.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import statistics
import subprocess
import tempfile
from pathlib import Path
from typing import Mapping

ARMS = frozenset({"A0", "A1", "A2", "A3", "A4", "A5"})
SHARED = frozenset({"objective_digest", "generation", "episode", "arm", "window",
                    "run_id", "trace_digest", "input_digest", "artifact_digest"})
HEX_LEN = 64


class EvidenceRejected(ValueError):
    """Untrusted, malformed, unsupported or insufficient evidence."""


def canonical_json(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise EvidenceRejected("invalid canonical JSON") from exc


def _hex_digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == HEX_LEN and all(
        c in "0123456789abcdef" for c in value)


def _number(value: object, label: str, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvidenceRejected(f"{label}: not numeric")
    try:
        f = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise EvidenceRejected(f"{label}: not representable as finite measurement") from exc
    if not math.isfinite(f) or f < minimum:
        raise EvidenceRejected(f"{label}: non-finite or out of range")
    return f


def _read_key_der(public_pem: Path) -> bytes:
    if not public_pem.is_file():
        raise EvidenceRejected("missing out-of-band pinned public key")
    proc = subprocess.run(
        ["openssl", "pkey", "-pubin", "-in", str(public_pem), "-outform", "DER"],
        capture_output=True, check=False, timeout=10,
    )
    if proc.returncode or not proc.stdout:
        raise EvidenceRejected("invalid pinned public key")
    # DER SPKI distinguishes keys even if their PEM whitespace differs.
    return proc.stdout


def _verify_signature(payload: object, signature_b64: object, public_pem: Path) -> None:
    if not isinstance(signature_b64, str):
        raise EvidenceRejected("missing detached Ed25519 signature")
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise EvidenceRejected("malformed base64 signature") from exc
    if len(signature) != 64:
        raise EvidenceRejected("wrong Ed25519 signature size")
    blob = canonical_json(payload)
    with tempfile.TemporaryDirectory(prefix="hepta-ndu-dmgp-") as directory:
        message = Path(directory) / "message.json"
        sig = Path(directory) / "sig.bin"
        message.write_bytes(blob)
        sig.write_bytes(signature)
        proc = subprocess.run(
            ["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(public_pem),
             "-rawin", "-in", str(message), "-sigfile", str(sig)],
            capture_output=True, check=False, timeout=10,
        )
    if proc.returncode:
        raise EvidenceRejected("untrusted or altered signed evidence")


def verify_envelope(envelope: object, public_pem: Path, expected_role: str) -> dict:
    if not isinstance(envelope, dict) or set(envelope) != {"payload", "signature_b64"}:
        raise EvidenceRejected("invalid signed envelope schema")
    payload = envelope["payload"]
    if not isinstance(payload, dict) or payload.get("role") != expected_role:
        raise EvidenceRejected("unexpected signer role")
    _verify_signature(payload, envelope["signature_b64"], public_pem)
    return payload


def _check_identity(payload: Mapping[str, object], expected_objective: str) -> None:
    if not SHARED.issubset(payload):
        raise EvidenceRejected("incomplete trial identity binding")
    if (payload["objective_digest"] != expected_objective
            or not isinstance(payload["generation"], int)
            or isinstance(payload["generation"], bool)
            or payload["generation"] < 1
            or not all(isinstance(payload[k], str) and payload[k]
                       for k in ("episode", "run_id"))
            or not isinstance(payload["arm"], str) or payload["arm"] not in ARMS
            or not isinstance(payload["window"], str)
            or payload["window"] not in ("train", "future", "retention")
            or not all(_hex_digest(payload[k])
                       for k in ("trace_digest", "input_digest", "artifact_digest"))):
        raise EvidenceRejected("untrusted identity, objective or split")


def verify_pair(entry: object, observer_pem: Path, meter_pem: Path, *,
                expected_objective: str, expected_evaluator_digest: str,
                expected_device_digest: str, training_cutoff: int,
                max_av_skew_ms: float = 120.0) -> dict:
    """Verify separately signed outcome + resource receipt for the same execution.

    A successful pair is *not* an independent claim of physical or perceptual truth:
    key custody and observer/meter quality require separate operator attestation.
    """
    if (not all(_hex_digest(x) for x in
                (expected_objective, expected_evaluator_digest, expected_device_digest))
            or not isinstance(training_cutoff, int)
            or isinstance(training_cutoff, bool) or training_cutoff < 1
            or isinstance(max_av_skew_ms, bool)
            or not isinstance(max_av_skew_ms, (int, float))
            or not math.isfinite(max_av_skew_ms) or max_av_skew_ms < 0):
        raise EvidenceRejected("missing trusted frozen objective/evaluator/device/cutoff")
    if not isinstance(entry, dict) or set(entry) != {"observer", "meter"}:
        raise EvidenceRejected("missing independent observer and host meter")
    obs = verify_envelope(entry["observer"], observer_pem, "independent_observer")
    meter = verify_envelope(entry["meter"], meter_pem, "host_meter")
    for payload in (obs, meter):
        _check_identity(payload, expected_objective)
    if any(obs[k] != meter[k] for k in SHARED):
        raise EvidenceRejected("observer and host meter refer to different executions")
    if obs.get("actor_id") in (None, "", obs.get("observer_id")):
        raise EvidenceRejected("missing or non-independent actor and observer")
    if not isinstance(obs.get("observer_id"), str) or not obs["observer_id"]:
        raise EvidenceRejected("missing observer identity")
    if obs.get("evidence_kind") != "independent_observation" or meter.get("source") != "host_metered":
        raise EvidenceRejected("synthetic or unmetered evidence")
    when = obs.get("observed_at")
    if not isinstance(when, int) or isinstance(when, bool) or when <= 0:
        raise EvidenceRejected("invalid observation time")
    if obs["window"] == "train" and when >= training_cutoff:
        raise EvidenceRejected("training data after frozen cutoff")
    if obs["window"] != "train" and when <= training_cutoff:
        raise EvidenceRejected("heldout evidence before frozen cutoff")
    quality = _number(obs.get("quality"), "independent quality")
    risk = _number(obs.get("risk"), "independent risk")
    if quality > 1 or risk > 1:
        raise EvidenceRejected("unregistered quality/risk units")
    if obs.get("perceptual_evaluator_digest") != expected_evaluator_digest:
        raise EvidenceRejected("unregistered perceptual evaluator revision")
    if obs.get("source_to_output_verified") is not True or obs.get("output_to_source_verified") is not True:
        raise EvidenceRejected("missing bidirectional semantic observation")
    # A boolean verdict alone is not auditable evidence. Require three
    # separately content-addressed and observer-signed perceptual products;
    # even this remains a schema/provenance check, NOT a pixel/audio audit.
    perceptual_fields = (
        "source_to_output_evidence_digest",
        "output_to_source_evidence_digest",
        "cross_modal_claims_digest",
    )
    if not all(_hex_digest(obs.get(field)) and obs[field] != "0" * 64
               for field in perceptual_fields):
        raise EvidenceRejected("missing independently bound perceptual evidence digests")
    if obs[perceptual_fields[0]] == obs[perceptual_fields[1]]:
        raise EvidenceRejected("forward/reverse evidence must be separately identified")
    modalities = obs.get("modalities")
    if (not isinstance(modalities, list) or not modalities
            or not all(isinstance(item, str) for item in modalities)
            or len(set(modalities)) != len(modalities)):
        raise EvidenceRejected("invalid output modality declaration")
    if set(modalities) - {"text", "image", "audio", "video"}:
        raise EvidenceRejected("invalid output modality")
    if {"audio", "video"}.issubset(modalities):
        if _number(obs.get("av_skew_ms"), "AV skew") > max_av_skew_ms:
            raise EvidenceRejected("audio/video temporal inconsistency")
    for label in ("gpu_seconds", "cpu_seconds", "energy_joules", "end_to_end_ms",
                  "controller_ms", "encoder_ms", "decoder_ms", "peak_rss_bytes",
                  "peak_vram_bytes"):
        _number(meter.get(label), label)
    if (meter["end_to_end_ms"] <= 0 or meter["decoder_ms"] <= 0
            or meter["peak_rss_bytes"] <= 0
            or meter["energy_joules"] <= 0
            or meter["end_to_end_ms"] < max(meter["encoder_ms"],
                                          meter["decoder_ms"], meter["controller_ms"])):
        raise EvidenceRejected("missing/inconsistent measured end-to-end decoder work")
    for digest_field in ("device_digest", "encoder_digest", "decoder_digest", "runtime_digest"):
        if not _hex_digest(meter.get(digest_field)):
            raise EvidenceRejected(f"missing host artifact identity: {digest_field}")
    if meter["device_digest"] != expected_device_digest:
        raise EvidenceRejected("unregistered measured device identity")
    return {
        "trace_digest": obs["trace_digest"],
        "episode": obs["episode"], "arm": obs["arm"], "window": obs["window"],
        "run_id": obs["run_id"], "input_digest": obs["input_digest"],
        "artifact_digest": obs["artifact_digest"], "quality": quality, "risk": risk,
        "energy_joules": float(meter["energy_joules"]),
        "gpu_seconds": float(meter["gpu_seconds"]),
        "end_to_end_ms": float(meter["end_to_end_ms"]),
        "controller_ms": float(meter["controller_ms"]),
    }


def audit_trial_file(manifest: object, observer_pem: Path, meter_pem: Path, *,
                     expected_objective: str, expected_evaluator_digest: str,
                     expected_device_digest: str, training_cutoff: int) -> dict:
    """Produce diagnostic numerical evidence; never a production activation token."""
    if not isinstance(manifest, dict) or manifest.get("schema") != "hepta.ndu-dmgp.signed-trials.v1":
        raise EvidenceRejected("unsupported signed trial manifest")
    if hashlib.sha256(_read_key_der(observer_pem)).digest() == hashlib.sha256(_read_key_der(meter_pem)).digest():
        raise EvidenceRejected("observer and meter share signing key")
    trials = manifest.get("trials")
    if not isinstance(trials, list) or not trials or len(trials) > 5000:
        raise EvidenceRejected("missing or unbounded signed trials")
    rows = [verify_pair(item, observer_pem, meter_pem,
                        expected_objective=expected_objective,
                        expected_evaluator_digest=expected_evaluator_digest,
                        expected_device_digest=expected_device_digest,
                        training_cutoff=training_cutoff) for item in trials]
    cohorts: dict[tuple[str, str], dict[str, dict]] = {}
    episode_windows: dict[str, str] = {}
    for r in rows:
        k = (r["window"], r["episode"])
        if episode_windows.setdefault(r["episode"], r["window"]) != r["window"]:
            raise EvidenceRejected("episode leakage across train/future/retention")
        if r["arm"] in cohorts.setdefault(k, {}):
            raise EvidenceRejected("duplicate trial arm in matched cohort")
        cohorts[k][r["arm"]] = r
    # Physical run identity must be globally unique, not merely per-arm or
    # per-episode. Replayed signatures cannot masquerade as fresh work.
    if len({row["run_id"] for row in rows}) != len(rows):
        raise EvidenceRejected("duplicate physical runs across signed trial rows")
    if any(set(v) != ARMS or len({a["input_digest"] for a in v.values()}) != 1
           or len({a["trace_digest"] for a in v.values()}) != len(ARMS)
           or len({a["run_id"] for a in v.values()}) != len(ARMS)
           for v in cohorts.values()):
        raise EvidenceRejected("missing arm or unmatched inputs/physical runs across A0-A5")
    # Distinct episode labels do not establish independence if they replay the
    # same input. Reject cross-episode reuse across all declared splits.
    episode_input_pairs = [(episode, next(iter(arms.values()))["input_digest"])
                           for (_, episode), arms in cohorts.items()]
    if len({source for _, source in episode_input_pairs}) != len(episode_input_pairs):
        raise EvidenceRejected("reused source input across independent trial episodes")
    n = {window: sum(1 for w, _ in cohorts if w == window)
         for window in ("train", "future", "retention")}
    reasons = []
    for window, minimum in (("train", 24), ("future", 24), ("retention", 24)):
        if n[window] < minimum:
            reasons.append(f"insufficient independent {window} matched episodes")
    # Pairwise future deltas preserve each input; no comparisons against shuffled episodes.
    future = [v for (w, _), v in sorted(cohorts.items()) if w == "future"]
    superiority = {}
    if len(future) >= 32:
        comparisons = len(ARMS) - 1
        alpha = 0.05  # Frozen familywise alpha; no data-dependent selection.
        for baseline in sorted(ARMS - {"A5"}):
            differences = [v["A5"]["quality"] - v[baseline]["quality"] for v in future]
            estimate = statistics.fmean(differences)
            # Differences in [-1,1]. Union-bounded one-sided Hoeffding LCB
            # corrects for five simultaneous comparisons; valid only for
            # independently sampled episode CLUSTERS, not merely distinct IDs.
            radius = math.sqrt(2.0 * math.log(comparisons / alpha) / len(differences))
            bound = estimate - radius
            superiority[baseline] = {
                "quality_delta_mean": estimate,
                "quality_delta_familywise_lcb95": bound,
                "method": "bonferroni-hoeffding",
                "independent_clusters_verified": False,
            }
            if bound <= 0:
                reasons.append(f"A5 quality does not exceed {baseline} on heldout future")
    else:
        reasons.append("insufficient 32-cluster future support for simultaneous bounds")
    # Quality alone does not prove NDU or cost improvement: the full external
    # objective, costs, covariance support, stability, closure and independent
    # final-use decisions are still required.
    return {
        "schema": "hepta.ndu-dmgp.signed-audit.v1", "verified_signed_pairs": len(rows),
        "matched_episode_counts": n, "paired_future_quality": superiority,
        "diagnostic_reasons": sorted(set(reasons)),
        "key_role_separation_verified": True,
        "real_world_truth_independently_certified": False,
        "conditional_covariance_identified": False,
        "longitudinal_learning_certified": False,
        "causal_cell_credit_certified": False,
        "production_blockers_closed": False,
        "no_promotion_authority": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--observer-public-key", required=True, type=Path)
    parser.add_argument("--meter-public-key", required=True, type=Path)
    parser.add_argument("--expected-objective-digest", required=True)
    parser.add_argument("--expected-evaluator-digest", required=True)
    parser.add_argument("--expected-device-digest", required=True)
    parser.add_argument("--training-cutoff", required=True, type=int)
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        report = audit_trial_file(manifest, args.observer_public_key, args.meter_public_key,
                                  expected_objective=args.expected_objective_digest,
                                  expected_evaluator_digest=args.expected_evaluator_digest,
                                  expected_device_digest=args.expected_device_digest,
                                  training_cutoff=args.training_cutoff)
    except (EvidenceRejected, OSError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "rejected", "reason": str(exc),
                          "production_blockers_closed": False,
                          "no_promotion_authority": True}))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
