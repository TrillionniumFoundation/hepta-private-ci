"""Fit a frozen public audio-label observation law using previously opened sources."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np
import torch

from ...next_20261025.media.audio_sources import load_audio
from ...next_20261025.media.repair.model import load_ingress
from ...v7_media.corpus import speech_spectrum


ROOT = Path(__file__).resolve().parents[4]
ALLOCATION = ROOT / "experiments/multimodal_output_portfolio/next_20261025/media/AUDIO_SOURCE_ALLOCATION.json"
ALLOCATION_SHA = "35862507212b97bc02bc1506070a31863f830e3c9e7747e5f3187ab2e6702fe5"
CHECKPOINT = Path("/tmp/hepta-ndu-next-media-cache/repair-training-001/audio-input.pt")
CHECKPOINT_SHA = "5c10b1ca0830879464f5d29219236fe88cb9422f7f630cb8dc7cc7b5844b3bbb"
AUDIO_ROOT = ROOT.parent / "ndu-next-assets/media/new-assets/speech-commands-v002-digits"
ALPHA = .5


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    if sha(ALLOCATION) != ALLOCATION_SHA or sha(CHECKPOINT) != CHECKPOINT_SHA:
        raise ValueError("Previously registered source/model bytes differ")
    sources = json.loads(ALLOCATION.read_text())["roles"]["qualification"]
    if len(sources) != 300:
        raise ValueError("The only authorized development role contains 300 recordings")
    dependencies = [Path(__file__), ALLOCATION, CHECKPOINT]
    dependencies += [ROOT / "experiments/multimodal_output_portfolio" / name for name in (
        "next_20261025/media/audio_sources.py", "next_20261025/media/repair/model.py",
        "closure_20261025/media/coherent.py", "v7_media/corpus.py")]
    registration = {
        "schema": "hepta.advance.audio-likelihood-development-registration.v1",
        "registered_ns": time.time_ns(), "alpha": ALPHA,
        "counts_axis": "observed argmax label, true source label",
        "source_role": "old qualification reused as development; not independent",
        "selection_history": "These 300 sources were previously used to select the frozen audio CNN",
        "factorization": "Pair observation law is the Kronecker product of digit laws; conditional error independence is an assumption, not established for same-speaker pairs",
        "fixed_candidate_count": 1, "source_recordings": len(sources),
        "input_sha256": {str(path): sha(path) for path in dependencies},
        "environment_threads": {name: os.getenv(name) for name in (
            "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")},
    }
    save(args.output / "registration.json", registration)
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    start = time.monotonic_ns()
    model = load_ingress(CHECKPOINT)
    probabilities = []
    with torch.inference_mode():
        for offset in range(0, len(sources), 32):
            waves = load_audio(AUDIO_ROOT, sources[offset:offset + 32])
            probabilities.append(model(speech_spectrum(waves)).softmax(-1).numpy())
    probabilities = np.concatenate(probabilities)
    prediction = probabilities.argmax(-1)
    truth = np.asarray([row["label"] for row in sources], dtype=np.int64)
    counts = np.zeros((10, 10), dtype=np.int64)
    np.add.at(counts, (prediction, truth), 1)
    digit_law = (counts + ALPHA) / (counts.sum(0) + 10 * ALPHA)
    pair_law = np.kron(digit_law, digit_law)
    if not np.allclose(pair_law.sum(0), 1., atol=1e-12):
        raise ValueError("Nonstochastic observation law")
    raw = args.output / "actual_observations.npz"
    np.savez_compressed(raw, probabilities=probabilities, prediction=prediction, truth=truth)
    result = {
        "schema": "hepta.advance.audio-label-likelihood.v1",
        "alpha": ALPHA, "count_matrix_observation_by_target": counts.tolist(),
        "digit_observation_by_target": digit_law.tolist(),
        "pair_observation_by_target": pair_law.tolist(),
        "observation_code": "left_argmax_label * 10 + right_argmax_label",
        "target_code": "left_true_digit * 10 + right_true_digit",
        "checkpoint_sha256": CHECKPOINT_SHA,
        "allocation_sha256": ALLOCATION_SHA,
        "registration_sha256": sha(args.output / "registration.json"),
        "actual_observations_sha256": sha(raw),
        "recordings": len(sources), "speakers": len({row["speaker"] for row in sources}),
        "development_correct": int((prediction == truth).sum()),
        "source_role": registration["source_role"],
        "factorization": registration["factorization"],
        "posterior_qualification": "Unqualified; fit-selected development likelihood and unvalidated pair independence",
        "inference_wall_ns": time.monotonic_ns() - start,
    }
    save(args.output / "likelihood.json", result)
    print(json.dumps({"path": str(args.output / "likelihood.json"),
        "sha256": sha(args.output / "likelihood.json"),
        "correct": result["development_correct"], "recordings": len(sources),
        "speakers": result["speakers"]}))


if __name__ == "__main__":
    main()
