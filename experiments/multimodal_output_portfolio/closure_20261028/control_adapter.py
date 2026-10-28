"""Existing natural generator adapter for real train/development integration.

This bounded 32-pixel model is used only to verify the new host execution path.
Fresh natural capability work has a separately frozen generator and observer.
"""

import hashlib
import io
import math
from pathlib import Path
import wave

import numpy as np
from PIL import Image
import torch

from ..continuation_20261027.control.client import sha
from ..unified_20261028.native_joint_episode import reopen
from ..unified_20261028.natural_model import draw, parameter_hash, process_ffmpeg, score_bundle, text_render
from ..unified_20261028.profile import digest


class ExistingNaturalAdapter:
    def __init__(self, *, model, checkpoint, assets, item, seed, fault):
        self.model, self.checkpoint, self.assets, self.item = model, Path(checkpoint), Path(assets), item
        self.seed, self.fault = seed, fault

    def prepare(self):
        snapshot = torch.load(self.checkpoint, weights_only=True, map_location="cpu")
        if snapshot["vocabulary"] != self.model.vocabulary or any(
                not torch.equal(value, snapshot["model"][name])
                for name, value in self.model.state_dict().items()):
            raise ValueError("Actual deployed tensor/vocabulary differs from the frozen checkpoint")
        self.parameter_sha = parameter_hash(self.model)
        with np.load(self.assets / "EVENTS.npz") as arrays:
            index = self.item["index"]
            video = arrays["context_video"][index:index + 1].copy()
            audio = arrays["context_audio"][index:index + 1].copy()
        self.video = torch.from_numpy(video).float().permute(0, 1, 4, 2, 3) / 255
        self.audio = torch.from_numpy(audio).float()
        self.rng = torch.Generator().manual_seed(self.seed)
        return {key: self.item[key] for key in ("event_id", "source_id", "split")} | {
            "input_sha256": digest({"video": hashlib.sha256(video.tobytes()).hexdigest(),
                                     "audio": hashlib.sha256(audio.tobytes()).hexdigest()}),
            "checkpoint_sha256": sha(self.checkpoint), "parameter_sha256": self.parameter_sha,
            "seed": self.seed, "declared_transport_fault": self.fault}

    def emit(self, action, public, directory, register_sample, write_file):
        if parameter_hash(self.model) != self.parameter_sha:
            raise ValueError("Generator changed during the actual owner trajectory")
        before = hashlib.sha256(self.rng.get_state().numpy().tobytes()).hexdigest()
        output = self.model(self.video, self.audio)
        values, logp = draw(output, self.rng)
        logp -= sum(values[name][0].numel() * (math.log(sigma) + .5 * math.log(2 * math.pi))
                    for name, sigma in (("image", .015), ("video", .015), ("audio", .0015)))
        sample = hashlib.sha256()
        for name, tensor in sorted(values.items()):
            sample.update(name.encode()); sample.update(tensor.detach().numpy().tobytes())
        descriptor = {"sampled_sha256": sample.hexdigest(), "rng_before_sha256": before,
                      "rng_after_sha256": hashlib.sha256(self.rng.get_state().numpy().tobytes()).hexdigest()}
        register_sample(logp.sum(), descriptor)
        refs, failure = {}, None
        try:
            stream = io.BytesIO()
            pixels = np.uint8(np.clip(values["image"][0].detach().numpy().transpose(1, 2, 0), 0, 1) * 255 + .5)
            Image.fromarray(pixels).save(stream, format="PNG")
            refs["image"] = write_file("image", ".png", stream.getvalue())
            pcm = np.int16(np.clip(values["audio"][0].detach().numpy(), -1, 1) * 32767)
            stream = io.BytesIO()
            with wave.open(stream, "wb") as output_wav:
                output_wav.setnchannels(1); output_wav.setsampwidth(2); output_wav.setframerate(8000)
                output_wav.writeframes(pcm.astype("<i2").tobytes())
            refs["audio"] = write_file("audio", ".wav", stream.getvalue())
            video = np.uint8(np.clip(values["video"][0].detach().numpy().transpose(0, 2, 3, 1), 0, 1) * 255 + .5)
            encoded_video = process_ffmpeg(["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "32x32",
                                           "-r", "8", "-i", "pipe:0", "-an", "-c:v", "ffv1", "-level", "3",
                                           "-pix_fmt", "bgr0", "-f", "matroska", "pipe:1"], video.tobytes())
            if self.fault and action == "keep":
                encoded_video = encoded_video[:8]
            refs["video"] = write_file("video", ".mkv", encoded_video)
            refs["text"] = write_file("text", ".txt", text_render(values["text"][0], self.model.vocabulary).encode("utf-8"))
            reopen(refs)
        except (RuntimeError, ValueError, OSError) as exc:
            failure = {"kind": "actual_codec_or_readback_failure", "type": type(exc).__name__,
                       "message": str(exc)[:300]}
        valid = failure is None
        context = self.video.detach().numpy()
        image = values["image"][0].detach().numpy()
        probabilities = output["text"].detach().softmax(-1)
        entropy = float(-(probabilities * probabilities.clamp_min(1e-12).log()).sum(-1).mean())
        public_features = [*context.mean(axis=(0, 1, 3, 4)), *context.std(axis=(0, 1, 3, 4)),
                           float(np.abs(np.diff(context, axis=1)).mean()), float(self.audio.square().mean().sqrt()),
                           entropy, *image.mean(axis=(1, 2)), float(values["video"].square().mean().sqrt()),
                           float(values["audio"].square().mean().sqrt()), float(valid), 1.0]
        return {"artifact_refs": refs, "artifact_sha256": {k: sha(v) for k, v in refs.items()},
                "terminal_kind": "delivered" if valid else "failed", "public_feedback": 1 if valid else -1,
                "public_features": public_features, "failure": failure, "stochastic": True,
                "final_state_digest": digest({"parameter": self.parameter_sha, "sample": descriptor})}

    def terminal_score(self, final):
        index = self.item["index"]
        delivered = reopen(final["artifact_refs"])
        with np.load(self.assets / "EVENTS.npz") as arrays:
            target = {name: arrays["target_" + name][index].copy() for name in ("image", "video", "audio")}
        target["image"] = target["image"].astype(np.float32) / 255
        target["video"] = target["video"].astype(np.float32) / 255
        return score_bundle(delivered, target, self.item["caption"])
