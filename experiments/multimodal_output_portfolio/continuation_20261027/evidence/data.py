"""Pinned real waveform custody and the unchanged frozen FSDD observer interface."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import time
import urllib.request
import wave


AREA = Path(__file__).parent
PROTOCOL = AREA / "PROTOCOL_V2.json"


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def download(destination):
    protocol = json.loads(PROTOCOL.read_text())
    destination.mkdir(parents=True, exist_ok=True)
    origin = ("https://raw.githubusercontent.com/soerenab/AudioMNIST/"
              + protocol["source_commit"] + "/")
    paths = ["README.md", "LICENSE"] + [
        f"data/{speaker}/{digit}_{speaker}_{index}.wav"
        for speakers in protocol["speaker_roles"].values() for speaker in speakers
        for digit in protocol["digits"] for index in protocol["recording_indices"]]

    def one(name):
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(origin + name, timeout=30) as response:
                        payload = response.read()
                    if name.endswith(".wav") and payload[:4] != b"RIFF":
                        raise ValueError("The pinned URL did not return RIFF bytes")
                    temporary = path.with_suffix(path.suffix + ".partial")
                    temporary.write_bytes(payload)
                    temporary.rename(path)
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(attempt + 1)
        return {"path": name, "sha256": digest(path), "bytes": path.stat().st_size}

    results = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(one, name): name for name in paths}
        for future in as_completed(futures):
            results.append(future.result())
            if len(results) % 500 == 0:
                print(json.dumps({"downloaded": len(results), "total": len(paths)}), flush=True)
    results.sort(key=lambda row: row["path"])
    wav = [row for row in results if row["path"].endswith(".wav")]
    if len({row["sha256"] for row in wav}) != len(wav):
        raise ValueError("Physical duplicate WAVs require source-role overlap review")
    manifest = {"schema": "hepta.ndu.audiomnist.source.v1",
                "source_commit": protocol["source_commit"],
                "protocol_sha256": digest(PROTOCOL), "files": results,
                "waveforms": len(wav), "bytes": sum(row["bytes"] for row in results),
                "test_waveform_model_features_computed": False}
    save(destination / "SOURCE_MANIFEST.json", manifest)
    return manifest


def features(path):
    import numpy as np
    from scipy.signal import resample_poly
    import torch
    from torch.nn import functional as functional

    with wave.open(str(path), "rb") as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (1, 2, 48000):
            raise ValueError("Pinned source interface requires mono PCM16 at 48 kHz")
        samples = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").copy()
    signal = resample_poly(samples.astype(np.float64) / 32768., 1, 6)
    x = torch.from_numpy(signal).float()
    if len(x) < 256:
        x = functional.pad(x, (0, 256 - len(x)))
    spectrum = torch.stft(x, n_fft=256, hop_length=64, window=torch.hann_window(256),
                          center=False, return_complex=True).abs().log1p()
    z = functional.interpolate(spectrum[None, None], size=(64, 64),
                               mode="bilinear", align_corners=False)[0]
    return (z - z.mean()) / z.std().clamp_min(1e-6)


def observe(source, speakers, checkpoint):
    import torch
    from ...repair_20261026.evidence.real_audio import DigitObserver

    protocol = json.loads(PROTOCOL.read_text())
    if digest(checkpoint) != protocol["observer"]["sha256"]:
        raise ValueError("Frozen observer checkpoint identity mismatch")
    manifest = json.loads((source / "SOURCE_MANIFEST.json").read_text())
    inventory = {row["path"]: row for row in manifest["files"]}
    model = DigitObserver().eval().requires_grad_(False)
    model.load_state_dict(torch.load(checkpoint, map_location="cpu", weights_only=True))
    rows = []
    with torch.inference_mode():
        for speaker in speakers:
            names = [f"data/{speaker}/{digit}_{speaker}_{index}.wav"
                     for digit in protocol["digits"] for index in protocol["recording_indices"]]
            x = torch.stack([features(source / name) for name in names])
            probabilities = torch.cat([model(chunk).softmax(-1) for chunk in x.split(64)]).double().numpy()
            for name, probability in zip(names, probabilities):
                if digest(source / name) != inventory[name]["sha256"]:
                    raise ValueError("Waveform changed since pinned-source custody")
                digit, _, index = Path(name).stem.split("_")
                rows.append({"source_path": name, "speaker": speaker, "target": int(digit),
                             "index": int(index), "event_id": inventory[name]["sha256"],
                             "observation": int(probability.argmax()),
                             "probabilities": probability.tolist()})
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", required=True, type=Path)
    arguments = parser.parse_args()
    result = download(arguments.destination)
    print(json.dumps({"complete": True, "waveforms": result["waveforms"], "bytes": result["bytes"]}))
