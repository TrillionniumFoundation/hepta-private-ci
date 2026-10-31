"""Observe each publicly clocked audio event without intended text or targets."""

import hashlib
from pathlib import Path
import re
import time

import numpy as np
from scipy.signal import resample_poly

from ...abc_next.temporal.external import DECODE, ExternalObserver
from ...abc_next.temporal.speech import write_pcm
from .observers import WORDS


RECIPE = {"schema": "hepta.next.event-asr.recipe.v1", "sample_rate": 8000,
          "padding_each_side_samples": 1600, "primary": "small.en",
          "secondary": "base.en", "max_new_tokens": 16,
          "word_timestamps": False, "target_or_prompt_supplied": False,
          "parse": "Exactly one digit per independently observed physical event; no lexical repairs",
          "event_boundaries": "Declared PCM presentation clock; never inferred from ground truth or ASR word times"}


def parse_event(transcript, carrier):
    digits = []
    for token in re.findall(r"[a-z]+|[0-9]+", transcript.lower()):
        if token in WORDS:
            digits.append(WORDS.index(token))
        elif len(token) == 1 and token.isdigit():
            digits.append(int(token))
        elif carrier and token in {"the", "digit", "is"}:
            continue
        else:
            return None
    return digits[0] if len(digits) == 1 else None


class EventWaveAudit:
    """Actual-event content cache preserves the order of two independently read events."""

    def __init__(self, assets, output, model_names=("small.en", "base.en")):
        if not model_names or any(name not in ("small.en", "base.en") for name in model_names):
            raise ValueError("Only preregistered frozen ASR identities are available")
        self.models = {name: ExternalObserver(Path(assets) / ("whisper-" + name)) for name in model_names}
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=False)
        self.receipt = {"recipe": RECIPE, "models": {name: model.load_receipt for name, model in self.models.items()}}
        self.cache, self.calls, self.hits = {}, 0, 0

    def observe_event(self, pcm, carrier):
        started = time.perf_counter_ns()
        if len(pcm) not in (16000, 32000):
            raise ValueError("Event must contain one or two seconds of actual PCM16 at 8 kHz")
        digest = hashlib.sha256(pcm).hexdigest()
        key = (digest, carrier)
        if key in self.cache:
            self.hits += 1
            return {**self.cache[key], "cache_hit": True, "request_wall_ns": time.perf_counter_ns() - started}
        path = self.output / (digest + ".wav")
        signal = np.frombuffer(pcm, dtype="<i2")
        if not path.exists():
            write_pcm(path, 8000, signal)
        padded = np.pad(signal.astype(np.float32) / 32768, (1600, 1600))
        actual = resample_poly(padded, 2, 1).astype(np.float32)
        decoding = {**DECODE, "word_timestamps": False, "max_new_tokens": 16}
        observations = {}
        for name, observer in self.models.items():
            wall, cpu = time.perf_counter_ns(), time.process_time_ns()
            segments, info = observer.model.transcribe(actual, **decoding)
            rows = [{"text": segment.text, "start": segment.start, "end": segment.end,
                     "avg_logprob": segment.avg_logprob, "no_speech_probability": segment.no_speech_prob}
                    for segment in segments]
            transcript = " ".join(row["text"].strip() for row in rows).strip()
            observations[name] = {"transcript": transcript, "segments": rows,
                                  "prediction": parse_event(transcript, carrier),
                                  "wall_ns": time.perf_counter_ns() - wall,
                                  "cpu_ns": time.process_time_ns() - cpu}
        self.calls += 1
        row = {"actual_event_pcm_sha256": digest, "actual_event_samples": len(signal),
               "observations": observations,
               "predictions": {name: value["prediction"] for name, value in observations.items()},
               "target_supplied": False}
        self.cache[key] = row
        return {**row, "cache_hit": False, "request_wall_ns": time.perf_counter_ns() - started}

    def observe_pcm(self, pcm, carrier=True):
        if len(pcm) != 64000:
            raise ValueError("Four-second output clock requires 32000 complete PCM16 samples")
        events = [self.observe_event(pcm[start:start + 32000], carrier) for start in (0, 32000)]
        return {"events": events,
                "predictions": {name: [row["predictions"].get(name) for row in events]
                                if name in self.models else None for name in ("small.en", "base.en")},
                "target_supplied": False, "clock_boundaries_samples": [0, 16000, 32000],
                "cache_hit": all(row["cache_hit"] for row in events),
                "request_wall_ns": sum(row["request_wall_ns"] for row in events),
                "observer_family_independence_claimed": False}
