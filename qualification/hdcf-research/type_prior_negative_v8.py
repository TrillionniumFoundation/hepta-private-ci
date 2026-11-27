"""Original V6 ModernBERT CellBank: source-bound cheap-baseline negative control.

This is not a pretrained model loader, source-issuer authenticator, NDU solver,
Cell Split activator, artifact signer or native code/effect executor. The historical
32-case TEST was already observed before this retrospective control was proposed.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
import os
import json
import math
from pathlib import Path
import random
import stat
import zipfile

from physical_bank import Denied, digest, validate_bundle
from independent_head_replay import _hash_weights, _replay_fit, _score, audit_head_replay

ORIGINAL_RUN_ID = 38930339541
ORIGINAL_HEAD = "b89a0b4a32eaa92881a79140256079aed0c38fe4"
ORIGINAL_INPUT = "95dc97bd0700165b431d140e77c35500713bc95dd3f6c31b6dabb9e021d26fad"
ORIGINAL_FEATURE_DIGEST = "85a4e29567689b68b532e1774d17e37e140222903eeb8f34f6928a5fbfd37c99"
ORIGINAL_TRIAL = "9e9654d5257f15a66bbb7783473ae27c2c7c684f0ed73c1cc9e544cb035c4267"
ORIGINAL_MODEL = "43138a5545ce4e7996d91735f2330519a8913304d3abf257f6cfdfbe0541283d"
ORIGINAL_SOURCE = "57ec275d8078af65b7731c2a98be812d844a6d6b"
TYPE_DOMAIN = "hepta.hdcf.original-type-partition.v1\0"
PINNED = {
    "features": (
        "3d8d6b7bed80f1f5efb1a17fd1df94208bef4239e5bbbbcd29e63262fb6e025d",
        {"features.json": "d6837a075fd894a2617d8d71f3e6a9a5570ce329958413eb0170149ce2d6f860",
         "feature-receipt.json": "e0697ff64ad4e145fa6db5b3b5be4abd1d9c382e5988f97c12f3cc813bd56566"},
    ),
    "trial": (
        "8bd2d2ba3b2de9f2fe1b99042b471c016d78f90c8305d7d82c91bf1a23138bed",
        {"trial.json": "6d1105462a4bcee79da3b84fbd123cd53bbdc8e9465af2fa0e5be5f35cf10f09"},
    ),
    "targets": (
        "140191b7915923b51a447c9cabc43d6dbba96060ae4dee90716f1fd2539821fb",
        {"targets.json": "e1f5590a888522d2401c7103fdd8ab85c523133a4dc61a4449dd980c3acd8882"},
    ),
    "public": (
        "51e258a7a721a03f402e6606cffb57f52e5ee35a458f5f75218eaafabd9fe698",
        {"public.json": "3322f27832a9fd029b691690ea6c456bf2b969da12f9d650d4184f021c92e01a"},
    ),
}
MAX_ARCHIVE_BYTES = 10_000_000
MAX_MEMBER_BYTES = 4_000_000


def _require(ok: bool, why: str) -> None:
    if not ok:
        raise Denied(why)


def _pairs(items):
    out = {}
    for k, v in items:
        if k in out:
            raise Denied("duplicate json key")
        out[k] = v
    return out


def _reject_constant(_value):
    raise Denied("nonfinite json constant")


def _read_pinned_archive(path: str, kind: str) -> dict[str, object]:
    """No extraction, redirects, symbolic links or mutable unpinned archive trust."""
    expected_outer, members = PINNED[kind]
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as reader:
        _require(stat.S_ISREG(os.fstat(reader.fileno()).st_mode), "not a regular archive descriptor")
        raw = reader.read(MAX_ARCHIVE_BYTES + 1)
    _require(len(raw) <= MAX_ARCHIVE_BYTES and
             hashlib.sha256(raw).hexdigest() == expected_outer, "original archive byte identity mismatch")
    try:
        # Analyze exactly the bytes opened and hashed above, not a mutable path
        # reopened after admission.
        with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
            names = archive.namelist()
            _require(len(names) == len(members) and len(set(names)) == len(names) and
                     set(names) == set(members), "unexpected zip entries")
            result = {}
            for name, expected in members.items():
                entry = archive.getinfo(name)
                mode = (entry.external_attr >> 16) & 0o170000
                _require(mode in (0, stat.S_IFREG) and not entry.is_dir() and
                         0 < entry.file_size <= MAX_MEMBER_BYTES, "unsafe or oversized archive member")
                payload = archive.read(name)
                _require(len(payload) == entry.file_size and
                         hashlib.sha256(payload).hexdigest() == expected, "original artifact member drift")
                result[name] = json.loads(payload.decode("utf-8"),
                                          object_pairs_hook=_pairs, parse_constant=_reject_constant)
            return result
    except (zipfile.BadZipFile, KeyError, UnicodeError, ValueError, OSError) as exc:
        if isinstance(exc, Denied):
            raise
        raise Denied("invalid original archive") from exc


def _type(case_id: str) -> str:
    _require(type(case_id) is str and case_id.isascii() and 1 <= len(case_id) <= 128,
             "invalid case identity")
    return "hash0" if hashlib.sha256((TYPE_DOMAIN + case_id).encode("ascii")).digest()[0] % 2 == 0 else "hash1"


def _original_census(features, public, private, receipt, trial):
    fit, held, d = validate_bundle(features)
    _require(d == 768 and len(fit) == 64 and len(held) == 32 and
             features["types"] == ["hash0", "hash1"] and digest(features) == ORIGINAL_FEATURE_DIGEST,
             "wrong original pretrained feature population")
    _require(type(receipt) is dict and receipt.get("observed_encoder_forward_calls") == 96 and
             receipt.get("input_id") == ORIGINAL_INPUT and
             receipt.get("model_snapshot_sha256") == ORIGINAL_MODEL and
             receipt.get("feature_bundle_digest") == ORIGINAL_FEATURE_DIGEST and
             receipt.get("held_labels_loaded_in_encoder_producer") is False and
             receipt.get("full_encoder_plus_head_tco_verified") is False and
             receipt.get("production_authorized") is False,
             "original Encoder-forward receipt changed")
    _require(type(public) is dict and public.get("input_id") == ORIGINAL_INPUT and
             public.get("source_revision") == ORIGINAL_SOURCE and
             type(public.get("fit")) is list and len(public["fit"]) == 64 and
             type(public.get("heldout")) is list and len(public["heldout"]) == 32 and
             public.get("production_authorized") is False,
             "original public input population drift")
    _require(type(private) is dict and private.get("input_id") == ORIGINAL_INPUT and
             private.get("source_revision") == ORIGINAL_SOURCE and
             private.get("binary_target_definition") == "original_label_mod_2" and
             type(private.get("targets")) is list and len(private["targets"]) == 32 and
             private.get("production_authorized") is False,
             "original blind label population drift")
    _require(type(trial) is dict and trial.get("trial_identity") == ORIGINAL_TRIAL and
             trial.get("bundle_digest") == ORIGINAL_FEATURE_DIGEST and
             trial.get("production_authorized") is False, "original trained trial drift")
    for f, r in zip(features["fit"], public["fit"], strict=True):
        _require(f["id"] == r["id"] and f["family"] == "BANKING77-train-original" and
                 type(r["label"]) is int and 0 <= r["label"] <= 3 and
                 f["target"] == r["label"] % 2 and f["type"] == _type(f["id"]),
                 "original FIT identity, type or target changed")
    for f, r, t in zip(features["held"], public["heldout"], private["targets"], strict=True):
        _require(f["id"] == r["id"] == t["id"] and
                 f["family"] == "BANKING77-test-original" == t["family"] and
                 f["type"] == t["type"] == _type(f["id"]) and
                 type(t["target"]) is int and t["target"] in (0, 1),
                 "original HELD identity, route or value drift")
    return fit, held, d


def audit_pinned_original(*, features_zip: str, trial_zip: str,
                          targets_zip: str, public_zip: str) -> dict:
    features_payload = _read_pinned_archive(features_zip, "features")
    trial = _read_pinned_archive(trial_zip, "trial")["trial.json"]
    private = _read_pinned_archive(targets_zip, "targets")["targets.json"]
    public = _read_pinned_archive(public_zip, "public")["public.json"]
    features = features_payload["features.json"]
    receipt = features_payload["feature-receipt.json"]
    fit, held, d = _original_census(features, public, private, receipt, trial)
    replay = audit_head_replay(features, trial, steps=256, seed=7347, lr=0.05)
    _require(replay["original_prediction_rows_replayed"] == 160 and
             replay["production_authorized"] is False, "original five-arm replay not complete")

    # Training-only, *no fitted tensors*: two simple binary label counts
    # indexed by the original source-ID hash route, Laplace smoothing alpha=1.
    counts: dict[str, Counter] = {t: Counter() for t in features["types"]}
    for _, _, t, _vector, target in fit:
        counts[features["types"][t]][target] += 1
    priors = {t: (counts[t][1] + 1) / (counts[t][0] + counts[t][1] + 2)
              for t in features["types"]}
    _require(all(counts[t][0] and counts[t][1] for t in priors),
             "train-only type frequency lacks class support")
    labels = {r["id"]: r["target"] for r in private["targets"]}
    reference = {r["id"]: r["p1"] for r in trial["predictions"]["split"]}
    # Independently reproduce exact trained Split weights, and validate that
    # the zero-vector ablation itself retains the original type-only routing.
    rng = random.Random(7347)
    initial = [[(rng.random() - 0.5) * .02 for _ in range(d+1)] for _ in range(2)]
    split_weights, touches = _replay_fit(fit, d, {"steps":256,"seed":7347,"lr":.05}, initial, "split")
    _require(_hash_weights(split_weights) == trial["arms"]["split"]["weights_digest"] and
             touches == 196864, "actual Split weights mismatch independent replay")

    prior_hits = split_hits = ablation_hits = prior_agreement = ablation_agreement = 0
    prior_brier = split_brier = prior_logloss = split_logloss = 0.0
    delta_brier_by_intent = [0.0] * 4
    for i, (case_id, _family, typenum, original_feature) in enumerate(held):
        y = labels[case_id]
        route = features["types"][typenum]
        p_prior, p_split = priors[route], reference[case_id]
        p_zero = _score(split_weights, (0.0,) * d, typenum, "split")
        pred_prior, pred_split, pred_zero = (p_prior >= .5), (p_split >= .5), (p_zero >= .5)
        prior_hits += (pred_prior == bool(y))
        split_hits += (pred_split == bool(y))
        ablation_hits += (pred_zero == bool(y))
        prior_agreement += (pred_prior == pred_split)
        ablation_agreement += (pred_zero == pred_split)
        pb = (p_prior - y) ** 2
        sb = (p_split - y) ** 2
        prior_brier += pb
        split_brier += sb
        prior_logloss -= math.log(p_prior if y else 1-p_prior)
        split_logloss -= math.log(p_split if y else 1-p_split)
        # The source slice has 8 held rows per original intent; this is a
        # retrospective visualization, NOT 4 independent publisher families.
        delta_brier_by_intent[i // 8] += (sb - pb)
    n = len(held)
    # The decision/loss comparisons are descriptive on the *already viewed*
    # public 32-case panel. They do not establish generalizable superiority.
    return {
        "schema": "hepta.hdcf.type-prior-original-negative.v1",
        "original_run_id": ORIGINAL_RUN_ID,
        "original_source_head": ORIGINAL_HEAD,
        "archive_sha256": {name: PINNED[name][0] for name in sorted(PINNED)},
        "original_model_snapshot_sha256": ORIGINAL_MODEL,
        "original_input_id": ORIGINAL_INPUT,
        "original_trial_identity": ORIGINAL_TRIAL,
        "real_original_encoder_forwards": receipt["observed_encoder_forward_calls"],
        "original_five_arm_predictions_independently_replayed": replay["original_prediction_rows_replayed"],
        "train_only_route_class_counts": {
            t: {"negative": counts[t][0], "positive": counts[t][1]}
            for t in sorted(priors)},
        "type_only_laplace_alpha": 1,
        "type_only_probabilities": {t: priors[t] for t in sorted(priors)},
        "test_count": n,
        "type_only_correct": prior_hits,
        "split_correct": split_hits,
        "zero_feature_split_correct": ablation_hits,
        "type_only_vs_split_decision_agreements": prior_agreement,
        "zero_feature_vs_original_split_decision_agreements": ablation_agreement,
        "type_only_brier": prior_brier / n,
        "split_brier": split_brier / n,
        "type_only_logloss": prior_logloss / n,
        "split_logloss": split_logloss / n,
        "split_minus_type_only_brier_by_retrospective_intent": [v/8 for v in delta_brier_by_intent],
        "type_only_head_sgd_steps": 0,
        "type_only_required_pretrained_encoder_forwards": 0,
        "split_head_sgd_steps": trial["arms"]["split"]["actual_sgd_steps"],
        "split_head_parameter_touches_estimated": touches,
        "same_publisher_retrospective_only": True,
        "future_window_verified": False,
        "task_transfer_verified": False,
        "original_publisher_signature_verified": False,
        "native_effect_authorized": False,
        "production_authorized": False,
        "disposition": "HOLD_NO_GO",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    for k in ("features", "trial", "targets", "public"):
        ap.add_argument(f"--{k}-zip", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    try:
        result = audit_pinned_original(features_zip=args.features_zip, trial_zip=args.trial_zip,
                                       targets_zip=args.targets_zip, public_zip=args.public_zip)
        out = Path(args.out)
        with out.open("x", encoding="utf-8") as f:
            json.dump(result, f, sort_keys=True, separators=(",", ":"), allow_nan=False)
            f.write("\n")
        print({"original_test": result["test_count"], "type_only": result["type_only_correct"],
               "split": result["split_correct"], "zero_feature_agreements":
               result["zero_feature_vs_original_split_decision_agreements"],
               "disposition": result["disposition"]})
        return 0
    except (Denied, OSError) as exc:
        ap.exit(2, f"DENY_ALL: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
