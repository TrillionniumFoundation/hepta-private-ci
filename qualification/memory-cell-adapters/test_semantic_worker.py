"""Real Python worker wire checks with an explicitly synthetic encoder source."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from semantic_protocol import ENCODER_DIGEST

MOCK_SOURCE = '''from types import SimpleNamespace
class Vector(list):
    def tolist(self): return list(self)
class Tokenizer:
    def encode(self, text): return SimpleNamespace(ids=[1,2], overflowing=[1] if text == "TRUNCATE" else [])
class PinnedMiniLMEncoder:
    def __init__(self, *args, **kwargs):
        self.digest = "4bff7b22bc544468dca828c404026aaa5d011ce83e305d056c14a24658955faf"
        self.base_bytes = 127536988
        self.tokenizer = Tokenizer()
    def encode(self, texts): return [Vector([1.0] + [0.0]*383) for text in texts]
'''


def frame(sequence, text):
    return {"schema": "hepta.memory.inventory-encoder-request.v1", "request_id": sequence,
            "text": text, "text_digest": hashlib.sha256(text.encode()).hexdigest(), "encoder_digest": ENCODER_DIGEST}


class WorkerProtocol(unittest.TestCase):
    def run_worker(self, raw, source_digest=None):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "encoder.py"; source.write_text(MOCK_SOURCE)
            command = [sys.executable, "-I", "-u", "-B", str(Path(__file__).with_name("semantic_encoder_worker.py")),
                       "--encoder-source", str(source), "--source-sha256", source_digest or hashlib.sha256(source.read_bytes()).hexdigest(),
                       "--encoder", temporary, "--encoder-digest", ENCODER_DIGEST]
            return subprocess.run(command, input=raw, capture_output=True, timeout=5, check=False)

    def test_serialized_unicode_and_truncation(self):
        raw = b"".join(json.dumps(frame(i, text)).encode() + b"\n" for i, text in enumerate(("读取 Cedar Harbor", "TRUNCATE", "next"), 1))
        result = self.run_worker(raw)
        self.assertEqual(result.returncode, 0, result.stderr)
        ready = json.loads(result.stderr)
        self.assertEqual(ready["encoder_digest"], ENCODER_DIGEST)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([row["request_id"] for row in rows], [1,2,3])
        self.assertEqual(len(rows[0]["features"]), 384)
        self.assertEqual(rows[1]["features"], []); self.assertTrue(rows[1]["truncated"])
        self.assertEqual(rows[2]["text_digest"], frame(3, "next")["text_digest"])

    def test_invalid_binding_duplicate_and_oversize_stop_without_a_response(self):
        wrong = frame(1, "text"); wrong["text_digest"] = "1" * 64
        duplicate = json.dumps(frame(1, "text")).replace('"request_id": 1', '"request_id": 1, "request_id": 1').encode() + b"\n"
        for raw in (json.dumps(wrong).encode() + b"\n", duplicate, b"x" * 16385 + b"\n"):
            result = self.run_worker(raw)
            self.assertNotEqual(result.returncode, 0); self.assertEqual(result.stdout, b"")

    def test_replayed_sequence_and_changed_source_are_rejected(self):
        raw = json.dumps(frame(1, "first")).encode() + b"\n"
        replayed = self.run_worker(raw + raw)
        self.assertNotEqual(replayed.returncode, 0); self.assertEqual(len(replayed.stdout.splitlines()), 1)
        changed = self.run_worker(raw, source_digest="0" * 64)
        self.assertNotEqual(changed.returncode, 0); self.assertEqual(changed.stdout, b"")


if __name__ == "__main__":
    unittest.main()
