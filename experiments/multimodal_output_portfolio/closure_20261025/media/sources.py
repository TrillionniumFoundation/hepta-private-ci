"""Stream pinned real speech roles without extracting or retrieving output WAVs."""

import hashlib
import io
import json
from pathlib import Path
import tarfile
import wave

import numpy as np
import torch
from torch.nn import functional as F

from ...v7_media.corpus import FSDD_ARCHIVE_SHA256, FSDD_COMMIT, ROLE_INDICES


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def save_json(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def speech_role(archive, role):
    """Return only one declared recording role; labels are training/audit targets."""
    if role not in ROLE_INDICES or sha(archive) != FSDD_ARCHIVE_SHA256:
        raise ValueError("Unknown speech role or changed pinned archive")
    signals, labels, metadata = [], [], []
    with tarfile.open(archive, "r:gz") as source:
        for member in sorted(source.getmembers(), key=lambda item: item.name):
            parts = Path(member.name).parts
            if len(parts) != 3 or parts[1] != "recordings" or not parts[2].endswith(".wav"):
                continue
            if parts[0] != "free-spoken-digit-dataset-" + FSDD_COMMIT or not member.isfile():
                raise ValueError("Unexpected source tree member")
            label, speaker, index = Path(parts[2]).stem.split("_")
            label, index = int(label), int(index)
            if not 0 <= label < 10 or not 0 <= index < 50 or member.size > 100000:
                raise ValueError("Source recording outside bounds")
            if index not in ROLE_INDICES[role]:
                continue
            raw = source.extractfile(member).read()
            with wave.open(io.BytesIO(raw)) as wav:
                if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 8000):
                    raise ValueError("Source PCM format changed")
                count = wav.getnframes()
                samples = np.frombuffer(wav.readframes(count), dtype="<i2").astype(np.float32) / 32768
            value = torch.from_numpy(samples.copy())
            if not 0 < len(value) <= 32000 or value.abs().max() <= 1e-5:
                raise ValueError("Empty source speech")
            value = .9 * value / value.abs().max()
            value = (F.interpolate(value[None, None], size=8000, mode="linear", align_corners=False)[0, 0]
                     if len(value) > 8000 else F.pad(value, (0, 8000 - len(value))))
            signals.append(value)
            labels.append(label)
            metadata.append({"path": member.name, "label": label, "speaker": speaker,
                             "index": index, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    if len(signals) != 60 * len(ROLE_INDICES[role]):
        raise ValueError("Incomplete source role census")
    return torch.stack(signals), torch.tensor(labels), metadata


def source_pins():
    root = Path(__file__).resolve().parents[2]
    paths = list(Path(__file__).parent.glob("*.py")) + [Path(__file__).with_name("protocol.json")]
    for directory, names in {"v7_media": ("models", "corpus", "media", "audit"),
                             "v7": ("model", "snapshot", "sources", "data", "evaluation"),
                             "v6": ("data", "neural", "observer")}.items():
        paths.extend(root / directory / (name + ".py") for name in names)
    return {str(path.relative_to(root)): sha(path) for path in paths}
