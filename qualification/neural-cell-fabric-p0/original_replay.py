"""Offline historical original ModernBERT 5-arm + cheap-prior independent recount.

Only consumes exact SHA256-pinned GitHub Actions ZIPs from original run 38930339541.
No pretrained model forward is executed here; no independent publisher signature.
Results are retrospective and always HOLD_NO_GO, never a new model result.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
from zipfile import ZipFile

from fabric import Denied, sha
from science_gate import exact_mcnemar

ARCHIVES = {
    "hdcf-original-features.zip": ("3d8d6b7bed80f1f5efb1a17fd1df94208bef4239e5bbbbcd29e63262fb6e025d", "features.json"),
    "hdcf-original-head-trial.zip": ("8bd2d2ba3b2de9f2fe1b99042b471c016d78f90c8305d7d82c91bf1a23138bed", "trial.json"),
    "hdcf-original-targets.zip": ("140191b7915923b51a447c9cabc43d6dbba96060ae4dee90716f1fd2539821fb", "targets.json"),
    "hdcf-original-public.zip": ("51e258a7a721a03f402e6606cffb57f52e5ee35a458f5f75218eaafabd9fe698", "public.json"),
}


def _no_duplicate_pairs(items):
    value = {}
    for key, datum in items:
        if key in value:
            raise Denied("duplicate JSON object key")
        value[key] = datum
    return value


def _no_nonfinite(x):
    raise Denied(f"nonfinite JSON constant {x}")


def read_original(directory: Path) -> dict[str, dict]:
    if not directory.is_dir() or directory.is_symlink():
        raise Denied("archive root missing/symlink")
    result = {}
    for name, (expected, member) in ARCHIVES.items():
        path = directory / name
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 2_000_000:
            raise Denied("archive absent or oversize")
        if sha(path.read_bytes()) != expected:
            raise Denied("original external ZIP SHA256 mismatch")
        with ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 4 or len({x.filename for x in entries}) != len(entries):
                raise Denied("archive member count/identity")
            if member not in {x.filename for x in entries}:
                raise Denied("missing original member")
            info = archive.getinfo(member)
            if info.file_size > 2_000_000 or info.is_dir():
                raise Denied("original member unsupported")
            payload = archive.read(member)
            if len(payload) != info.file_size:
                raise Denied("truncated original member")
            result[name] = json.loads(payload, object_pairs_hook=_no_duplicate_pairs,
                                      parse_constant=_no_nonfinite)
            if name == "hdcf-original-features.zip":
                r = archive.read("feature-receipt.json")
                result["feature_receipt"] = json.loads(r, object_pairs_hook=_no_duplicate_pairs,
                                                      parse_constant=_no_nonfinite)
    return result


def recount(source: dict[str, dict]) -> dict[str, object]:
    features = source["hdcf-original-features.zip"]
    trial = source["hdcf-original-head-trial.zip"]
    labels = source["hdcf-original-targets.zip"]
    public = source["hdcf-original-public.zip"]
    if (len(features["fit"]) != 64 or len(features["held"]) != 32 or
            len(labels["targets"]) != 32 or len(public["fit"]) != 64 or
            len(public["heldout"]) != 32 or features["dimension"] != 768):
        raise Denied("original cohort cardinality")
    if (trial["encoder_forward_count"] != 0 or
            source["feature_receipt"]["observed_encoder_forward_calls"] != 96 or
            set(trial["predictions"]) !=
            {"frozen", "shared_dense", "shared_one_touch", "split", "swapped"}):
        raise Denied("original trial structure")
    if (public["input_id"] != labels["input_id"] or
            features["producer"]["source_sha256"] != public["stage_digest"]):
        raise Denied("original input identity drift")
    for cohort in ("fit", "held"):
        left = features[cohort]
        right = public["fit" if cohort == "fit" else "heldout"]
        if [x["id"] for x in left] != [x["id"] for x in right]:
            raise Denied("original source case/order drift")
    held = features["held"]
    target = labels["targets"]
    if [(x["id"], x["type"]) for x in held] != [(x["id"], x["type"]) for x in target]:
        raise Denied("blind source/route mismatch")
    train_counts = {typ: Counter() for typ in features["types"]}
    for row in features["fit"]:
        if row["target"] not in (0, 1) or row["type"] not in train_counts:
            raise Denied("noncanonical fit labels or route")
        train_counts[row["type"]][row["target"]] += 1
    prior = {typ: (counts[1] + 1) / (counts[0] + counts[1] + 2)
             for typ, counts in train_counts.items()}
    if any(not 0 < p < 1 for p in prior.values()):
        raise Denied("bad Laplace posterior")
    truth = [int(x["target"]) for x in target]
    if any(x["target"] not in (0, 1) for x in target):
        raise Denied("bad original targets")
    baseline_names = tuple(trial["predictions"])
    predictions = {}
    for name in baseline_names:
        rows = trial["predictions"][name]
        if len(rows) != len(held) or [(x["id"], x["type"]) for x in rows] != [(x["id"], x["type"]) for x in held]:
            raise Denied("trial output changed case/route")
        probs = [x["p1"] for x in rows]
        if any(not isinstance(x, (int, float)) or isinstance(x, bool) or not math.isfinite(x) or not 0 <= x <= 1 for x in probs):
            raise Denied("invalid original probability")
        predictions[name] = probs
    predictions["type_prior_zero_sgd"] = [prior[row["type"]] for row in held]
    metrics = {}
    decisions = {}
    for name, probs in predictions.items():
        dec = [int(p >= .5) for p in probs]
        decisions[name] = dec
        metrics[name] = {"correct": sum(a == b for a, b in zip(dec, truth)),
                         "brier": sum((p - b)**2 for p, b in zip(probs, truth)) / len(truth)}
    split = decisions["split"]
    shared = decisions["shared_one_touch"]
    wins = sum(a == y and b != y for a, b, y in zip(split, shared, truth))
    losses = sum(a != y and b == y for a, b, y in zip(split, shared, truth))
    return {
        "kind": "historical_original_pretrained_archived_prediction_recount",
        "original_run": 38930339541,
        "archive_sha256": {name: x[0] for name, x in ARCHIVES.items()},
        "source_identity": public["input_id"],
        "physical_encoder_forward_count_in_original_receipt": source["feature_receipt"]["observed_encoder_forward_calls"],
        "trial_reused_cached_features_without_new_forwards": trial["encoder_forward_count"] == 0,
        "replayed_original_prediction_rows": sum(len(trial["predictions"][name]) for name in baseline_names),
        "fit_count": len(features["fit"]), "held_count": len(truth),
        "train_only_type_counts": {key: {"neg": counts[0], "pos": counts[1]} for key, counts in train_counts.items()},
        "type_prior_probabilities": prior,
        "metrics": metrics,
        "split_vs_prior_agreement": sum(a == b for a, b in zip(split, decisions["type_prior_zero_sgd"])),
        "split_vs_shared_one_touch_wins": wins,
        "split_vs_shared_one_touch_losses": losses,
        "split_vs_shared_one_touch_mcnemar_exact_p": exact_mcnemar(wins, losses),
        "zero_feature_original_predictions_reexecuted": False,
        "new_pretrained_forward_executed": False,
        "independent_publisher_signature_verified": False,
        "source_independent_future_gain_verified": False,
        "system2_or_multimodal_ability_verified": False,
        "model_selection_authorized": False,
        "native_effect_authorized": False,
        "authority": "DENY_ALL", "disposition": "HOLD_NO_GO",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive-dir", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise Denied("create-only report required")
    report = recount(read_original(args.archive_dir))
    raw = (json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    import os
    fd = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(raw)
        out.flush()
        os.fsync(out.fileno())
    print(json.dumps({"report_sha256": sha(raw), "cases": report["held_count"],
                      "disposition": report["disposition"]}, sort_keys=True))


if __name__ == "__main__":
    main()
