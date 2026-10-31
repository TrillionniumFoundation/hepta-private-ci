"""Four-modality offline labels with explicit deterministic acoustic memoization.

Actual neural speech PCM was exhaustively generated and independently audited
for every token of this frozen voice. Offline endpoint collection may reuse
that exact function table. Native inference always executes the ONNX decoder.
Video pixels are generated for every state and quantized; this endpoint does
not claim to execute codec containers or incur native inference's full cost.
"""

import hashlib
import json
from pathlib import Path
import time
import wave

import numpy as np
import torch

from ..v6.data import render_tokens
from ..v6.neural import parameter_hash
from ..v6.observer import CAPTION
from ..v6.plan_training import _png_roundtrip
from ..v7.metric import EndpointLabeler, MetricContract
from ..v7.sources import digest
from .audit import observable_media_features
from .media import file_pin
from .models import weights_sha256
from .motion import ConditionedMotionDecoder
from .pcm_audit import FrozenPcmAudit


METRIC = {"schema": "hepta.ndu.four-modal-strict-metric.v1", "required_mask": 15,
          "modalities": ["text", "image", "audio", "video"],
          "text_success": "both target digits and their ordered relation, exact decoded grammar",
          "image_success": "both raw PNG panels independently recognized as target digits",
          "audio_success": "both actual quantized PCM events independently recognized as target digits",
          "video_success": "all twenty quantized frames recognized in their required event order",
          "loss": ".5*(not joint_success)+.125*number_of_failed_modalities",
          "utility": "1-2*loss", "unknown_audio_bytes": "failure",
          "missing_input_views": "remain in full census; no success credit for information insufficiency",
          "verification": "quantized_media_payloads", "cost": "offline memoized audio; not actual runtime cost"}


class FiniteAcousticRollout:
    """Exact frozen generator table keyed by requested token, not audit truth."""

    def __init__(self, pcm_audit):
        self.audit = pcm_audit
        self.waveforms = {}
        self.evidence_pins = []
        for evidence in pcm_audit.record["evidence"]:
            pin = evidence["row"]
            if file_pin(pin["path"])["sha256"] != pin["sha256"]:
                raise ValueError("Finite acoustic source record changed")
            row = json.loads(Path(pin["path"]).read_text())
            audio_pin = row["output"]["files"]["audio"]
            if file_pin(audio_pin["path"])["sha256"] != audio_pin["sha256"]:
                raise ValueError("Finite acoustic source PCM changed")
            with wave.open(audio_pin["path"], "rb") as source:
                if (source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getnframes()) != (1, 2, 8000, 16000):
                    raise ValueError("Finite acoustic source clock mismatch")
                raw = source.readframes(16000)
            for slot, event in enumerate(row["output"]["audio_decoding"]):
                requested = event["predicted_token"]
                probabilities = row["output"]["semantic_probabilities"][0][slot]
                if requested != int(np.argmax(probabilities)):
                    raise ValueError("Acoustic table request binding mismatch")
                pcm = raw[16000 * slot:16000 * (slot + 1)]
                if requested in self.waveforms and self.waveforms[requested] != pcm:
                    raise ValueError("Acoustic profile was not a deterministic function")
                self.waveforms[requested] = pcm
            self.evidence_pins.extend((pin, audio_pin))
        if set(self.waveforms) != set(range(10)):
            raise ValueError("Acoustic function was not exhaustively observed")
        self.function_sha256 = digest({token: hashlib.sha256(pcm).hexdigest() for token, pcm in self.waveforms.items()})

    def verify_integrity(self):
        self.audit.verify_integrity()
        current = digest({token: hashlib.sha256(pcm).hexdigest() for token, pcm in self.waveforms.items()})
        if current != self.function_sha256:
            raise RuntimeError("Frozen finite acoustic function changed")

    def generate_pcm16(self, probabilities):
        return [b"".join(self.waveforms[token] for token in pair)
                for pair in probabilities.argmax(-1).detach().cpu().tolist()]


def four_modal_labeler(pixel_observer, *, observer_file_sha256, motion_path,
                      motion_file_sha256, pcm_audit_path, pcm_audit_sha256):
    observer_hash = parameter_hash(pixel_observer)
    if file_pin(motion_path)["sha256"] != motion_file_sha256:
        raise ValueError("Caller did not pin the temporal model")
    record = torch.load(motion_path, map_location="cpu", weights_only=True)
    motion = ConditionedMotionDecoder()
    motion.load_state_dict(record["state_dict"], strict=True)
    motion.eval().requires_grad_(False)
    motion_hash = weights_sha256(motion)
    if motion_hash != record["weights_sha256"]:
        raise ValueError("Temporal parameter identity changed")
    speech = FrozenPcmAudit(pcm_audit_path, pcm_audit_sha256)
    acoustic = FiniteAcousticRollout(speech)
    contract = MetricContract("strict_digit_pair_four_modal", 15, 15, -1., 1., digest(METRIC),
        (("observer_parameters", observer_hash), ("observer_file", observer_file_sha256),
         ("motion_parameters", motion_hash), ("motion_file", motion_file_sha256),
         ("pcm_audit", pcm_audit_sha256), ("acoustic_function", acoustic.function_sha256),
         ("acoustic_manifest", speech.record["voice"]["sha256"]),
         ("endpoint_implementation", file_pin(__file__)["sha256"])), "quantized_media_payloads")

    def integrity():
        if (pixel_observer.training or any(parameter.requires_grad for parameter in pixel_observer.parameters())
                or parameter_hash(pixel_observer) != observer_hash or motion.training
                or any(parameter.requires_grad for parameter in motion.parameters()) or weights_sha256(motion) != motion_hash):
            raise RuntimeError("Frozen four-modal endpoint producer changed")
        acoustic.verify_integrity()

    @torch.inference_mode()
    def callback(snapshot, state, target):
        started = time.perf_counter_ns()
        generated = snapshot.decode(state)
        unquantized = generated.image_logits.sigmoid()
        pixels, png_sha = _png_roundtrip(unquantized)
        probabilities = snapshot.semantic_probabilities(state)
        audio_pcm = acoustic.generate_pcm16(probabilities)
        # Batch size is an execution detail; each real state produces its own
        # frame tensor. Native inference uses the same batch-one motion path.
        clips = torch.cat([motion(probabilities[i:i + 1], unquantized[i:i + 1]).sigmoid()
                           for i in range(len(probabilities))])
        frame_bytes = (clips * 255).round().to(torch.uint8)
        panels = torch.stack((pixels[:, :, :, :28], pixels[:, :, :, 28:]), dim=1)
        image_predictions = pixel_observer(panels.flatten(0, 1)).argmax(-1).reshape(-1, 2)
        video_predictions = pixel_observer(frame_bytes.flatten(0, 1).float() / 255).argmax(-1).reshape(-1, 20)
        captions = [render_tokens(tokens) for tokens in generated.token_ids]
        rows = []
        for index, (pcm, text) in enumerate(zip(audio_pcm, captions)):
            expected = target.labels[index].tolist()
            audio_digits = speech.predict_pcm16(pcm)
            image_digits = image_predictions[index].tolist()
            video_digits = video_predictions[index].tolist()
            caption = CAPTION.fullmatch(text.strip())
            relation = "less" if expected[0] < expected[1] else "greater" if expected[0] > expected[1] else "equal"
            success = {"text": bool(caption and [int(caption[1]), int(caption[2])] == expected and caption[3] == relation),
                       "image": image_digits == expected, "audio": audio_digits == expected,
                       "video": video_digits == np.repeat(expected, 10).tolist()}
            joint = all(success.values())
            loss = .5 * (not joint) + .125 * sum(not value for value in success.values())
            rgb = np.repeat(frame_bytes[index, :, 0].numpy()[..., None], 3, axis=-1).tobytes()
            raw = {"caption": text, "audio_bytes": pcm, "video_bytes": rgb}
            rows.append({"utility": 1 - 2 * loss, "joint_loss": loss, "joint_success": joint,
                "success": success, "strict_completion": True,
                "raw_sha256": {"image": png_sha[index], "text": hashlib.sha256(text.encode()).hexdigest(),
                               "audio_pcm16": hashlib.sha256(pcm).hexdigest(), "video_rgb24": hashlib.sha256(rgb).hexdigest()},
                "observed_digits": {"image": image_digits, "audio": audio_digits, "video": video_digits},
                "observable_features": observable_media_features(raw),
                "offline_cost": {"acoustic_memoized_events": 2, "video_frames": 20,
                                 "codec_containers_executed": False}})
        elapsed = time.perf_counter_ns() - started
        for row in rows:
            row["offline_batch_wall_ns"] = elapsed
        return rows

    return EndpointLabeler(contract, callback, integrity)
