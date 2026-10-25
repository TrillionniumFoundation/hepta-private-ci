"""Bounded real neural synthesis and independently decoded WAV observations."""

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import time
import wave

import numpy as np
import onnxruntime as ort
from piper import PiperVoice, SynthesisConfig
from piper.config import PiperConfig
from scipy.signal import resample_poly
from vosk import KaldiRecognizer, Model, SetLogLevel


VOICE = "en_US-ljspeech-medium"
ASR = "vosk-model-small-en-us-0.15"


def sha256(path):
    checksum = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024):
            checksum.update(block)
    return checksum.hexdigest()


def read_pcm(path):
    with wave.open(str(path), "rb") as stream:
        if stream.getnchannels() != 1 or stream.getsampwidth() != 2 or stream.getcomptype() != "NONE":
            raise ValueError("Only actual mono PCM16 WAV is accepted")
        sample_rate, frames = stream.getframerate(), stream.getnframes()
        payload = stream.readframes(frames)
    if len(payload) != 2 * frames or frames == 0:
        raise ValueError("Incomplete or empty WAV")
    return sample_rate, np.frombuffer(payload, dtype="<i2").copy()


def write_pcm(path, sample_rate, samples):
    path = Path(path)
    if path.exists():
        raise FileExistsError(path)
    with path.open("xb") as raw:
        with wave.open(raw, "wb") as stream:
            stream.setparams((1, 2, sample_rate, 0, "NONE", "not compressed"))
            stream.writeframes(np.asarray(samples, dtype="<i2").tobytes())
        raw.flush()
        os.fsync(raw.fileno())
    actual_rate, actual = read_pcm(path)
    if actual_rate != sample_rate or not np.array_equal(actual, samples):
        raise ValueError("Physical WAV readback differs")


class SpeechBackend:
    """Fixed pretrained TTS and fixed independent unrestricted-vocabulary ASR.

    The ASR never receives intended text, task target, candidate facts, a custom
    grammar, or a source identifier. It decodes only the actual WAV samples.
    """

    def __init__(self, assets):
        start, cpu = time.perf_counter_ns(), time.process_time_ns()
        assets = Path(assets)
        manifest = json.loads((assets / "manifest.json").read_text())
        for row in manifest["sources"] + manifest["extracted_vosk_files"]:
            if sha256(assets / row["path"]) != row["sha256"]:
                raise ValueError(f"Public model asset changed: {row['path']}")
        ort.disable_telemetry_events()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        config = PiperConfig.from_dict(json.loads((assets / f"{VOICE}.onnx.json").read_text()))
        session = ort.InferenceSession(str(assets / f"{VOICE}.onnx"), sess_options=options,
                                       providers=["CPUExecutionProvider"])
        self.voice = PiperVoice(session=session, config=config, download_dir=assets)
        SetLogLevel(-1)
        self.observer = Model(str(assets / ASR))
        self.load_receipt = {"wall_ns": time.perf_counter_ns() - start,
                             "cpu_ns": time.process_time_ns() - cpu,
                             "includes": "all asset hashes, CPU neural TTS and independent ASR model loads",
                             "manifest_sha256": sha256(assets / "manifest.json"),
                             "providers": session.get_providers(), "onnx_threads": 1,
                             "packages": {name: importlib.metadata.version(name) for name in
                                          ("piper-tts", "onnxruntime", "vosk", "numpy", "scipy")}}

    def synthesize(self, text, output, length_scale=1.0):
        if not text.strip() or len(text) > 320 or not 0.8 <= length_scale <= 1.5:
            raise ValueError("Text/synthesis control outside declared bounds")
        output = Path(output)
        start, cpu = time.perf_counter_ns(), time.process_time_ns()
        config = SynthesisConfig(length_scale=length_scale, noise_scale=0.0, noise_w_scale=0.0,
                                 normalize_audio=True, volume=0.8)
        with output.open("xb") as raw:
            with wave.open(raw, "wb") as stream:
                self.voice.synthesize_wav(text, stream, syn_config=config)
            raw.flush()
            os.fsync(raw.fileno())
        sample_rate, samples = read_pcm(output)
        if sample_rate != self.voice.config.sample_rate or len(samples) > 30 * sample_rate:
            raise ValueError("Unexpected TTS output clock/length")
        return {"path": str(output), "sha256": sha256(output), "sample_rate": sample_rate,
                "samples": len(samples), "duration_seconds": len(samples) / sample_rate,
                "wall_ns": time.perf_counter_ns() - start, "cpu_ns": time.process_time_ns() - cpu,
                "peak_absolute_pcm": int(np.abs(samples.astype(np.int32)).max()),
                "tts_model_calls": 1, "length_scale": length_scale,
                "noise_scale": 0.0, "noise_w_scale": 0.0}

    def observe(self, path):
        start, cpu = time.perf_counter_ns(), time.process_time_ns()
        sample_rate, samples = read_pcm(path)
        divisor = np.gcd(sample_rate, 16000)
        resampled = resample_poly(samples.astype(np.float64), 16000 // divisor, sample_rate // divisor)
        audio = np.clip(np.rint(resampled), -32768, 32767).astype("<i2")
        decoder = KaldiRecognizer(self.observer, 16000)
        decoder.SetWords(True)
        parts = []
        for offset in range(0, len(audio), 4000):
            if decoder.AcceptWaveform(audio[offset:offset + 4000].tobytes()):
                parts.append(json.loads(decoder.Result()))
        parts.append(json.loads(decoder.FinalResult()))
        words = [word for part in parts for word in part.get("result", [])]
        return {"transcript": " ".join(part.get("text", "") for part in parts).strip(),
                "words": words, "mean_word_confidence": float(np.mean([row["conf"] for row in words])) if words else 0.0,
                "input_sha256": sha256(path), "input_samples": len(samples),
                "asr_samples_16000": len(audio), "custom_grammar": False,
                "wall_ns": time.perf_counter_ns() - start, "cpu_ns": time.process_time_ns() - cpu}
