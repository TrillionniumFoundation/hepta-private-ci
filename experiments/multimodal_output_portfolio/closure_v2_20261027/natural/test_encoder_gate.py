"""Verify decoder allocation precedes generation and retains one encoder call."""
from pathlib import Path
import tempfile
import unittest

import numpy as np

from .speech_encoder_gate import episode


class RecordingEngine:
    def __init__(self):
        self.events = []

    def prepare(self, path):
        self.events.append("encode")
        return np.ones((1, 4, 32), dtype=np.float32), {"audio_samples": 16000, "encoded_sha256": "fixture"}

    def generate(self, encoded, beam, destination):
        if self.events != ["encode"]:
            raise AssertionError("A decoder was invoked before the sole selection")
        self.events.append("decode-" + str(beam))
        transcript = "actual selected beam " + str(beam)
        destination.write_text(transcript + "\n")
        return {"transcript": transcript, "beam": beam}


class EncoderGateTests(unittest.TestCase):
    def test_public_gate_dispatches_exactly_one_decoder_after_one_encoder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for sign, expected in ((1., 5), (-1., 1)):
                model = {"mean": [0.] * 49, "scale": [1.] * 49, "weights": [sign] + [0.] * 49}
                engine = RecordingEngine()
                result = episode(engine, "public-input", model, 0., root / str(expected))
                self.assertEqual(engine.events, ["encode", "decode-" + str(expected)])
                self.assertEqual(result["encoder_calls"], 1)
                self.assertEqual(result["decoder_calls"], 1)
                self.assertEqual(result["gate"]["decoder_outputs_before_gate"], 0)
                self.assertEqual(Path(result["output_path"]).read_text().strip(), "actual selected beam " + str(expected))


if __name__ == "__main__":
    unittest.main()
