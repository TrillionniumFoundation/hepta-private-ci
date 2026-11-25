"""Prepare offline tensors with the unchanged archived low-level decoder.

Linux-only preparation accounting includes ffmpeg subprocess CPU. Test actors
are decoded without computing model scores or using their normalization moments.
"""

import argparse
from importlib.metadata import version
import json
from pathlib import Path
import platform
import resource
import subprocess
import time

import numpy as np

from .acquire import digest, save, stage
from .decoder_original import decode


def prepare(root):
    output = root/"prepared_model_clock_v2"
    output.mkdir()
    media = json.loads((root/"MEDIA_MANIFEST.json").read_text())
    acquisition = json.loads((root/"ACQUISITION.json").read_text())
    if (not acquisition["all_verified"] or acquisition["manifest_sha256"] != digest((root/"MEDIA_MANIFEST.json").read_bytes())):
        raise ValueError("unverified media acquisition")
    normalization = np.load(root/"base"/"normalization.npz", allow_pickle=False)
    mean, scale = normalization["mean"], normalization["scale"]
    train = np.load(root/"base"/"train.npz", allow_pickle=False)
    records, encoded, receipts = media["records"], [], []
    for index, row in enumerate(records, 1):
        path = root/"media"/(row["clip"]+".flv")
        if path.stat().st_size != row["bytes"] or digest(path.read_bytes()) != row["sha256"]:
            raise ValueError("media changed after acquisition")
        features, info = decode(path)
        encoded.append(features)
        receipts.append({"clip": row["clip"], **info})
        if index % 32 == 0:
            print(json.dumps({"decoded": index, "total": len(records)}), flush=True)
    normalized = ((np.asarray(encoded, dtype=np.float64)-mean)/scale).astype(np.float32)
    durations = np.asarray([r["duration_seconds"] for r in receipts], dtype=np.float32)
    test = {"audio": normalized[:, 0], "video": normalized[:, 1],
            "dt": np.repeat((10*durations/32)[:, None], 32, axis=1),
            "y": np.asarray([r["label"] for r in records], dtype=np.int64),
            "actor": np.asarray([r["actor"] for r in records]),
            "clip": np.asarray([r["clip"] for r in records])}
    split_rows = {}
    for name, arrays in (("train", train), ("dev", np.load(root/"base"/"validation.npz", allow_pickle=False)), ("test", test)):
        real_dt = arrays["dt"].astype(np.float64)*.1
        elapsed = np.cumsum(real_dt, axis=1)-.5*real_dt
        clocks = np.broadcast_to(np.stack((np.arange(32)/31, np.full(32, 1/32)), -1), (*real_dt.shape, 2)).astype(np.float32)
        values = {modality: np.concatenate((arrays[modality], clocks), -1) for modality in ("audio", "video")}
        values.update({key: arrays[key] for key in ("y", "actor", "clip")})
        values["elapsed_seconds"], values["dt_seconds"] = elapsed, real_dt
        if any(not np.isfinite(v).all() for v in values.values() if v.dtype.kind in "fc"):
            raise ValueError("nonfinite encoded data")
        np.savez_compressed(output/(name+".npz"), **values)
        split_rows[name] = {"path": name+".npz", "sha256": digest((output/(name+".npz")).read_bytes()),
            "examples": len(values["y"]), "actors": sorted(set(values["actor"].tolist())),
            "labels": np.bincount(values["y"], minlength=6).tolist()}
    if (set(split_rows["train"]["actors"]) & set(split_rows["test"]["actors"])
            or set(split_rows["dev"]["actors"]) & set(split_rows["test"]["actors"])):
        raise ValueError("actor leakage")
    save(output/"DECODE.json", {"records": receipts, "ffmpeg": subprocess.check_output(["ffmpeg", "-version"], text=True).splitlines()[0],
        "python": platform.python_version(), "numpy": np.__version__, "scipy": version("scipy"),
        "decoder_sha256": digest(Path(__file__).with_name("decoder_original.py").read_bytes())})
    save(output/"DATASET.json", {"schema": "hcsn-av-closure-offline-v1", "splits": split_rows,
        "roster_sha256": digest((root/"ROSTER.json").read_bytes()), "media_manifest_sha256": digest((root/"MEDIA_MANIFEST.json").read_bytes()),
        "base_dataset_sha256": digest((root/"base"/"DATASET.json").read_bytes()),
        "base_normalization_sha256": digest((root/"base"/"normalization.npz").read_bytes()),
        "decode_sha256": digest((output/"DECODE.json").read_bytes()), "shape_per_modality": [32, 130],
        "time_contract": "32 offline resampled positions. Every backbone uses normalized model dt=.25 and common t/31,1/32 input channels. Actual elapsed/dt are audit metadata ONLY, never read by a model.",
        "design_revision": "Before source/protocol freeze or any AV fitting/test evaluation, replaced proposed shared real timing inputs because they can identify paired recordings. Preserved discarded proposal and acquisition receipts.",
        "target_contract": "6 acted emotions and same-recording audiovisual match; no language/generative task",
        "independence_scope": "8 actors outside three audited prior manifests; not a global every-branch novelty claim",
        "license_database": "ODbL-1.0", "license_contents": "DbCL-1.0"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    stage(args.root, "prepare", prepare)
