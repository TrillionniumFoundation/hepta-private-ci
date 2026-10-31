"""Target-free neural speech and ASR worker in the existing speech environment."""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import sys
import time

import numpy as np
from scipy.signal import resample_poly

from ...abc_next.temporal.external import ExternalObserver
from ...abc_next.temporal.speech import SpeechBackend, read_pcm, sha256, write_pcm


WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")


def whisper_digits(text, carrier=False):
    tokens = re.findall(r"[a-z]+|[0-9]+", text.lower())
    result = []
    for token in tokens:
        if token in WORDS:
            result.append(WORDS.index(token))
        elif token.isdigit() and 1 <= len(token) <= 2:
            result.extend(int(value) for value in token)
        elif not carrier:
            return None
    return result if len(result) == 2 else None


def vosk_events(observation, event_seconds=1, carrier=False):
    result = [-1, -1]
    rows = observation["words"]
    if carrier:
        rows = [word for word in rows if word["word"].lower() in WORDS]
    if len(rows) != 2:
        return result
    for word in rows:
        token = word["word"].lower()
        if token not in WORDS:
            return [-1, -1]
        event = int((word["start"] + word["end"]) / (2 * event_seconds))
        if event not in (0, 1) or result[event] != -1 or word["start"] < event * event_seconds - .08 or word["end"] > (event + 1) * event_seconds + .08:
            return [-1, -1]
        result[event] = WORDS.index(token)
    return result


def whisper_events(observation, event_seconds):
    result, count = [-1, -1], 0
    for segment in observation["segments"]:
        for word in segment["words"]:
            tokens = re.findall(r"[a-z]+|[0-9]+", word["word"].lower())
            if len(tokens) != 1:
                continue
            token = tokens[0]
            if token in WORDS:
                digit = WORDS.index(token)
            elif len(token) == 1 and token.isdigit():
                digit = int(token)
            else:
                continue
            count += 1
            event = int((word["start"] + word["end"]) / (2 * event_seconds))
            if event not in (0, 1) or result[event] != -1 or word["start"] < event * event_seconds - .08 or word["end"] > (event + 1) * event_seconds + .08:
                return [-1, -1]
            result[event] = digit
    return result if count == 2 else [-1, -1]


def emit(value):
    print(json.dumps(value, allow_nan=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("assets", "asr-assets", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--profile", type=Path, default=Path(__file__).with_name("waveform_protocol.json"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    backend, external = SpeechBackend(args.assets), ExternalObserver(args.asr_assets)
    configuration = json.loads(args.profile.read_text())
    profile = configuration["synthesis"]
    carrier = "text_pattern" in configuration
    emit({"ok": True, "tts_and_vosk": backend.load_receipt, "whisper": external.load_receipt,
          "worker_source_sha256": sha256(__file__), "profile": profile})
    cache, synthesis_calls, observation_calls, hits = {}, 0, 0, 0
    for line in sys.stdin:
        try:
            request = json.loads(line)
            started, cpu = time.perf_counter_ns(), time.process_time_ns()
            if request["operation"] == "close":
                emit({"ok": True, "synthesis_calls": synthesis_calls, "observations": observation_calls, "audit_cache_hits": hits})
                return
            if request["operation"] == "synthesize":
                probabilities = np.asarray(request["probabilities"], dtype=np.float64)
                if (probabilities.shape != (2, 10) or not np.isfinite(probabilities).all()
                        or (probabilities < 0).any() or not np.allclose(probabilities.sum(-1), 1, atol=1e-5)):
                    raise ValueError("Neural voice requires two predicted probability simplexes")
                directory = Path(request["output_directory"])
                directory.mkdir(parents=True, exist_ok=False)
                signals, records = [], []
                for event, digit in enumerate(probabilities.argmax(-1).tolist()):
                    raw_path = directory / f"neural-event-{event}.wav"
                    text = configuration.get("text_pattern", "{word}").format(word=WORDS[digit])
                    receipt = backend.synthesize(text, raw_path, length_scale=profile["length_scale"])
                    synthesis_calls += 1
                    rate, pcm = read_pcm(raw_path)
                    value = resample_poly(pcm.astype(np.float64) / 32768, 160, 441).astype(np.float32)
                    if rate != 22050:
                        raise ValueError("Pinned neural voice sample rate changed")
                    if profile.get("trim_mode") != "none":
                        active = np.flatnonzero(np.abs(value) >= max(1e-5, profile["trim_relative_threshold"] * np.max(np.abs(value))))
                        if not len(active):
                            raise ValueError("Neural voice returned silence")
                        left = max(0, int(active[0]) - profile["silence_margin_samples"])
                        right = min(len(value), int(active[-1]) + profile["silence_margin_samples"] + 1)
                        value = value[left:right]
                    original_length = len(value)
                    if len(value) > profile["max_word_samples"]:
                        value = np.interp(np.linspace(0, len(value) - 1, profile["max_word_samples"]), np.arange(len(value)), value).astype(np.float32)
                    value = np.pad(value, (0, profile["word_samples"] - len(value)))
                    signals.append(value)
                    records.append({"predicted_digit": digit, "neural_receipt": receipt,
                                    "trimmed_samples": original_length, "duration_compressed": original_length > profile["max_word_samples"]})
                payload = np.stack(signals).astype("<f4").tobytes()
                emit({"ok": True, "waveform_base64": base64.b64encode(payload).decode(), "events": records,
                      "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu})
            elif request["operation"] == "observe":
                pcm = base64.b64decode(request["pcm16_base64"], validate=True)
                if len(pcm) != 4 * profile["word_samples"]:
                    raise ValueError("Independent ASR requires the complete registered actual PCM16 duration")
                digest = hashlib.sha256(pcm).hexdigest()
                if digest in cache:
                    hits += 1
                    emit({"ok": True, **cache[digest], "cache_hit": True})
                    continue
                path = args.output / ("observed-" + digest + ".wav")
                write_pcm(path, 8000, np.frombuffer(pcm, dtype="<i2"))
                vosk, whisper = backend.observe(path), external.observe(path)
                events = vosk_events(vosk, profile["word_samples"] / 8000, carrier)
                transcript_digits = whisper_digits(whisper["transcript"], carrier)
                consensus = events if events == transcript_digits else [-1, -1]
                primary_events = whisper_events(whisper, profile["word_samples"] / 8000)
                predictions = primary_events if configuration.get("primary_asr") == "whisper_event" else consensus
                observation_calls += 1
                record = {"predictions": predictions, "vosk_event_digits": events,
                          "whisper_event_digits": primary_events, "consensus_digits": consensus,
                          "whisper_digits": transcript_digits, "vosk": vosk, "whisper": whisper,
                          "actual_pcm_sha256": digest, "target_supplied": False,
                          "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu}
                cache[digest] = record
                emit({"ok": True, **record, "cache_hit": False})
            else:
                raise ValueError("Unknown waveform worker operation")
        except Exception as error:
            emit({"ok": False, "error": repr(error)})


if __name__ == "__main__":
    main()
