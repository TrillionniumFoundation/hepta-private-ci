"""Prepare exact historical TRAIN PCM windows for an offline model CI input."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import numpy as np


HERE = Path(__file__).resolve().parent
FRONTEND = HERE.parent / "frontend"
REUSED = FRONTEND / "reused_train001"
COHORT = REUSED / "inputs/train001/COHORT.json"
IDENTITY = REUSED / "inputs/train001/IDENTITY.json"
DECODER = REUSED / "encoder.py"
DECODER_SHA = "77df75fb588936b5bf4bc70e89d93eb752cef113dd4cf513f5a5ab94be33085a"


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def freeze(args):
    if sha(DECODER) != DECODER_SHA:
        raise ValueError("Previously frozen physical-prefix decoder differs")
    paths = [Path(__file__), COHORT, IDENTITY, DECODER]
    write(args.plan, {"schema": "hcsn-v13-emotion-waveform-prepare-plan.v1",
        "files_sha256": {str(p.resolve()): sha(p) for p in paths},
        "raw_media_root": str(args.media.resolve()), "records": 288, "actors": 24,
        "population": "Historical TRAIN only; no new independent confirmation",
        "window": "Exactly retained shared-AV-origin one-second crop, native PCM before resample",
        "sample_rate": 16000, "accepted_samples": 16000, "dtype": "little-endian float32",
        "maximum_npz_bytes": 20000000, "model_forward_executed": False})


def run(args):
    plan = json.loads(args.plan.read_text())
    for name, expected in plan["files_sha256"].items():
        if sha(name) != expected:
            raise ValueError("Frozen source or TRAIN identity changed: " + name)
    prior = json.loads(IDENTITY.read_text())
    if prior["source_sha256"] != DECODER_SHA or prior["manifest_sha256"] != sha(COHORT):
        raise ValueError("Previously executed TRAIN provenance is not bound")
    records = sorted(json.loads(COHORT.read_text())["records"], key=lambda r: r["clip"])
    actors = {str(r["actor"]) for r in records}
    if (len(records) != 288 or len({r["clip"] for r in records}) != 288 or len(actors) != 24
            or any(r["split"] != "train" for r in records)
            or any(sum(str(r["actor"]) == actor for r in records) != 12 for actor in actors)):
        raise ValueError("Exactly the fixed 288 TRAIN recordings /24 actors required")
    expected = {r["clip"]: r for r in prior["details"]}
    if set(expected) != {r["clip"] for r in records}:
        raise ValueError("TRAIN provenance rows differ")
    spec = importlib.util.spec_from_file_location("hcsn_emotion_physical_prefix_decoder", DECODER)
    decoder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(decoder)
    args.out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(COHORT, args.out / "COHORT.json")
    waves, details, raw_bytes = [], [], 0
    for index, row in enumerate(records):
        path = Path(plan["raw_media_root"]) / (row["clip"] + ".flv")
        if path.stat().st_size != row["bytes"] or sha(path) != row["sha256"]:
            raise ValueError("Historical TRAIN source bytes differ: " + row["clip"])
        window, clock = decoder.decode_prefix(path)
        wave = np.asarray(window, dtype="<f4")
        if wave.shape != (16000,) or not np.isfinite(wave).all():
            raise ValueError("Expected exactly one accepted finite physical second")
        wave_hash = hashlib.sha256(wave.tobytes()).hexdigest()
        if clock != expected[row["clip"]]["prefix"] or wave_hash != clock["waveform_sha256"]:
            raise ValueError("Actual source-clock PCM differs from frozen original prefix")
        waves.append(wave)
        raw_bytes += row["bytes"]
        details.append({"clip": row["clip"], "actor": str(row["actor"]), "raw_bytes": row["bytes"],
                        "raw_sha256": row["sha256"], "waveform_sha256": wave_hash, "source_clock": clock})
        if (index + 1) % 24 == 0:
            print(json.dumps({"prepared": index + 1, "population": "historical TRAIN"}), flush=True)
    target = args.out / "WAVEFORMS.npz"
    array = np.asarray(waves, dtype="<f4")
    with target.open("xb") as stream:
        np.savez_compressed(stream, waveforms=array, clip=np.asarray([r["clip"] for r in records]),
                            actor=np.asarray([str(r["actor"]) for r in records]), sample_rate=np.asarray(16000))
    if target.stat().st_size > plan["maximum_npz_bytes"]:
        raise ValueError("Prepared PCM transport exceeds predeclared size cap")
    write(args.out / "PCM_IDENTITY.json", {"schema": "hcsn-v13-emotion-prepared-physical-pcm.v1",
        "plan_sha256": sha(args.plan), "source_sha256": sha(__file__), "decoder_sha256": DECODER_SHA,
        "original_train_identity_sha256": sha(IDENTITY), "original_train_cohort_sha256": sha(COHORT),
        "copied_cohort_sha256": sha(args.out / "COHORT.json"), "waveforms_npz_sha256": sha(target),
        "waveforms_npz_bytes": target.stat().st_size, "array_shape": list(array.shape), "dtype": str(array.dtype),
        "array_sha256": hashlib.sha256(array.tobytes()).hexdigest(), "raw_train_bytes_verified": raw_bytes,
        "records": 288, "actors": 24, "sample_rate": 16000, "details": details,
        "no_full_recording_normalization": True, "model_forward_executed": False,
        "validation_or_test_loaded": False, "independent_confirmation": False,
        "scope": "Offline real decoder preparation; already accepted windows only, not streaming decoder qualification."})
    print(json.dumps({"status": "PASS", "waveform_records": 288,
                      "waveforms_npz_bytes": target.stat().st_size, "waveforms_npz_sha256": sha(target)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "run"))
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--media", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    (freeze if args.mode == "freeze" else run)(args)
