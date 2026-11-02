"""Verify retained TRAIN speech-cache provenance and re-execute one real prefix."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
from .strong_audio import LocalSpeech, WEIGHT_SHA, sha, write

HERE = Path(__file__).resolve().parent
REUSED = HERE / "reused_train001"
EMOTIONS = ("ANG", "DIS", "FEA", "HAP", "NEU", "SAD")


def prepare(args):
    paths = [Path(__file__), HERE / "strong_audio.py", REUSED / "encoder.py"]
    paths += [REUSED / name for name in ("CHECKPOINT.json", "SOURCE_FREEZE.json", "SOURCE_PUBLICATION.json")]
    paths += [REUSED / "inputs/train001" / name for name in ("features.npz", "COHORT.json", "IDENTITY.json")]
    write(args.plan, {"schema": "hcsn-v13-train-speech-cache-contract-plan.v1",
        "files_sha256": {str(p.resolve()): sha(p) for p in paths},
        "raw_media": str(args.media.resolve()), "checkpoint": str(args.checkpoint.resolve()),
        "runtime": str(args.runtime.resolve()), "expected_records": 288, "expected_actors": 24,
        "feature_descriptor": "First1536: final-layer hidden mean/std only; exclude116 CTC descriptor coordinates",
        "actual_replay": "Lexicographically first TRAIN clip, original shared-AV-clock accepted 1s prefix",
        "gate": "Raw/cache/row bytes exact; replay descriptor bitwise equal; no quality evaluation"})


def run(args):
    plan = json.loads(args.plan.read_text())
    for path, expected in plan["files_sha256"].items():
        if sha(path) != expected:
            raise ValueError("Frozen source or prepared-input bytes changed: " + path)
    args.out.mkdir(parents=True, exist_ok=False)
    base = REUSED / "inputs/train001"
    identity = json.loads((base / "IDENTITY.json").read_text())
    cohort = json.loads((base / "COHORT.json").read_text())
    records = sorted(cohort["records"], key=lambda r: r["clip"])
    if (identity["split"] != "train" or identity["checkpoint_sha256"] != WEIGHT_SHA
            or identity["manifest_sha256"] != sha(base / "COHORT.json")
            or identity["features_sha256"] != sha(base / "features.npz")):
        raise ValueError("Prepared cache does not bind the exact training input and encoder")
    if len(records) != 288 or len({r["actor"] for r in records}) != 24:
        raise ValueError("Wrong historical training roster")
    details = {r["clip"]: r for r in identity["details"]}
    hashes, raw_bytes = set(), 0
    with np.load(base / "features.npz", allow_pickle=False) as cache:
        features = cache["features"].copy()
        if features.shape != (288, 1652) or features.dtype != np.float32 or not np.isfinite(features).all():
            raise ValueError("Unexpected retained speech cache")
        for index, row in enumerate(records):
            clip = row["clip"]
            fields = clip.split("_")
            if (row["split"] != "train" or fields != [str(row["actor"]), row["sentence"], row["emotion"], "XX"]
                    or row["emotion"] not in EMOTIONS or str(cache["clip"][index]) != clip
                    or str(cache["actor"][index]) != str(row["actor"])):
                raise ValueError("Actor/recording/target metadata mismatch")
            path = Path(plan["raw_media"]) / (clip + ".flv")
            if path.stat().st_size != row["bytes"] or sha(path) != row["sha256"]:
                raise ValueError("Genuine original TRAIN bytes are missing or changed")
            detail = details[clip]
            feature_hash = hashlib.sha256(features[index].tobytes()).hexdigest()
            if (detail["raw_sha256"] != row["sha256"] or detail["feature_sha256"] != feature_hash
                    or detail["ctc_sha256"] != hashlib.sha256(cache["ctc_logits"][index].tobytes()).hexdigest()
                    or feature_hash in hashes):
                raise ValueError("Prepared row hash mismatch or feature-byte alias")
            hashes.add(feature_hash)
            raw_bytes += row["bytes"]
    source = REUSED / "encoder.py"
    if sha(source) != identity["source_sha256"]:
        raise ValueError("Original decoder/descriptor implementation identity differs")
    spec = importlib.util.spec_from_file_location("hcsn_v13_retained_prefix_decoder", source)
    decoder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(decoder)
    first = records[0]
    wave, prefix = decoder.decode_prefix(Path(plan["raw_media"]) / (first["clip"] + ".flv"))
    expected = details[first["clip"]]
    if prefix != expected["prefix"]:
        raise ValueError("Re-executed accepted PCM/source-clock contract differs")
    model = LocalSpeech(Path(plan["checkpoint"]), Path(plan["runtime"]))
    actual = model.infer(wave)
    error = float(np.max(abs(actual[2] - features[0, :1536])))
    if not np.array_equal(actual[2], features[0, :1536]):
        raise ValueError("Actual pretrained descriptor differs from retained frozen cache")
    with (args.out / "ACTUAL_REPLAY.npz").open("xb") as stream:
        np.savez_compressed(stream, waveform=wave, hidden=actual[0], ctc_logits=actual[1], feature=actual[2])
    write(args.out / "RESULT.json", {"schema": "hcsn-v13-train-speech-cache-contract.v1", "status": "PASS",
        "plan_sha256": sha(args.plan), "raw_train_records_verified": len(records), "actors": 24,
        "raw_train_bytes": raw_bytes, "unique_full_feature_byte_hashes": len(hashes),
        "original_cache_sha256": sha(base / "features.npz"), "actual_replayed_clip": first["clip"],
        "actual_prefix": prefix, "actual_pretrained_forwards": 1, "descriptor_bitwise_equal": True,
        "descriptor_max_absolute_difference": error, "output_sha256": sha(args.out / "ACTUAL_REPLAY.npz"),
        "emotions": list(EMOTIONS), "target_contract": "Emotion target comes from checked TRAIN metadata, not existing binary sentence labels. No labels enter encoder inference.",
        "validation_or_test_loaded": False, "quality_evaluated": False,
        "independent_confirmation": False, "strong_audio_reference_qualified": False})
    print(json.dumps({"status": "PASS", "raw_train_records_verified": 288, "actual_pretrained_forwards": 1}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "run"))
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--media", type=Path)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--runtime", type=Path)
    args = parser.parse_args()
    (prepare if args.mode == "prepare" else run)(args)
