"""Actual neural generation, physical codecs and separate target-free audits."""

import hashlib
from pathlib import Path
import shutil
import time

import numpy as np
import torch
from torch.nn import functional as F

from ...abc_next.temporal.speech import write_pcm
from ...closure_20261025.media import carrier_media
from ...closure_20261025.media.coherent import CoherentVideo, MelSpeech
from ...closure_20261025.media.network import VideoInput
from ...closure_20261025.media.sources import sha
from ...v6.data import render_tokens
from ...v6.observer import CAPTION, Recognizer
from ...v7.snapshot import Snapshot
from ...v7_media.corpus import spectrum_waveform
from ...v7_media.models import AcousticDecoder
from .observers import FrozenSpeechObservers
from .waveform import WaveformStudent


def load_components(shared, restored, student, audio_input):
    """Restore explicit model bytes; no current or future source outcomes enter."""
    shared, restored = Path(shared), Path(restored)
    checkpoint = shared / "abc2-runs/training-001/seed-17/output_ndu/model.pt"
    generator = Snapshot.load(checkpoint, expected_file_sha256=sha(checkpoint))._model
    paths = {"student": Path(student), "audio_input": Path(audio_input),
             "motion": restored / "evidence/refine-001/video.pt",
             "video_input": restored / "evidence/training-001/video_input.pt",
             "vae": restored / "evidence/acoustic-repair-001/acoustic.pt",
             "image_audit": shared / "abc2-runs/qualification-001/secondary-observer.pt"}
    constructors = {"student": WaveformStudent, "audio_input": MelSpeech,
                    "motion": CoherentVideo, "video_input": VideoInput,
                    "vae": AcousticDecoder, "image_audit": Recognizer}
    models = {"generator": generator}
    for name, path in paths.items():
        model = constructors[name]().eval().requires_grad_(False)
        model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True)["state_dict"], strict=True)
        models[name] = model
    return models, {str(checkpoint): sha(checkpoint), **{str(path): sha(path) for path in paths.values()}}


@torch.inference_mode()
def render_state(generator, student, motion, state, directory, request_id, vae=None, seed=23117):
    """Generate from public state, never from labels or precomputed wave files."""
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    output = generator.decode(state)
    probabilities = generator.semantic_probabilities(state)
    hard = F.one_hot(probabilities.argmax(-1), 10).float()
    if vae is None:
        waveform = student(hard.reshape(-1, 10))
        backend = "trained_phase_preserving_waveform_student"
    else:
        legacy = spectrum_waveform(vae.decode(hard.reshape(-1, 10)), seed)
        waveform = F.pad(legacy, (0, 8000))
        backend = "legacy_vae_same_four_second_presentation"
    frames = motion(hard, output.image_logits.sigmoid()).sigmoid()[0]
    identity = hashlib.sha256(b"".join(getattr(state, name).detach().cpu().numpy().tobytes()
                                      for name in ("h", "image", "text", "context"))).hexdigest()
    media = carrier_media.write_media(directory, render_tokens(output.token_ids[0]),
              output.image_logits[0].sigmoid(), waveform, frames,
              {"request_sha256": hashlib.sha256(request_id.encode()).hexdigest(), "state_sha256": identity},
              shutil.which("ffmpeg"), shutil.which("ffprobe"))
    return {"output": media, "predicted_semantic_posterior": probabilities.tolist(),
            "state_sha256": identity, "backend": backend,
            "execution_wall_ns": time.perf_counter_ns() - started,
            "python_cpu_ns": time.process_time_ns() - cpu}


class WaveAudit:
    """Reuse completed observations only by exact actual waveform bytes."""

    def __init__(self, assets, output):
        self.models = FrozenSpeechObservers(assets)
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=False)
        self.cache, self.calls, self.hits = {}, 0, 0

    def observe_pcm(self, pcm, carrier):
        key = (hashlib.sha256(pcm).hexdigest(), carrier)
        started = time.perf_counter_ns()
        if key in self.cache:
            self.hits += 1
            return {**self.cache[key], "cache_hit": True, "request_wall_ns": time.perf_counter_ns() - started}
        path = self.output / (key[0] + ".wav")
        if not path.exists():
            write_pcm(path, 8000, np.frombuffer(pcm, dtype="<i2"))
        row = self.models.observe(path, carrier=carrier)
        self.calls += 1
        self.cache[key] = row
        return {**row, "cache_hit": False, "request_wall_ns": time.perf_counter_ns() - started}


def observe_bundle(paths, image_observer, speech_observer, carrier=True):
    """Only actual serialized output is visible to image and speech observers."""
    started = time.perf_counter_ns()
    decoded = carrier_media.read_media(paths)
    pixels = torch.from_numpy(decoded["image"].copy()).float() / 255
    panels = torch.stack((pixels[:, :28], pixels[:, 28:]))[:, None]
    frames = np.frombuffer(decoded["video_bytes"], dtype=np.uint8).reshape(20, 28, 28, 3)
    with torch.inference_mode():
        image_digits = image_observer(panels).argmax(-1).tolist()
        video_digits = image_observer(torch.from_numpy(frames[..., 0].copy()).float()[:, None] / 255).argmax(-1).tolist()
    speech = speech_observer.observe_pcm(decoded["audio_bytes"], carrier=carrier)
    caption = CAPTION.fullmatch(decoded["caption"].strip())
    return {"caption_digits": [int(caption[1]), int(caption[2])] if caption else None,
            "caption_relation": caption[3] if caption else None,
            "image_digits": image_digits, "video_digits": video_digits,
            "speech": speech, "clock": decoded["clock"],
            "content_checks": carrier_media.content_checks(decoded, 6),
            "audit_wall_ns": time.perf_counter_ns() - started, "target_supplied": False}


def score_observation(observed, expected):
    """Attach ground truth only after every actual output observation completed."""
    expected = list(expected)
    relation = "less" if expected[0] < expected[1] else "greater" if expected[0] > expected[1] else "equal"
    success = {"text": observed["caption_digits"] == expected and observed["caption_relation"] == relation,
               "image": observed["image_digits"] == expected,
               "video": observed["video_digits"] == [value for digit in expected for value in [digit] * 10],
               "audio": observed["speech"]["predictions"]["small.en"] == expected}
    return {"expected_after_observation": expected, "success": success,
            "joint_success": all(success.values()) and observed["content_checks"]["moving_video"]
                             and observed["content_checks"]["nonempty_audio"],
            "secondary_audio_success": observed["speech"]["predictions"]["base.en"] == expected}
