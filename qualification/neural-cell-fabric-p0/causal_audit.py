"""P0.4 historical causal-lesion audit: genuine pretrained features, NO NEW encoder.

Producer only opens fixed original feature and trial archives (no held labels).
Independent postseal reviewer opens the historical publisher/target archives.
Offline scalar training reconstructs original 5-arm float64 parameters, validates
all 160 held predictions, then actually evaluates the trained Split on zero
vectors. Every operation is research-only, DENY_ALL, and retrospectively selected.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import io
import json
import math
import os
from pathlib import Path
import random
import stat
import struct
from zipfile import ZipFile, BadZipFile

from fabric import Denied, sha
from original_replay import ARCHIVES, _no_duplicate_pairs, _no_nonfinite
from science_gate import exact_mcnemar

SOURCE = "95dc97bd0700165b431d140e77c35500713bc95dd3f6c31b6dabb9e021d26fad"
BUNDLE = "85a4e29567689b68b532e1774d17e37e140222903eeb8f34f6928a5fbfd37c99"
TRIAL = "9e9654d5257f15a66bbb7783473ae27c2c7c684f0ed73c1cc9e544cb035c4267"
WEIGHT_DOMAIN = b"hepta.hdcf.actual-head-weights.v1\0"
TYPE_DOMAIN = b"hepta.hdcf.original-type-partition.v1\x00"
MODES = ("frozen", "shared_dense", "shared_one_touch", "split", "swapped")
INNER_SHA256 = {
    "features.json": "d6837a075fd894a2617d8d71f3e6a9a5570ce329958413eb0170149ce2d6f860",
    "feature-receipt.json": "e0697ff64ad4e145fa6db5b3b5be4abd1d9c382e5988f97c12f3cc813bd56566",
    "trial.json": "6d1105462a4bcee79da3b84fbd123cd53bbdc8e9465af2fa0e5be5f35cf10f09",
    "targets.json": "e1f5590a888522d2401c7103fdd8ab85c523133a4dc61a4449dd980c3acd8882",
    "public.json": "3322f27832a9fd029b691690ea6c456bf2b969da12f9d650d4184f021c92e01a",
}


def _load_archive(root: Path, name: str) -> dict:
    """Hash opened descriptor and each member; do not extract archives or follow symlinks."""
    if not root.is_dir() or root.is_symlink() or name not in ARCHIVES:
        raise Denied("unsupported archive root or identity")
    outer, member = ARCHIVES[name]
    try:
        fd = os.open(root / name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as fp:
            if not stat.S_ISREG(os.fstat(fp.fileno()).st_mode):
                raise Denied("archive not a regular file")
            raw = fp.read(2_000_001)
        if len(raw) > 2_000_000 or sha(raw) != outer:
            raise Denied("original archive bytes changed")
        with ZipFile(io.BytesIO(raw)) as z:
            names = z.namelist()
            expected = {member, "feature-receipt.json"} if name == "hdcf-original-features.zip" else {member}
            if len(names) != len(expected) or set(names) != expected:
                raise Denied("unexpected original ZIP member")
            out = {}
            for key in names:
                entry = z.getinfo(key)
                if entry.is_dir() or not 0 < entry.file_size <= 2_000_000:
                    raise Denied("unsupported original ZIP member")
                payload = z.read(key)
                if len(payload) != entry.file_size or sha(payload) != INNER_SHA256[key]:
                    raise Denied("original ZIP member digest mismatch")
                out[key] = json.loads(payload, object_pairs_hook=_no_duplicate_pairs,
                                      parse_constant=_no_nonfinite)
            return out
    except (OSError, BadZipFile, KeyError, ValueError) as error:
        if isinstance(error, Denied):
            raise
        raise Denied("invalid original archive") from error


def type_from_case_id(case_id: str) -> str:
    if type(case_id) is not str or not 1 <= len(case_id) <= 128 or not case_id.isascii():
        raise Denied("noncanonical original case identity")
    bit = hashlib.sha256(TYPE_DOMAIN + case_id.encode("ascii")).digest()[0] % 2
    return "hash0" if bit == 0 else "hash1"


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))


def _predict(weights: list[list[float]], vector: tuple[float, ...], subtype: int, mode: str) -> float:
    if mode in ("shared_dense", "shared_one_touch"):
        w = [(x + y) / 2 for x, y in zip(weights[0], weights[1], strict=True)]
    else:
        w = weights[subtype ^ int(mode == "swapped")]
    z = sum(a * b for a, b in zip(w[:-1], vector, strict=True)) + w[-1]
    return _sigmoid(z)


def _weight_digest(weights: list[list[float]]) -> str:
    packed = b"".join(struct.pack("<d", p) for row in weights for p in row)
    return sha(WEIGHT_DOMAIN + packed)


def _fit(fit: list, dimension: int, initial: list[list[float]], mode: str) -> tuple[list[list[float]], int]:
    weights = [row.copy() for row in initial]
    rng = random.Random(7348)
    indexes = list(range(len(fit)))
    schedule: list[int] = []
    while len(schedule) < 256:
        rng.shuffle(indexes)
        schedule.extend(indexes)
    touches = 0
    for step, index in enumerate(schedule[:256]):
        item = fit[index]
        subtype = item["type_index"]
        vector = item["vector"]
        delta = .05 * (_predict(weights, vector, subtype, mode) - item["target"])
        if mode == "shared_dense":
            targets = ((0, .5), (1, .5))
        elif mode == "shared_one_touch":
            targets = ((step % 2, 1.0),)
        else:
            targets = ((subtype, 1.0),)
        for slot, factor in targets:
            for dim, value in enumerate(vector):
                weights[slot][dim] -= delta * factor * value
            weights[slot][-1] -= delta * factor
            touches += dimension + 1
    return weights, touches


def _bound_vector(value: object, d: int) -> tuple[float, ...]:
    if type(value) is not list or len(value) != d:
        raise Denied("feature dimension")
    if any(type(p) not in (int, float) or not math.isfinite(p) or abs(p) > 8 for p in value):
        raise Denied("invalid original feature scalar")
    return tuple(float(p) for p in value)


def produce_unlabeled(root: Path) -> dict:
    """Prelabel producer: only 2 source archives, no targets, no publisher held gold."""
    features_raw = _load_archive(root, "hdcf-original-features.zip")
    trial_raw = _load_archive(root, "hdcf-original-head-trial.zip")
    f, t = features_raw["features.json"], trial_raw["trial.json"]
    receipt = features_raw["feature-receipt.json"]
    if (f.get("dimension") != 768 or f.get("types") != ["hash0", "hash1"]
            or len(f.get("fit", [])) != 64 or len(f.get("held", [])) != 32
            or t.get("bundle_digest") != BUNDLE or t.get("trial_identity") != TRIAL
            or t.get("encoder_forward_count") != 0 or set(t.get("arms", {})) != set(MODES)
            or set(t.get("predictions", {})) != set(MODES)
            or receipt.get("observed_encoder_forward_calls") != 96
            or receipt.get("input_id") != SOURCE
            or receipt.get("feature_bundle_digest") != BUNDLE):
        raise Denied("prelabel original lineage or census mismatch")
    fit, held, seen = [], [], set()
    for segment, expected_len in (("fit", 64), ("held", 32)):
        for raw in f[segment]:
            if type(raw.get("id")) is not str or raw["id"] in seen:
                raise Denied("duplicate source case")
            seen.add(raw["id"])
            if raw.get("type") != type_from_case_id(raw["id"]):
                raise Denied("route not independently reproduced")
            subtype = f["types"].index(raw["type"])
            vector = _bound_vector(raw.get("vector"), 768)
            entry = {"id": raw["id"], "type": raw["type"], "type_index": subtype,
                     "family": raw.get("family"), "vector": vector}
            if segment == "fit":
                if type(raw.get("target")) is not int or raw["target"] not in (0, 1):
                    raise Denied("invalid FIT label")
                entry["target"] = raw["target"]
                fit.append(entry)
            else:
                held.append(entry)
    if len(fit) != 64 or len(held) != 32:
        raise Denied("invalid original cohort")
    rng = random.Random(7347)
    initial = [[(rng.random() - .5) * .02 for _ in range(769)] for _ in range(2)]
    trained: dict[str, list[list[float]]] = {}
    predictions: dict[str, list[dict]] = {}
    weight_hashes: dict[str, str] = {}
    touches: dict[str, int] = {}
    for mode in MODES:
        if mode == "frozen":
            weights, touched = initial, 0
        elif mode == "swapped":
            weights, touched = trained["split"], 0
        else:
            weights, touched = _fit(fit, 768, initial, mode)
        if _weight_digest(weights) != t["arms"][mode]["weights_digest"]:
            raise Denied("actual original SGD weight hash mismatch")
        if t["arms"][mode]["estimated_parameter_touches"] != touched:
            raise Denied("unpaid original training work")
        if t["arms"][mode]["actual_sgd_steps"] != (0 if mode in ("frozen", "swapped") else 256):
            raise Denied("original optimizer schedule drift")
        trained[mode] = weights
        weight_hashes[mode] = _weight_digest(weights)
        touches[mode] = touched
        rows = []
        if len(t["predictions"][mode]) != 32:
            raise Denied("original prediction census")
        for original, arch in zip(held, t["predictions"][mode], strict=True):
            if (arch.get("id") != original["id"] or arch.get("type") != original["type"]
                    or arch.get("family") != original["family"]):
                raise Denied("prediction row lineage")
            score = _predict(weights, original["vector"], original["type_index"], mode)
            if type(arch.get("p1")) not in (float, int) or not math.isfinite(arch["p1"]) or abs(score - arch["p1"]) > 1e-13:
                raise Denied("original fitted-model prediction mismatch")
            rows.append({"id": original["id"], "type": original["type"], "p": score})
        predictions[mode] = rows
    # Genuine intervention on newly reconstructed trained weights, never replayed
    # model probabilities with the feature-vector identity falsely relabeled.
    zero = []
    for original in held:
        z = _predict(trained["split"], (0.,) * 768, original["type_index"], "split")
        zero.append({"id": original["id"], "type": original["type"], "p": z})
    counts = {name: Counter() for name in f["types"]}
    for row in fit:
        counts[row["type"]][row["target"]] += 1
    prior = {typ: (count[1] + 1) / (count[0] + count[1] + 2)
             for typ, count in counts.items()}
    predictions["zero_features"] = zero
    predictions["type_prior"] = [{"id": row["id"], "type": row["type"], "p": prior[row["type"]]} for row in held]
    sealed = {
        "schema": "hepta.cell-fabric.p04.prelabel.v1",
        "original_run": 38930339541,
        "feature_archive_sha256": ARCHIVES["hdcf-original-features.zip"][0],
        "trial_archive_sha256": ARCHIVES["hdcf-original-head-trial.zip"][0],
        "input_id": SOURCE,
        "trial_id": TRIAL,
        "original_pretrained_forwards_from_receipt": 96,
        "new_pretrained_forwards": 0,
        "original_predictions_independently_reconstructed": 160,
        "training_parameter_touches": touches,
        "recomputed_weight_hashes": weight_hashes,
        "train_label_type_counts": {k: {"neg": v[0], "pos": v[1]} for k, v in counts.items()},
        "predictions": predictions,
        "authority": "DENY_ALL",
    }
    return sealed


def canonical_bytes(data: object) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _write_private_new(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink() or path.parent.is_symlink() or not path.parent.is_dir():
        raise Denied("output not create-only private directory")
    if stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        raise Denied("output directory must be 0700")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as writer:
        writer.write(payload)
        writer.flush()
        os.fsync(writer.fileno())
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _read_sealed(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise Denied("invalid prelabel seal path")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as reader:
        if not stat.S_ISREG(os.fstat(reader.fileno()).st_mode):
            raise Denied("not regular seal")
        data = reader.read(300_000)
    if len(data) >= 300_000:
        raise Denied("oversized prelabel evidence")
    obj = json.loads(data, object_pairs_hook=_no_duplicate_pairs, parse_constant=_no_nonfinite)
    if canonical_bytes(obj) != data:
        raise Denied("noncanonical prelabel evidence")
    return obj


def review_late_labels(prelabel: dict, root: Path) -> dict:
    """Late postseal label reader; never trains, reports sanitized aggregates."""
    public = _load_archive(root, "hdcf-original-public.zip")["public.json"]
    held = _load_archive(root, "hdcf-original-targets.zip")["targets.json"]
    if (prelabel.get("schema") != "hepta.cell-fabric.p04.prelabel.v1"
            or prelabel.get("input_id") != SOURCE or prelabel.get("trial_id") != TRIAL
            or prelabel.get("new_pretrained_forwards") != 0
            or prelabel.get("original_predictions_independently_reconstructed") != 160
            or prelabel.get("authority") != "DENY_ALL"
            or public.get("input_id") != SOURCE or held.get("input_id") != SOURCE
            or len(public.get("heldout", [])) != 32 or len(held.get("targets", [])) != 32
            or len(prelabel.get("predictions", {})) != 7):
        raise Denied("postseal original lineage mismatch")
    # Frozen original publisher IDs/routes (public corpus and target rows), not
    # fresh independent publisher issuances or future windows.
    truth = []
    for a, b in zip(public["heldout"], held["targets"], strict=True):
        if (a.get("id") != b.get("id") or type(b.get("target")) is not int
                or b["target"] not in (0, 1) or b.get("type") != type_from_case_id(a["id"])):
            raise Denied("original publisher case/label mismatch")
        truth.append(b["target"])
    names = set(MODES) | {"zero_features", "type_prior"}
    if set(prelabel["predictions"]) != names:
        raise Denied("postseal missing arm")
    metrics = {}
    decisions = {}
    losses = {}
    for name, rows in prelabel["predictions"].items():
        if type(rows) is not list or len(rows) != 32:
            raise Denied("missing prelabel case")
        prob = []
        for p, ref in zip(rows, held["targets"], strict=True):
            if (type(p) is not dict or set(p) != {"id", "type", "p"}
                    or p["id"] != ref["id"] or p["type"] != ref["type"]
                    or type(p["p"]) not in (int, float) or not math.isfinite(p["p"])
                    or not 0 < p["p"] < 1):
                raise Denied("prelabel predictions corrupted or remapped")
            prob.append(p["p"])
        decisions[name] = [int(p >= .5) for p in prob]
        losses[name] = [(p - label) ** 2 for p, label in zip(prob, truth)]
        metrics[name] = {
            "correct": sum(a == b for a, b in zip(decisions[name], truth)),
            "brier": math.fsum(losses[name]) / len(truth),
            "nll": -math.fsum(math.log(p if label else 1 - p) for p, label in zip(prob, truth)) / 32,
        }
    split = decisions["split"]
    base = decisions["shared_one_touch"]
    wins = sum(s == y and b != y for s, b, y in zip(split, base, truth))
    losses_count = sum(s != y and b == y for s, b, y in zip(split, base, truth))
    delta_brier = [s - p for s, p in zip(losses["split"], losses["type_prior"], strict=True)]
    # Label-exposed paired bootstrap is descriptive ONLY, not future transfer.
    rng = random.Random(2615)
    means = sorted(math.fsum(delta_brier[rng.randrange(32)] for _ in range(32)) / 32
                   for _ in range(4000))
    return {
        "schema": "hepta.cell-fabric.p04.original-historical-lesion-review.v1",
        "original_run": 38930339541,
        "feature_pretraining_reperformed": False,
        "prelabel_original_160_outputs_independently_reproduced": True,
        "zero_feature_model_forward_reexecuted_on_reconstructed_head": True,
        "prelabel_seal_sha256": sha(canonical_bytes(prelabel)),
        "archive_sha256": {name: data[0] for name, data in ARCHIVES.items()},
        "held_cases": 32,
        "metrics": metrics,
        "split_vs_prior_decision_agreement": sum(a == b for a, b in zip(split, decisions["type_prior"])),
        "split_vs_zero_feature_decision_agreement": sum(a == b for a, b in zip(split, decisions["zero_features"])),
        "split_vs_shared_equal_touch_wins": wins,
        "split_vs_shared_equal_touch_losses": losses_count,
        "split_vs_shared_equal_touch_p_exact": exact_mcnemar(wins, losses_count),
        "posthoc_paired_brier_split_minus_prior_mean": math.fsum(delta_brier) / 32,
        "posthoc_row_bootstrap_brier_95pct": [means[99], means[3899]],
        "bootstrap_not_valid_for_prospective_or_correlated_source_inference": True,
        "future_source_independence_verified": False,
        "full_service_cost_verified": False,
        "learned_cell_gain_verified": False,
        "ndu_task_gain_verified": False,
        "native_os_effect_authorized": False,
        "authority": "DENY_ALL",
        "disposition": "HOLD_NO_GO",
    }


def main() -> None:
    p = argparse.ArgumentParser()
    commands = p.add_subparsers(dest="phase", required=True)
    for name in ("prelabel", "review"):
        parser = commands.add_parser(name)
        parser.add_argument("--archive-dir", required=True, type=Path)
        parser.add_argument("--output", required=True, type=Path)
        if name == "review":
            parser.add_argument("--prelabel", required=True, type=Path)
    args = p.parse_args()
    if args.phase == "prelabel":
        report = produce_unlabeled(args.archive_dir)
    else:
        pre = _read_sealed(args.prelabel)
        # Verify the producer material independently before opening gold.
        genuine = produce_unlabeled(args.archive_dir)
        if canonical_bytes(pre) != canonical_bytes(genuine):
            raise Denied("prelabel producer altered or source not reproduced")
        report = review_late_labels(pre, args.archive_dir)
    raw = canonical_bytes(report)
    _write_private_new(args.output, raw)
    print(json.dumps({"phase": args.phase, "sha256": sha(raw),
                      "authority": "DENY_ALL", "disposition": "HOLD_NO_GO"}, sort_keys=True))


if __name__ == "__main__":
    main()
