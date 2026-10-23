"""Reuse immutable TRAIN/cache bytes, preserving their fully priced history."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from data import prepare_decoded_observer
from independent.learning import CONTENT_PARAMETERS, setup_work
from ndu_training.cv_train_d2.budget import ROOT, plan
from ndu_training.reinfer_d1.kernels import Reference


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def required_files():
    p = plan()
    old, new = ROOT / p["original_run"], ROOT / p["TRAIN_and_reference_run"]
    artifacts = json.loads((old / "artifacts.json").read_text())["files"]
    latest = json.loads((new / "artifacts.json").read_text())["files"]
    result = {
        old / name: artifacts[name]["sha256"]
        for name in (
            "base-11.npz",
            "base-23.npz",
            "base-47.npz",
            "build/libjoint.so",
            "result.json",
        )
    }
    result.update(
        {
            new / name: latest[name]["sha256"]
            for name in (
                "TRAIN-inputs.npz",
                "TRAIN-map.json",
                "base-reference-11.npz",
                "base-reference-23.npz",
                "base-reference-47.npz",
                "result.json",
            )
        }
    )
    for path in (
        old / "artifacts.json",
        new / "artifacts.json",
        ROOT / "ndu_training/reinfer_d1/evidence/run-d1.txt",
    ):
        result[path] = sha(path)
    return result


def verify_inputs():
    files = required_files()
    for path, expected in files.items():
        if sha(path) != expected:
            raise ValueError(f"immutable TRAIN/base/cache hash mismatch: {path}")
    return {str(path.relative_to(ROOT)): digest for path, digest in files.items()}


def load_inputs():
    path = ROOT / plan()["TRAIN_and_reference_run"]
    with np.load(path / "TRAIN-inputs.npz", allow_pickle=False) as saved:
        arrays = {
            key: saved[key]
            for key in (
                "full",
                "low",
                "labels",
                "cohorts",
                "row_source_index",
                "commands",
                "source_scene",
            )
        }
    assert arrays["full"].shape == arrays["low"].shape == (3072, 202)
    assert arrays["labels"].shape == (3072,) and arrays["cohorts"].shape == (48, 64)
    mapping = json.loads((path / "TRAIN-map.json").read_text())
    assert len(mapping["source_ids"]) == 192
    for value in arrays.values():
        value.flags.writeable = False
    return arrays, mapping


def load_reference(seed, base, arrays):
    """No forward/rebuild: exact paid reference cache from the consumed diagnostic."""
    path = ROOT / plan()["TRAIN_and_reference_run"] / f"base-reference-{seed}.npz"
    ref = Reference.__new__(Reference)
    ref.model = base
    ref.x = np.concatenate((arrays["full"], arrays["low"]))
    ref.y = np.tile(arrays["labels"], 2)
    with np.load(path, allow_pickle=False) as stored:
        for attr, key in (
            ("h", "hidden"),
            ("dh", "ce_dhidden"),
            ("dt", "ce_dtext"),
            ("di", "ce_dimage"),
        ):
            setattr(ref, attr, stored[key])
        ref.mean = {key: stored["mean_" + key] for key in CONTENT_PARAMETERS}
    for value in (ref.x, ref.y, ref.h, ref.dh, ref.dt, ref.di, *ref.mean.values()):
        value.flags.writeable = False
    return ref


def readout_observer(base, ledger):
    ledger.charge_kernel(
        "readout_setup", "decoded_reward", **setup_work(base.dimensions, "A")
    )
    observer = prepare_decoded_observer(base)
    ledger.charge_kernel(
        "readout_setup", "reward_exponential", scalar_ops=1728, exp_ops=1728
    )
    return SimpleNamespace(
        reward=observer.reward,
        observations=observer.observations,
        exponential_reward=np.exp(-1.5 * observer.reward),
    )
