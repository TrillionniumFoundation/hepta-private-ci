"""Metadata-only speaker-disjoint allocation of official Speech Commands digits."""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly
import torch

from ...abc_next.temporal.speech import read_pcm
from ...closure_20261025.media.sources import sha, save_json
from .observers import WORDS


SALT = "hepta-next-audio-20261025-v1"


def rank(value):
    return hashlib.sha256((SALT + ":" + value).encode()).digest()


def register(root, output):
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text())
    test = set((root / "testing_list.txt").read_text().splitlines())
    valid = set((root / "validation_list.txt").read_text().splitlines())
    roles, speakers = defaultdict(list), defaultdict(set)
    for row in manifest["files"]:
        path = Path(row["path"])
        if path.suffix != ".wav":
            continue
        role = "confirmation" if row["path"] in test else "qualification" if row["path"] in valid else "fit"
        speaker = path.stem.split("_nohash_")[0]
        enriched = {**row, "label": WORDS.index(path.parts[0]), "speaker": speaker}
        roles[role].append(enriched)
        speakers[role].add(speaker)
    if any(speakers[a] & speakers[b] for a, b in (("fit", "qualification"), ("fit", "confirmation"), ("qualification", "confirmation"))):
        raise ValueError("Official speaker roles overlap")
    selected = {}
    for role, count in (("fit", 300), ("qualification", 30)):
        selected[role] = [row for digit in range(10)
                          for row in sorted((r for r in roles[role] if r["label"] == digit), key=lambda r: rank(r["path"]))[:count]]
        if len(selected[role]) != 10 * count:
            raise ValueError("Insufficient fixed role size")
    by_speaker = defaultdict(list)
    for row in roles["confirmation"]:
        by_speaker[row["speaker"]].append(row)
    eligible = sorted((s for s, rows in by_speaker.items() if len({r["label"] for r in rows}) == 10), key=rank)
    if len(eligible) < 56:
        raise ValueError("Expected enough complete-vocabulary held-out speakers")
    for role, group in (("media", eligible[:32]), ("joint", eligible[32:56])):
        selected[role] = []
        for speaker in group:
            for digit in range(10):
                candidates = sorted((r for r in by_speaker[speaker] if r["label"] == digit), key=lambda r: rank(r["path"]))
                selected[role].append(candidates[0])
    result = {"schema": "hepta.next.audio-source-allocation.v1", "salt": SALT,
              "source_manifest_sha256": sha(root / "manifest.json"),
              "whole_archive_sha256": manifest["whole_archive_sha256"],
              "source_url": manifest["url"], "license": "CC-BY-4.0, Pete Warden",
              "allocator_sha256": sha(__file__), "roles": selected,
              "official_role_speaker_counts": {k: len(v) for k, v in speakers.items()},
              "official_role_overlap": 0, "fit_recordings": 3000,
              "qualification_recordings": 300,
              "confirmation_selection": "Metadata-only complete-vocabulary speakers; first hashed recording per digit, no acoustic quality filter",
              "media_speakers": eligible[:32], "joint_speakers": eligible[32:56],
              "input_pairing": "Media writer group maps to one unique audio speaker; joint writer groups map modulo24, and must cluster repeated speakers",
              "new_model_scores_opened": False, "pretrained_model_corpus_overlap_known": False}
    save_json(output, result)
    return result


def load_audio(root, rows):
    """Reopen exact selected PCM; normalization has no label-dependent branch."""
    signals = []
    for row in rows:
        path = Path(root) / row["path"]
        if sha(path) != row["sha256"]:
            raise ValueError("Changed public recording")
        rate, pcm = read_pcm(path)
        signal = resample_poly(pcm.astype(np.float64) / 32768, 8000, rate).astype(np.float32)
        if len(signal) > 8000:
            raise ValueError("Official keyword event exceeds one second")
        peak = np.abs(signal).max()
        if peak > 0:
            signal = .9 * signal / peak
        signals.append(np.pad(signal, (0, 8000 - len(signal))))
    return torch.from_numpy(np.stack(signals))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = register(args.root, args.output)
    print(json.dumps({"sha256": sha(args.output), "counts": {k: len(v) for k, v in result["roles"].items()}}))
