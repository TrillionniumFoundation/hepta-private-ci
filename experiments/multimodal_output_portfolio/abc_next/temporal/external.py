"""Independent frozen Transformer ASR, restricted to offline measurement.

No intended text, target fact, public source signal, candidate list or grammar is
accepted. No caller in policy.py or the online decision phase has this object.
This establishes separation of observers, not independence of training corpora.
"""

import importlib.metadata
import json
from pathlib import Path
import time

import numpy as np
from faster_whisper import WhisperModel
from scipy.signal import resample_poly

from .speech import read_pcm, sha256


DECODE = {"language": "en", "task": "transcribe", "beam_size": 5, "best_of": 1,
          "temperature": 0.0, "condition_on_previous_text": False, "vad_filter": False,
          "initial_prompt": None, "prefix": None, "hotwords": None,
          "word_timestamps": True, "compression_ratio_threshold": 2.4,
          "log_prob_threshold": -1.0, "no_speech_threshold": 0.6,
          "max_new_tokens": 128}


class ExternalObserver:
    def __init__(self, assets):
        started, cpu = time.perf_counter_ns(), time.process_time_ns()
        assets = Path(assets)
        manifest = json.loads((assets / "manifest.json").read_text())
        for row in manifest["sources"]:
            if sha256(assets / row["path"]) != row["sha256"]:
                raise ValueError("Frozen external ASR asset changed")
        self.model = WhisperModel(str(assets), device="cpu", compute_type="int8",
                                  cpu_threads=1, num_workers=1, local_files_only=True)
        self.load_receipt = {"wall_ns": time.perf_counter_ns() - started,
                             "cpu_ns": time.process_time_ns() - cpu,
                             "manifest_sha256": sha256(assets / "manifest.json"),
                             "decoding": DECODE, "cpu_threads": 1, "compute_type": "int8",
                             "packages": {name: importlib.metadata.version(name) for name in
                                          ("faster-whisper", "ctranslate2", "tokenizers", "av")}}

    def observe(self, path):
        started, cpu = time.perf_counter_ns(), time.process_time_ns()
        rate, pcm = read_pcm(path)
        divisor = np.gcd(rate, 16000)
        audio = resample_poly(pcm.astype(np.float32) / 32768, 16000 // divisor,
                              rate // divisor).astype(np.float32)
        segments, info = self.model.transcribe(audio, **DECODE)
        rows = []
        for segment in segments:
            rows.append({"text": segment.text, "start": segment.start, "end": segment.end,
                         "avg_logprob": segment.avg_logprob,
                         "no_speech_probability": segment.no_speech_prob,
                         "words": [{"word": word.word, "start": word.start, "end": word.end,
                                    "probability": word.probability} for word in segment.words or []]})
        return {"transcript": " ".join(row["text"].strip() for row in rows).strip(),
                "segments": rows, "input_sha256": sha256(path), "input_samples": len(pcm),
                "decoded_duration": info.duration, "observer": "offline_whisper_tiny_en",
                "target_or_prompt_supplied": False,
                "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu}
