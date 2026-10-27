"""Actual Whisper generation with an explicit reusable encoder result."""
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.audio import decode_audio, pad_or_trim
from faster_whisper.tokenizer import Tokenizer
from faster_whisper.transcribe import get_suppressed_tokens

from .common import save


class SpeechEngine:
    """Frozen neural encoder/decoder; inference never receives target transcripts."""

    def __init__(self, model_path, threads):
        self.model = WhisperModel(str(model_path), device="cpu", compute_type="int8",
            cpu_threads=threads, num_workers=1, local_files_only=True)
        self.tokenizer = Tokenizer(self.model.hf_tokenizer, self.model.model.is_multilingual,
            task="transcribe", language="en")
        self.prompt = self.model.get_prompt(self.tokenizer, previous_tokens=[], without_timestamps=True)
        self.suppress = get_suppressed_tokens(self.tokenizer, [-1])

    def prepare(self, audio_path):
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        audio = decode_audio(str(audio_path), sampling_rate=16000)
        if len(audio) > 29 * 16000:
            raise ValueError("Only frozen single-window public-duration input is permitted")
        features = pad_or_trim(self.model.feature_extractor(audio)[..., :3000])
        encoded = self.model.encode(features)
        array = np.asarray(encoded)
        record = {"audio_samples": len(audio), "feature_shape": list(features.shape),
            "encoded_shape": list(array.shape), "encoded_bytes": int(array.nbytes),
            "encoded_sha256": hashlib.sha256(array.tobytes()).hexdigest(),
            "wall_seconds": (time.perf_counter_ns() - wall) / 1e9,
            "cpu_seconds": (time.process_time_ns() - cpu) / 1e9}
        return encoded, record

    def generate(self, encoded, beam, destination):
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        result = self.model.model.generate(encoded, [self.prompt], beam_size=beam, patience=1,
            length_penalty=1, repetition_penalty=1, no_repeat_ngram_size=0, max_length=448,
            suppress_blank=True, suppress_tokens=self.suppress, return_scores=True,
            return_no_speech_prob=True, sampling_temperature=0)[0]
        tokens = result.sequences_ids[0]
        transcript = self.tokenizer.decode(tokens).strip()
        confidence = float(result.scores[0] * len(tokens) / (len(tokens) + 1))
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(transcript + "\n", encoding="utf-8")
        readback = destination.read_text(encoding="utf-8").strip()
        if transcript != readback:
            raise ValueError("Actual neural transcript did not survive delivery readback")
        public = {"transcript": readback, "tokens": tokens, "beam": beam,
            "confidence": confidence, "score": float(result.scores[0]),
            "no_speech_probability": float(result.no_speech_prob),
            "output_path": str(destination), "private_reference_received": False}
        save(destination.with_suffix(".json"), public)
        return {**public, "wall_seconds": (time.perf_counter_ns() - wall) / 1e9,
            "cpu_seconds": (time.process_time_ns() - cpu) / 1e9}

    def episode(self, audio_path, arm, threshold, output):
        output.mkdir(parents=True, exist_ok=False)
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        encoded, first_encoding = self.prepare(audio_path)
        encodings = [first_encoding]
        first = self.generate(encoded, 5 if arm == "fixed_beam5" else 1, output / "FIRST.txt")
        generations = [first]
        gate_wall, gate_cpu = time.perf_counter_ns(), time.process_time_ns()
        proceed = arm in {"cached_continuation", "reencoded_continuation"} and first["confidence"] < threshold
        gate = {"continue": proceed, "threshold": threshold, "observed_confidence": first["confidence"],
            "wall_seconds": (time.perf_counter_ns() - gate_wall) / 1e9,
            "cpu_seconds": (time.process_time_ns() - gate_cpu) / 1e9}
        if proceed:
            if arm == "reencoded_continuation":
                encoded, second_encoding = self.prepare(audio_path)
                if second_encoding["encoded_sha256"] != first_encoding["encoded_sha256"]:
                    raise ValueError("Re-encoding changed the frozen encoder result")
                encodings.append(second_encoding)
            generations.append(self.generate(encoded, 5, output / "CONTINUED.txt"))
        delivered = output / "DELIVERED.txt"
        delivered.write_text(generations[-1]["transcript"] + "\n", encoding="utf-8")
        text = delivered.read_text(encoding="utf-8").strip()
        public = {"arm": arm, "transcript": text, "encodings": encodings, "generations": generations,
            "gate": gate, "encoder_calls": len(encodings), "decoder_calls": len(generations),
            "encoded_bytes": first_encoding["encoded_bytes"], "output_path": str(delivered),
            "output_sha256": hashlib.sha256(delivered.read_bytes()).hexdigest(),
            "private_reference_received": False, "delivered_before_private_scoring_ns": time.time_ns()}
        save(output / "PUBLIC_RESULT.json", public)
        if json.loads((output / "PUBLIC_RESULT.json").read_text())["transcript"] != text:
            raise ValueError("Public receipt readback differs")
        return {**public, "whole_wall_seconds": (time.perf_counter_ns() - wall) / 1e9,
            "whole_cpu_seconds": (time.process_time_ns() - cpu) / 1e9}
