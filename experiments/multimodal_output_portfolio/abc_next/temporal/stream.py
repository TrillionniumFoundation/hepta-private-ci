"""Append-only text/PCM commits and lossless final WAV evidence."""

import hashlib
import json
import os
from pathlib import Path

import numpy as np

from .facts import canonical
from .speech import read_pcm, sha256, write_pcm


class AppendOnlyOutput:
    def __init__(self, directory, sample_rate):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.sample_rate = int(sample_rate)
        self.pcm = (self.directory / "committed.pcm.part").open("xb")
        self.text = (self.directory / "output.txt").open("xb")
        self.ledger = (self.directory / "commits.jsonl").open("xb")
        self.rows = []
        self.audio_samples, self.text_bytes = 0, 0
        self.previous = "0" * 64
        self.closed = False

    def append(self, text, wav_path, phase):
        if self.closed:
            raise RuntimeError("Cannot change an already closed output")
        sample_rate, samples = read_pcm(wav_path)
        if sample_rate != self.sample_rate or not text.strip():
            raise ValueError("Output clock/text differs from declared stream")
        text_payload = (text + "\n").encode()
        pcm_payload = samples.astype("<i2").tobytes()
        self.pcm.write(pcm_payload)
        self.text.write(text_payload)
        for stream in (self.pcm, self.text):
            stream.flush()
            os.fsync(stream.fileno())
        row = {"index": len(self.rows), "phase": phase, "previous_sha256": self.previous,
               "sample_start": self.audio_samples, "sample_stop": self.audio_samples + len(samples),
               "text_start": self.text_bytes, "text_stop": self.text_bytes + len(text_payload),
               "pcm_sha256": hashlib.sha256(pcm_payload).hexdigest(),
               "text_sha256": hashlib.sha256(text_payload).hexdigest(), "source_wav_sha256": sha256(wav_path)}
        self.previous = hashlib.sha256(canonical(row)).hexdigest()
        row["record_sha256"] = self.previous
        self.ledger.write(canonical(row) + b"\n")
        self.ledger.flush()
        os.fsync(self.ledger.fileno())
        self.rows.append(row)
        self.audio_samples += len(samples)
        self.text_bytes += len(text_payload)

    def finish(self):
        if self.closed:
            raise RuntimeError("Output was already finalized")
        for stream in (self.pcm, self.text, self.ledger):
            stream.close()
        self.closed = True
        pcm_path = self.directory / "committed.pcm.part"
        samples = np.frombuffer(pcm_path.read_bytes(), dtype="<i2")
        write_pcm(self.directory / "output.wav", self.sample_rate, samples)
        result = verify_output(self.directory)
        if result["commit_count"] != len(self.rows) or result["last_record_sha256"] != self.previous:
            raise ValueError("Final stream differs from actual commit chain")
        # Remove the duplicate raw spool only after exact WAV/span verification.
        pcm_path.unlink()
        return result


def verify_output(directory):
    directory = Path(directory)
    sample_rate, samples = read_pcm(directory / "output.wav")
    pcm, text = samples.astype("<i2").tobytes(), (directory / "output.txt").read_bytes()
    rows = [json.loads(line) for line in (directory / "commits.jsonl").read_text().splitlines()]
    previous, audio_offset, text_offset = "0" * 64, 0, 0
    if not rows:
        raise ValueError("No output commits")
    for index, original in enumerate(rows):
        row = dict(original)
        identity = row.pop("record_sha256")
        if identity != hashlib.sha256(canonical(row)).hexdigest() or row["previous_sha256"] != previous:
            raise ValueError("Output commit chain changed")
        if row["index"] != index or row["sample_start"] != audio_offset or row["text_start"] != text_offset:
            raise ValueError("Noncontiguous output commit")
        audio_part = pcm[2 * row["sample_start"]:2 * row["sample_stop"]]
        text_part = text[row["text_start"]:row["text_stop"]]
        if (hashlib.sha256(audio_part).hexdigest() != row["pcm_sha256"] or
                hashlib.sha256(text_part).hexdigest() != row["text_sha256"]):
            raise ValueError("Already committed text/audio changed")
        previous, audio_offset, text_offset = identity, row["sample_stop"], row["text_stop"]
    if 2 * audio_offset != len(pcm) or text_offset != len(text):
        raise ValueError("Unaccounted final output bytes")
    return {"sample_rate": sample_rate, "samples": len(samples), "text_bytes": len(text),
            "commit_count": len(rows), "last_record_sha256": previous,
            "wave_sha256": sha256(directory / "output.wav"), "text_sha256": sha256(directory / "output.txt"),
            "duration_seconds": len(samples) / sample_rate, "exact_committed_span_readback": True}
