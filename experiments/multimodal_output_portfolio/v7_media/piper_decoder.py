"""Pinned local neural TTS adapter for predicted semantic digit slots.

The semantic argmax is a declared discrete bottleneck. Every invocation runs
the neural ONNX decoder; no prerecorded waveforms or target labels are read.
The VAE negative controls remain available in the separate backend.
"""

import hashlib
import importlib.metadata
import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import time

import numpy as np
from scipy.signal import resample_poly
import torch

from .models import validate_probabilities


MODEL_SHA256 = "9127a559e11603f10b366d1a20ac7426826081dbc521de4c2420c57728d73f0f"
REVISION = "2525f22960f62209936f0ae3cce3ffe7b2c18f1f"
WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
PROFILE = {"schema": "hepta.ndu.piper-semantic-decoder.v1", "speaker_id": 0,
           "length_scale": .8, "noise_scale": 0., "noise_w_scale": 0.,
           "volume": .9, "normalize_audio": True, "trim_relative_threshold": .01,
           "silence_margin_samples": 160, "max_word_samples": 7680,
           "output_sample_rate": 8000, "word_samples": 8000,
           "semantic_token_selection": "argmax_first_index", "threads": 2}


class PiperSemanticDecoder:
    def __init__(self, manifest_path, manifest_sha256):
        import onnxruntime
        onnxruntime.disable_telemetry_events()
        from piper import PiperVoice, SynthesisConfig
        from piper.config import PiperConfig
        from piper.voice import ESPEAK_DATA_DIR

        started = time.perf_counter_ns()
        path = Path(manifest_path)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
            raise ValueError("Invalid bounded neural voice manifest")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest_sha256:
            raise ValueError("Caller did not bind the neural voice manifest")
        manifest = json.loads(raw)
        if manifest["model"] != "en_US-libritts-high" or manifest["revision"] != REVISION:
            raise ValueError("Unregistered neural voice identity")
        expected_names = {"MODEL_CARD", "en_US-libritts-high.onnx.json", "en_US-libritts-high.onnx"}
        if len(manifest["files"]) != 3 or {item["path"] for item in manifest["files"]} != expected_names:
            raise ValueError("Neural voice manifest census mismatch")
        self.pins = {}
        for entry in manifest["files"]:
            source = path.parent / entry["path"]
            if source.is_symlink() or not source.is_file() or source.stat().st_size > 140_000_000:
                raise ValueError("Neural voice source bound")
            content = source.read_bytes()
            if hashlib.sha256(content).hexdigest() != entry["sha256"] or len(content) != entry["bytes"]:
                raise ValueError("Neural voice source changed")
            self.pins[entry["path"]] = {"sha256": entry["sha256"], "bytes": entry["bytes"]}
        if self.pins["en_US-libritts-high.onnx"]["sha256"] != MODEL_SHA256:
            raise ValueError("Neural voice differs from the independently recorded LFS SHA")
        if importlib.metadata.version("piper-tts") != "1.8.0":
            raise ValueError("Neural voice runtime version changed")
        config = PiperConfig.from_dict(json.loads((path.parent / "en_US-libritts-high.onnx.json").read_text()))
        if config.sample_rate != 22050 or config.num_speakers != 904:
            raise ValueError("Unexpected public voice configuration")
        session_options = onnxruntime.SessionOptions()
        session_options.intra_op_num_threads = PROFILE["threads"]
        session_options.inter_op_num_threads = 1
        session_options.enable_cpu_mem_arena = False
        self.voice = PiperVoice(config=config, session=onnxruntime.InferenceSession(
            str(path.parent / "en_US-libritts-high.onnx"), sess_options=session_options,
            providers=["CPUExecutionProvider"]), espeak_data_dir=Path(ESPEAK_DATA_DIR),
            download_dir=path.parent)
        self.config = SynthesisConfig(**{name: PROFILE[name] for name in
            ("speaker_id", "length_scale", "noise_scale", "noise_w_scale", "volume", "normalize_audio")})
        self.pins["profile"] = {"sha256": hashlib.sha256(json.dumps(PROFILE, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
        self.pins["runtime"] = {"piper": importlib.metadata.version("piper-tts"),
                                "onnxruntime": importlib.metadata.version("onnxruntime")}
        self._manifest_path = path
        self._manifest_sha256 = manifest_sha256
        self._files = deepcopy(manifest["files"])
        self._synthesis_config = deepcopy(self.config)
        self._voice_config = deepcopy(asdict(self.voice.config))
        self._session = self.voice.session
        self._pins = deepcopy(self.pins)
        self._profile = deepcopy(PROFILE)
        self.load_wall_ns = time.perf_counter_ns() - started
        self.last_metadata = []

    def verify_integrity(self):
        if (self.config != self._synthesis_config or asdict(self.voice.config) != self._voice_config
                or self.voice.session is not self._session or PROFILE != self._profile
                or self.voice.session.get_providers() != ["CPUExecutionProvider"] or self.pins != self._pins
                or importlib.metadata.version("piper-tts") != self._pins["runtime"]["piper"]
                or importlib.metadata.version("onnxruntime") != self._pins["runtime"]["onnxruntime"]):
            raise RuntimeError("Frozen neural voice configuration/runtime changed")
        if hashlib.sha256(self._manifest_path.read_bytes()).hexdigest() != self._manifest_sha256:
            raise RuntimeError("Frozen neural voice manifest changed")
        for entry in self._files:
            if hashlib.sha256((self._manifest_path.parent / entry["path"]).read_bytes()).hexdigest() != entry["sha256"]:
                raise RuntimeError("Frozen neural voice dependency changed")
        return self._manifest_sha256

    def waveform(self, probabilities, seed=None):
        validate_probabilities(probabilities)
        if not 1 <= len(probabilities) <= 128:
            raise ValueError("Bounded semantic voice batch")
        waveforms, metadata = [], []
        for digit in probabilities.argmax(-1).detach().cpu().tolist():
            started = time.perf_counter_ns()
            chunks = list(self.voice.synthesize(WORDS[digit], syn_config=self.config))
            if len(chunks) != 1 or chunks[0].sample_rate != 22050:
                raise ValueError("Expected one actual neural speech chunk")
            original = chunks[0].audio_float_array
            if not 1 <= len(original) <= 10 * 22050 or not np.isfinite(original).all():
                raise ValueError("Invalid raw neural waveform")
            value = resample_poly(original, 160, 441).astype(np.float32)
            active = np.flatnonzero(np.abs(value) >= max(1e-5, PROFILE["trim_relative_threshold"] * np.max(np.abs(value))))
            if not len(active):
                raise ValueError("Neural decoder returned silence")
            left = max(0, int(active[0]) - 160)
            right = min(len(value), int(active[-1]) + 161)
            value = value[left:right]
            before = len(value)
            compressed = before > PROFILE["max_word_samples"]
            if compressed:
                value = np.interp(np.linspace(0, before - 1, PROFILE["max_word_samples"]),
                                  np.arange(before), value).astype(np.float32)
            value = np.pad(value, (0, 8000 - len(value)))
            peak = float(np.max(np.abs(value)))
            if peak > 1:
                value = .9 * value / peak
            waveforms.append(torch.from_numpy(value.copy()))
            metadata.append({"predicted_token": digit, "phonemes": chunks[0].phonemes,
                             "raw_samples": len(original), "trimmed_samples": before,
                             "duration_compressed": compressed, "wall_ns": time.perf_counter_ns() - started,
                             "raw_float_sha256": hashlib.sha256(original.tobytes()).hexdigest()})
        self.last_metadata = metadata
        return torch.stack(waveforms)
