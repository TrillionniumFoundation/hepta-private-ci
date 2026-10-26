"""Reuse only measured ASR observations of byte-identical actual waveform events."""

import copy
import hashlib
import json
from pathlib import Path
import time
import wave

from ....closure_20261025.media.sources import sha
from ..ensemble_event import PRIMARY, SECONDARIES, RULE, ensemble_digit


class CachedFrozenAudit:
    """This is a verified observation cache, never a substitute for unseen ASR."""

    def __init__(self, assets, output, manifest):
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=False)
        self.manifest = Path(manifest)
        self.manifest_sha256 = sha(self.manifest)
        record = json.loads(self.manifest.read_text())
        for path, expected in record["frozen_source_sha256"].items():
            if sha(path) != expected:
                raise ValueError("Measured observation cache provenance changed")
        for name in SECONDARIES:
            path = Path(assets) / ("whisper-" + name) / "manifest.json"
            if sha(path) != record["component_manifest_sha256"][name]:
                raise ValueError("Cache belongs to different ASR models")
            for item in json.loads(path.read_text())["sources"]:
                if sha(path.parent / item["path"]) != item["sha256"]:
                    raise ValueError("Actual frozen ASR model bytes differ")
        self.cache = {}
        for entry in record["events"]:
            path = Path(entry["actual_wave_file"])
            if sha(path) != entry["actual_wave_file_sha256"]:
                raise ValueError("Original measured audio event file changed")
            with wave.open(str(path), "rb") as audio:
                if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) != (8000, 1, 2):
                    raise ValueError("Original event PCM format changed")
                pcm = audio.readframes(audio.getnframes())
            observed = entry["target_free_observation"]
            if hashlib.sha256(pcm).hexdigest() != observed["actual_event_pcm_sha256"]:
                raise ValueError("Original measured event bytes changed")
            self.cache[(observed["actual_event_pcm_sha256"], entry["carrier"])] = observed
        self.calls, self.hits = 0, 0
        self.receipt = {"schema": "hepta.next.verified-event-cache.v1", "primary": PRIMARY,
                        "secondary_observers": SECONDARIES, "ensemble_rule": RULE,
                        "cache_manifest_sha256": self.manifest_sha256,
                        "models": record["component_model_receipts"],
                        "measured_unique_events": len(self.cache),
                        "new_asr_inference_calls": 0,
                        "provenance": "Completed V2 development ASR; actual neural outputs are generated and decoded anew",
                        "cold_asr_process_receipt": record["original_process_receipt"],
                        "unknown_event_behavior": "Reject: no fabricated observation or label lookup"}

    def observe_event(self, pcm, carrier):
        started = time.perf_counter_ns()
        key = (hashlib.sha256(pcm).hexdigest(), carrier)
        if key not in self.cache:
            raise ValueError("Actual event is absent from the frozen measured ASR cache")
        raw = copy.deepcopy(self.cache[key])
        self.hits += 1
        return {**raw, "predictions": {**raw["predictions"], PRIMARY: ensemble_digit(raw["predictions"])},
                "cache_hit": True, "cache_manifest_sha256": self.manifest_sha256,
                "historical_asr_wall_ns": sum(row["wall_ns"] for row in raw["observations"].values()),
                "request_wall_ns": time.perf_counter_ns() - started,
                "primary_observer": PRIMARY, "target_supplied": False}

    def observe_pcm(self, pcm, carrier=True):
        if len(pcm) != 64000:
            raise ValueError("Require the actual four-second two-event PCM clock")
        events = [self.observe_event(pcm[start:start + 32000], carrier) for start in (0, 32000)]
        return {"events": events,
                "predictions": {name: [row["predictions"][name] for row in events]
                                for name in (*SECONDARIES, PRIMARY)},
                "target_supplied": False, "clock_boundaries_samples": [0, 16000, 32000],
                "cache_hit": True, "primary_observer": PRIMARY,
                "secondary_observers": SECONDARIES, "ensemble_rule": RULE,
                "request_wall_ns": sum(row["request_wall_ns"] for row in events),
                "observer_family_independence_claimed": False}
