"""Actual codec/clock boundaries, plus invalid semantic-condition rejection."""

from pathlib import Path
import shutil
import tempfile
import unittest
import wave

import numpy as np
import torch

from .media import read_media, write_media
from .models import AcousticDecoder, TemporalPixelDecoder, validate_probabilities


class MediaContractTests(unittest.TestCase):
    def test_semantic_condition_rejects_unbounded_or_nonprobability_input(self):
        for values in (torch.zeros(1, 2, 10), torch.full((1, 2, 10), float("nan")),
                       torch.ones(1, 2, 11) / 11):
            with self.assertRaises(ValueError):
                validate_probabilities(values, paired=True)

    def test_learned_heads_produce_finite_condition_dependent_media(self):
        torch.manual_seed(17)
        torch.set_num_threads(2)
        probabilities = torch.nn.functional.one_hot(torch.tensor([[1, 2], [8, 9]]), 10).float()
        audio, video = AcousticDecoder(), TemporalPixelDecoder()
        spectra = audio.decode(probabilities.reshape(-1, 10))
        frames = video(probabilities)
        self.assertEqual(tuple(spectra.shape), (4, 1, 129, 101))
        self.assertEqual(tuple(frames.shape), (2, 20, 1, 28, 28))
        self.assertTrue(torch.isfinite(spectra).all())
        self.assertTrue(torch.isfinite(frames).all())
        self.assertFalse(torch.equal(spectra[0], spectra[2]))
        self.assertFalse(torch.equal(frames[0], frames[1]))
        self.assertFalse(torch.equal(frames[0, 0], frames[0, -1]))

    def test_actual_lossless_mux_clock_and_crossfile_rejection(self):
        ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
        self.assertIsNotNone(ffmpeg, "Actual codec is required; do not silently skip")
        self.assertIsNotNone(ffprobe, "Actual parser is required; do not silently skip")
        pixels = torch.arange(28 * 56).reshape(1, 28, 56).float() / (28 * 56)
        time = torch.arange(8000) / 8000
        waveform = torch.stack((.4 * torch.sin(2 * torch.pi * 300 * time),
                                .4 * torch.sin(2 * torch.pi * 600 * time)))
        frames = torch.arange(20).float()[:, None, None, None].expand(20, 1, 28, 28) / 20
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "joint"
            report = write_media(directory, "left 1 right 2 relation less", pixels,
                                  waveform, frames, {"request_sha256": "1" * 64,
                                                     "state_sha256": "2" * 64}, ffmpeg, ffprobe)
            self.assertTrue(report["lossless_roundtrip"])
            self.assertEqual(report["required_modalities"], ["text", "image", "audio", "video"])
            paths = {name: entry["path"] for name, entry in report["files"].items()}
            actual = read_media(paths, ffmpeg, ffprobe)
            self.assertEqual(actual["clock"]["events"][1],
                             {"slot": 1, "audio_sample": 8000, "video_frame": 10,
                              "time_ns": 1_000_000_000})
            with wave.open(paths["audio"], "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(8000)
                output.writeframes(np.zeros(16000, dtype="<i2").tobytes())
            with self.assertRaisesRegex(ValueError, "byte census mismatch"):
                read_media(paths, ffmpeg, ffprobe)

    def test_missing_required_modality_is_not_a_complete_bundle(self):
        with self.assertRaises(ValueError):
            read_media({"text": "absent", "image": "absent", "audio": "absent"})


if __name__ == "__main__":
    unittest.main()
