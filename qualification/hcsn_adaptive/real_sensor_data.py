"""Causal, timestamp-preserving windows from UCI Room Occupancy Estimation.

This is a five-sensor-modality nowcasting benchmark, not an audio waveform,
image, text, or foundation-model benchmark. The published CO2 slope is omitted
because its window alignment is unspecified. The query occurs when the next
observation arrives, before its sensors/label are revealed. Its timestamp is
available to EVERY model as a query horizon; its sensor values are never inputs.
All durations are actual source seconds, not a forecast of unknown arrival time.
"""

import argparse
import csv
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path

import numpy as np


SOURCE_SHA256 = "c090ee5c94b61762bfec9d22767864490b51030f98cca030f02822468db25d9c"
SOURCE_URL = "https://archive.ics.uci.edu/static/public/864/room%2Boccupancy%2Bestimation.zip"
MODALITIES = {
    "temperature": [f"S{i}_Temp" for i in range(1, 5)],
    "light": [f"S{i}_Light" for i in range(1, 5)],
    "sound_amplitude": [f"S{i}_Sound" for i in range(1, 5)],
    "co2": ["S5_CO2"],
    "pir": ["S6_PIR", "S7_PIR"],
}
FEATURES = tuple(name for group in MODALITIES.values() for name in group)


def read_rows(raw, *, expected_sha256=SOURCE_SHA256):
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("source CSV hash differs from the declared dataset")
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    required = {"Date", "Time", "Room_Occupancy_Count", *FEATURES}
    if not rows or not required.issubset(rows[0]):
        raise ValueError("missing source columns")
    epoch = datetime(1970, 1, 1)
    stamps = np.array([int((datetime.strptime(row["Date"]+" "+row["Time"],
                         "%Y/%m/%d %H:%M:%S")-epoch).total_seconds()) for row in rows], dtype=np.int64)
    if np.any(np.diff(stamps) <= 0):
        raise ValueError("source rows must have strictly increasing timestamps")
    x = np.asarray([[float(row[name]) for name in FEATURES] for row in rows], dtype=np.float64)
    labels = np.asarray([int(row["Room_Occupancy_Count"]) for row in rows], dtype=np.int64)
    if not np.isfinite(x).all() or np.any((labels < 0) | (labels > 3)):
        raise ValueError("invalid sensor value or occupancy target")
    return x, labels, stamps


def make_splits(x, labels, stamps, *, length=16, max_gap_seconds=300):
    if type(length) is not int or not 2 <= length <= 128 or max_gap_seconds <= 0:
        raise ValueError("invalid window contract")
    if x.ndim != 2 or x.shape != (len(stamps), len(FEATURES)) or labels.shape != stamps.shape:
        raise ValueError("incompatible source shapes")
    n = len(x)
    cut1, cut2 = int(n*.6), int(n*.8)
    if min(cut1, cut2-cut1, n-cut2) <= 3*length:
        raise ValueError("insufficient chronology for disjoint windows")
    # Purge length rows at each internal boundary; no window can cross a split.
    bounds = {"train": (0, cut1-length), "dev": (cut1+length, cut2-length),
              "test": (cut2+length, n)}
    mean = x[:cut1-length].mean(0)
    scale = x[:cut1-length].std(0)
    scale = np.where(scale > 1e-8, scale, 1.0)
    scaled = np.clip((x-mean)/scale, -8, 8)
    splits, timing = {}, {}
    used = set()
    for name, (lo, hi) in bounds.items():
        samples, targets, durations, identities = [], [], [], []
        input_times, target_times = [], []
        segments = np.r_[lo, np.flatnonzero(np.diff(stamps[lo:hi]) > max_gap_seconds)+lo+1, hi]
        for a, b in zip(segments[:-1], segments[1:]):
            for start in range(int(a), int(b)-length, length+1):
                stop = start+length
                rows = set(range(start, stop+1))
                if rows & used:
                    raise AssertionError("source row reused across windows")
                used.update(rows)
                samples.append(scaled[start:stop])
                targets.append(np.eye(4)[labels[stop]])
                durations.append(np.diff(stamps[start:stop+1]).astype(np.float64))
                identities.append(f"uci864:{start}:{stop}:{stamps[stop]}")
                input_times.append(stamps[start:stop])
                target_times.append(stamps[stop])
        if not samples:
            raise ValueError(f"empty chronological {name} split")
        splits[name] = {"x": np.stack(samples), "y": np.stack(targets), "dt": np.stack(durations),
                        "ids": np.asarray(identities), "input_times": np.stack(input_times),
                        "target_times": np.asarray(target_times, dtype=np.int64)}
        timing[name] = {"source_bounds_half_open": [lo, hi], "windows": len(samples),
                        "duration_seconds_min": float(np.min(durations)),
                        "duration_seconds_max": float(np.max(durations)),
                        "first_input_time": int(input_times[0][0]),
                        "last_target_time": int(target_times[-1])}
    return splits, {"length": length, "max_gap_seconds": max_gap_seconds,
                    "purge_rows_per_side": length, "stride": length+1,
                    "normalization_train_only": {"mean": mean.tolist(), "scale": scale.tolist(), "clip": 8},
                    "splits": timing}


def prepare(source, destination, *, length=16):
    raw = Path(source).read_bytes()
    arrays = read_rows(raw)
    splits, contract = make_splits(*arrays, length=length)
    out = Path(destination)
    out.mkdir(parents=True, exist_ok=False)
    files = {}
    for name, data in splits.items():
        path = out/f"{name}.npz"
        np.savez_compressed(path, **data)
        files[name] = {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest = {"schema": "hcsn-real-sensor-windows-v1", "source_url": SOURCE_URL,
                "source_csv_sha256": SOURCE_SHA256, "source_rows": len(arrays[0]),
                "citation": "Singh, A. & Chaudhari, S. (2018). Room Occupancy Estimation. UCI. doi:10.24432/C5P605",
                "license": "CC BY 4.0", "feature_columns": FEATURES, "modalities": MODALITIES,
                "clock": "naive published local Date/Time; differences in physical seconds; timezone unspecified",
                "task": "nowcast occupancy at query arrival using only earlier sensor observations",
                "query_contract": "target timestamp known at query arrival; target row sensors and label withheld; every baseline receives the same elapsed times",
                "excluded_features": ["S5_CO2_Slope"], "boundary_handling": "reset between windows; omit gaps over 300 seconds",
                "raw_audio_or_images": False, "contract": contract, "files": files}
    (out/"dataset.json").write_text(json.dumps(manifest, indent=2)+"\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("destination")
    parser.add_argument("--length", type=int, default=16)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.destination, length=args.length), indent=2))
