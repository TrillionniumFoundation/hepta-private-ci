"""Validate label-free media inputs and export inexpensive content baselines."""

import argparse
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import resource
import time

import numpy as np
from PIL import Image

from acquire_cell_audio import verify_audio
from prepare_cell_media import canonical, input_identity, sha
from real_cell_features import sha_file


def media_rows(dataset):
    path = Path(dataset)
    raw = path.read_bytes()
    if len(raw) > 16 * 1024**2:
        raise ValueError("media cohort exceeds metadata budget")
    data = json.loads(raw)
    modality = data["protocol"]["input_modality"]
    neutral = data["protocol"]["neutral_prompt"]
    if modality not in ("image", "audio") or not 1 <= len(data["rows"]) <= 2000:
        raise ValueError("bounded image or audio cohort required")
    result, seen = [], set()
    for row in data["rows"]:
        record = dict(row["record"])
        if set(record) != {"text", modality} or record["text"] != neutral or row["text"] != neutral:
            raise ValueError("only fixed neutral text and one media path enter the encoder")
        relative = Path(record[modality])
        source = path.parent / relative
        if (relative.is_absolute() or ".." in relative.parts or source.is_symlink()
                or not source.resolve().is_relative_to(path.parent.resolve()) or not source.is_file()
                or source.stat().st_size > 1_000_000):
            raise ValueError("invalid or unbounded source media")
        content = source.read_bytes()
        if modality == "audio":
            verified = verify_audio(content, row)
        else:
            if sha(content) != row["media_sha256"] or len(content) != row["media_bytes"]:
                raise ValueError("image bytes differ from selected source")
            with Image.open(source) as picture:
                if picture.mode != "RGB" or picture.size != (32, 32):
                    raise ValueError("unaltered original RGB image required")
                if "pixels:" + sha(np.asarray(picture).tobytes()) != row["group_id"]:
                    raise ValueError("image pixels differ from the published row")
            if row["input_content_sha256"] != input_identity("image", neutral, "sha256:" + sha(content)):
                raise ValueError("image predictor identity differs")
            verified = {"sha256": sha(content), "bytes": len(content)}
        if row["source_id"] in seen:
            raise ValueError("duplicate source ID")
        seen.add(row["source_id"])
        result.append({"source_id": row["source_id"], "source_version": row["source_version"],
                       "input_content_sha256": row["input_content_sha256"], "record": record,
                       "media_sha256": verified["sha256"], "media_bytes": verified["bytes"]})
    return result, modality, sha(raw)


def save_features(root, features, plan, identity, details):
    features = np.asarray(features, dtype=np.float32)
    if features.ndim != 2 or len(features) != len(plan["source_ids"]) or not np.isfinite(features).all():
        raise ValueError("finite native feature matrix and complete source order required")
    with (root / "features.npz").open("xb") as stream:
        np.savez_compressed(stream, features=features)
    report = {"plan": plan, "feature_identity": identity, "feature_shape": list(features.shape),
              "feature_tensor_sha256": sha(features.tobytes()),
              "feature_archive_sha256": sha_file(root / "features.npz"),
              "feature_archive_bytes": (root / "features.npz").stat().st_size,
              "retained_global_bytes": features.nbytes, **details}
    (root / "report.json").write_bytes(canonical(report) + b"\n")
    return report


def cheap_features(dataset, output):
    rows, modality, digest = media_rows(dataset)
    source_root = Path(dataset).parent
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    config = {"image": {"method": "all_raw_RGB_pixels", "scale": "uint8 / 127.5 - 1", "width": 3072},
              "audio": {"method": "MFCC_temporal_mean_std", "sample_rate": 16000, "n_mfcc": 40,
                        "n_fft": 512, "hop_length": 160, "n_mels": 64, "width": 80}}[modality]
    config = {**config, "source_sha256": sha(Path(__file__).read_bytes()),
              "packages": {name: importlib.metadata.version(name) for name in
                           ("numpy", "Pillow", "librosa", "soundfile", "scipy", "soxr")}}
    identity = sha(canonical(config))
    plan = {"schema": "hepta.cheap-media-features.v1", "dataset_sha256": digest,
            "source_ids": [row["source_id"] for row in rows], "input_modality": modality,
            "predictor_fields": ["actual_media_bytes"], "gold_fields_enter_encoder": False,
            "configuration": config, "predictor_sha256": sha(canonical(rows))}
    (root / "plan.json").write_bytes(canonical(plan) + b"\n")
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    features = []
    for row in rows:
        source = source_root / row["record"][modality]
        raw = source.read_bytes()
        if sha(raw) != row["media_sha256"]:
            raise ValueError("media changed before inexpensive extraction")
        if modality == "image":
            with Image.open(io.BytesIO(raw)) as picture:
                vector = (np.asarray(picture, dtype=np.float32).reshape(-1) / 127.5 - 1)
        else:
            import librosa
            signal, rate = librosa.load(io.BytesIO(raw), sr=16000, mono=True)
            if rate != 16000 or len(signal) != 80000:
                raise ValueError("full resampled five-second waveform required")
            mfcc = librosa.feature.mfcc(y=signal, sr=rate, n_mfcc=40, n_fft=512, hop_length=160, n_mels=64)
            vector = np.concatenate((mfcc.mean(axis=1), mfcc.std(axis=1)))
        features.append(vector)
    after_rows, after_modality, after_digest = media_rows(dataset)
    if rows != after_rows or modality != after_modality or digest != after_digest:
        raise ValueError("source cohort changed during inexpensive extraction")
    return save_features(root, features, plan, identity,
        {"encoding": {"wall_ns": time.perf_counter_ns() - started,
                      "cpu_ns": time.process_time_ns() - cpu, "encoder_instances": 0,
                      "physical_model_forward_calls": 0},
         "source_media_bytes": sum(row["media_bytes"] for row in rows),
         "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
         "quality_qualified": False})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output", required=True)
    result = cheap_features(**vars(parser.parse_args()))
    print(json.dumps({key: result[key] for key in ("feature_identity", "feature_shape", "encoding")}))
