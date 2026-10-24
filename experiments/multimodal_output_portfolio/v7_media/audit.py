"""Offline joint outcome labels and target-free raw-media feature extraction."""

import time

import numpy as np
import torch

from ..v6.observer import CAPTION
from .corpus import WORD_SAMPLES, speech_spectrum
from .media import read_media


def observable_media_features(decoded):
    """Use actual public output bytes only; never inspect expected semantics."""
    audio = np.frombuffer(decoded["audio_bytes"], dtype="<i2").astype(np.float32).reshape(2, WORD_SAMPLES) / 32768
    video = np.frombuffer(decoded["video_bytes"], dtype=np.uint8).reshape(20, 28, 28, 3).astype(np.float32) / 255
    features = []
    for segment in audio:
        features.extend([float(np.sqrt(np.mean(segment * segment))),
                         float(np.mean(np.abs(segment) > .05)),
                         float(np.mean(np.signbit(segment[1:]) != np.signbit(segment[:-1])))])
    gray = video.mean(axis=-1)
    for block in (gray[:10], gray[10:]):
        features.extend([float(block.mean()), float(block.std()),
                         float(np.abs(np.diff(block, axis=0)).mean())])
    features.append(float(CAPTION.fullmatch(decoded["caption"].strip()) is not None))
    if not np.isfinite(features).all():
        raise ValueError("Nonfinite actual media features")
    return features


def observe_four_modal_bundle(paths, pixel_observer, speech_observer, expected_labels):
    """Evaluate raw artifacts after generation; this function is not a decoder."""
    started = time.perf_counter_ns()
    labels = torch.as_tensor(expected_labels, dtype=torch.long).reshape(-1)
    if labels.shape != (2,) or (labels < 0).any() or (labels > 9).any():
        raise ValueError("Offline expected semantics must contain two source labels")
    decoded = read_media(paths)
    image = torch.from_numpy(decoded["image"].copy()).float() / 255
    image_digits = torch.stack((image[:, :28], image[:, 28:]))[:, None]
    audio = np.frombuffer(decoded["audio_bytes"], dtype="<i2").astype(np.float32).reshape(2, WORD_SAMPLES) / 32768
    rgb = np.frombuffer(decoded["video_bytes"], dtype=np.uint8).reshape(20, 28, 28, 3)
    if not np.array_equal(rgb[..., 0], rgb[..., 1]) or not np.array_equal(rgb[..., 0], rgb[..., 2]):
        raise ValueError("This registered video profile requires genuine grayscale frames")
    frame_pixels = torch.from_numpy(rgb[..., 0].copy()).float()[:, None] / 255
    with torch.inference_mode():
        image_predictions = pixel_observer(image_digits).argmax(-1)
        if hasattr(speech_observer, "predict_pcm16"):
            audio_predictions = torch.tensor(speech_observer.predict_pcm16(decoded["audio_bytes"]))
        else:
            audio_predictions = speech_observer(speech_spectrum(torch.from_numpy(audio.copy()))).argmax(-1)
        video_predictions = pixel_observer(frame_pixels).argmax(-1)
    caption = CAPTION.fullmatch(decoded["caption"].strip())
    expected = labels.tolist()
    relation = "less" if expected[0] < expected[1] else "greater" if expected[0] > expected[1] else "equal"
    caption_digits = [int(caption[1]), int(caption[2])] if caption else None
    success = {
        "text": bool(caption and caption_digits == expected and caption[3] == relation),
        "image": bool(torch.equal(image_predictions, labels)),
        "audio": bool(torch.equal(audio_predictions, labels)),
        "video": bool(torch.equal(video_predictions, labels.repeat_interleave(10))),
    }
    return {"schema": "hepta.ndu.four-modal-observation.v1", "required_mask": 15,
            "success": success, "joint_success": all(success.values()),
            "strict_completion": True, "expected_labels": expected,
            "caption_digits": caption_digits, "image_digits": image_predictions.tolist(),
            "audio_digits": audio_predictions.tolist(), "video_digits": video_predictions.tolist(),
            "clock": decoded["clock"], "observable_features": observable_media_features(decoded),
            "audit_wall_ns": time.perf_counter_ns() - started,
            "scope": "Local frozen observer labels; not human or external attestation"}
