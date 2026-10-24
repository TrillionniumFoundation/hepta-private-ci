"""Exact raw-PCM audit cache for a frozen finite deterministic voice profile.

Labels originate in the independently qualified CTC observer, never in the
generator's latent argmax or task target. Unknown byte sequences are rejected.
This cache accelerates evaluation only; native inference still runs neural TTS.
"""

import hashlib
import json
from pathlib import Path
import wave

from .media import file_pin, require_digest


def make_pcm_audit_cache(qualification_root, destination):
    root = Path(qualification_root)
    summary = json.loads((root / "summary.json").read_text())
    qualification = json.loads((root / "qualification.json").read_text())
    actual = sum(row["ctc_digit"] == row["expected"] for row in qualification["rows"]) / len(qualification["rows"])
    by_class = {digit: [row for row in qualification["rows"] if row["expected"] == digit] for digit in range(10)}
    if (len(qualification["rows"]) != 600 or actual < .8
            or any(len(rows) != 60 or sum(row["ctc_digit"] == digit for row in rows) / len(rows) < .6
                   for digit, rows in by_class.items()) or not summary["speech_capability_pass"]):
        raise ValueError("Cannot cache an unqualified speech observer/profile")
    mapping, evidence = {}, []
    for index in range(10):
        row_path = root / f"row-{index:03d}.json"
        row = json.loads(row_path.read_text())
        pin = row["output"]["files"]["audio"]
        if file_pin(pin["path"])["sha256"] != pin["sha256"]:
            raise ValueError("Frozen neural speech audit file changed")
        with wave.open(pin["path"], "rb") as source:
            if (source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getnframes()) != (1, 2, 8000, 16000):
                raise ValueError("Audited PCM census mismatch")
            raw = source.readframes(16000)
        for slot, observed in enumerate(row["audio_audit"]):
            pcm = raw[slot * 16000:(slot + 1) * 16000]
            key = hashlib.sha256(pcm).hexdigest()
            digit = observed["ctc_digit"]
            if key in mapping and mapping[key]["digit"] != digit:
                raise ValueError("Independent speech audit disagrees on identical PCM")
            mapping[key] = {"digit": digit, "ctc_negative_log_likelihoods": observed["ctc_negative_log_likelihoods"]}
        evidence.append({"row": file_pin(row_path), "audio": pin})
    if len(mapping) != 10 or {row["digit"] for row in mapping.values()} != set(range(10)):
        raise ValueError("Frozen finite voice was not exhaustively observed")
    registration = json.loads((root / "registration.json").read_text())
    result = {"schema": "hepta.ndu.finite-pcm-audit.v1", "purpose": "raw-byte outcome evaluator only",
              "voice": registration["voice"], "voice_profile": registration["voice_profile"],
              "asr_revision": registration["asr_revision"], "asr_weights": registration["asr_weights"],
              "qualification": file_pin(root / "qualification.json"),
              "summary": file_pin(root / "summary.json"), "evidence": evidence,
              "words": mapping, "unknown_pcm_prediction": -1, "authority": "deny_all"}
    with Path(destination).open("x") as output:
        json.dump(result, output, sort_keys=True, indent=2, allow_nan=False)
        output.write("\n")
    return file_pin(destination)


class FrozenPcmAudit:
    def __init__(self, path, sha256):
        require_digest(sha256)
        self.path = Path(path)
        self.sha256 = sha256
        raw = self.path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != sha256:
            raise ValueError("Caller must pin the finite independent PCM audit")
        self.record = json.loads(raw)
        if self.record["schema"] != "hepta.ndu.finite-pcm-audit.v1" or len(self.record["words"]) != 10:
            raise ValueError("Invalid bounded PCM audit profile")
        self._mapping = {key: row["digit"] for key, row in self.record["words"].items()}
        if set(self._mapping.values()) != set(range(10)):
            raise ValueError("Incomplete finite independent PCM audit")
        for key in self._mapping:
            require_digest(key)

    def verify_integrity(self):
        if hashlib.sha256(self.path.read_bytes()).hexdigest() != self.sha256:
            raise RuntimeError("Frozen PCM audit file changed")
        expected = {key: row["digit"] for key, row in json.loads(self.path.read_text())["words"].items()}
        if self._mapping != expected:
            raise RuntimeError("Frozen PCM outcome labels changed")

    def predict_pcm16(self, raw):
        self.verify_integrity()
        if not isinstance(raw, bytes) or not 16000 <= len(raw) <= 128 * 16000 or len(raw) % 16000:
            raise ValueError("Expected complete bounded one-second PCM16 segments")
        return [self._mapping.get(hashlib.sha256(raw[start:start + 16000]).hexdigest(), -1)
                for start in range(0, len(raw), 16000)]
