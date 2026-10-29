"""Actual UTF-8, RGB PNG, PCM WAV and timed four-frame GIF readback scoring.

GIF is the declared low-resolution video diagnostic, not an open-domain video
codec claim. Natural semantic qualification uses its independent observer gate.
"""

import hashlib
from pathlib import Path
import wave

import numpy as np
from PIL import Image
import torch


def write_read(sample, directory, audio_rate=2048, frame_ms=120):
    shapes = {"image": (1, 3, 16, 16), "audio": (1, 1024), "video": (1, 4, 3, 16, 16), "text": (1, 2)}
    if (set(sample) != set(shapes) or any(tuple(sample[m].shape) != shape
            or not torch.isfinite(sample[m]).all() for m, shape in shapes.items())):
        raise ValueError("Nonfinite or malformed emitted sample cannot be codec-repaired")
    labels = sample["text"][0]
    if labels.dtype not in (torch.int64, torch.int32) or not (0 <= labels[0] < 63 and 0 <= labels[1] < 17):
        raise ValueError("Text emission outside the registered discrete law")
    if type(audio_rate) is not int or audio_rate <= 0 or type(frame_ms) is not int or frame_ms <= 0 or frame_ms % 10:
        raise ValueError("Unsupported media clock")
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=False)
    image = (sample["image"][0].detach().numpy().clip(0, 1) * 255).round().astype(np.uint8)
    Image.fromarray(image.transpose(1, 2, 0)).save(directory / "image.png")
    audio = (sample["audio"][0].detach().numpy().clip(-1, 1) * 32767).round().astype("<i2")
    with wave.open(str(directory / "audio.wav"), "wb") as handle:
        handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(audio_rate)
        handle.writeframes(audio.tobytes())
    video = (sample["video"][0].detach().numpy().clip(0, 1) * 255).round().astype(np.uint8)
    frames = [Image.fromarray(frame.transpose(1, 2, 0)) for frame in video]
    frames[0].save(directory / "video.gif", save_all=True, append_images=frames[1:],
                   duration=frame_ms, loop=0, optimize=False, disposal=2)
    text = sample["text"][0].detach().tolist()
    (directory / "text.txt").write_text(f"action={text[0]};sound={text[1]}\n", encoding="utf-8")
    return read_bundle(directory, audio_rate=audio_rate, frame_ms=frame_ms)


def read_bundle(directory, audio_rate=2048, frame_ms=120):
    directory = Path(directory)
    with Image.open(directory / "image.png") as handle:
        image = np.asarray(handle.convert("RGB"), dtype=np.float32).copy().transpose(2, 0, 1) / 255
    with wave.open(str(directory / "audio.wav"), "rb") as handle:
        if (handle.getnchannels(), handle.getsampwidth(), handle.getframerate()) != (1, 2, audio_rate):
            raise ValueError("Audio law changed")
        audio = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2").astype(np.float32) / 32767
    with Image.open(directory / "video.gif") as handle:
        frames = []
        for i in range(handle.n_frames):
            handle.seek(i)
            duration = handle.info.get("duration", 0)
            if duration <= 0 or duration % frame_ms or duration > 4 * frame_ms:
                raise ValueError("Media clock changed")
            frame = np.asarray(handle.convert("RGB"), dtype=np.float32).copy().transpose(2, 0, 1) / 255
            frames.extend([frame] * (duration // frame_ms))
    # Expanding a codec's registered duration preserves its real media clock.
    if (len(frames) != 4 or any(f.shape != (3, 16, 16) for f in frames)
            or audio.shape != (1024,) or image.shape != (3, 16, 16)):
        raise ValueError("Actual media shape differs from emission law")
    text = (directory / "text.txt").read_text(encoding="utf-8")
    fields = text.strip().split(";")
    if len(fields) != 2 or not fields[0].startswith("action=") or not fields[1].startswith("sound="):
        raise ValueError("Malformed unrepaired text")
    labels = np.array([int(fields[0][7:]), int(fields[1][6:])], dtype=np.int64)
    if not (0 <= labels[0] < 63 and 0 <= labels[1] < 17):
        raise ValueError("Text label outside the frozen ontology")
    tensors = {"image": torch.from_numpy(image)[None], "audio": torch.from_numpy(audio)[None],
               "video": torch.from_numpy(np.stack(frames))[None], "text": torch.from_numpy(labels)[None]}
    paths = {"image": "image.png", "audio": "audio.wav", "video": "video.gif", "text": "text.txt"}
    identities = {m: hashlib.sha256((directory / name).read_bytes()).hexdigest() for m, name in paths.items()}
    return tensors, identities


def utility(sample, target):
    """Fixed mechanism/restoration metric, independent of trainable model weights."""
    errors = torch.stack([(sample[m] - target[m]).square().flatten(1).mean(1)
                          for m in ("image", "audio", "video")], -1)
    text = (sample["text"] == target["text"]).to(errors.dtype).mean(-1)
    # Multiplicative media component retains joint failure interactions.
    return 0.65 * torch.exp(-4 * errors.sum(-1)) + 0.35 * text
