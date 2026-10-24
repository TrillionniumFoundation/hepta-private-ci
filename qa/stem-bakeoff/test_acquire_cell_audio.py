import hashlib
import io
from pathlib import Path
import tempfile
import unittest
import wave

from acquire_cell_audio import acquire_one, verify_audio
from prepare_cell_media import ESC_REVISION, input_identity


class AudioAcquisitionTests(unittest.TestCase):
    def fixture(self, frames=220500):
        stream = io.BytesIO()
        with wave.open(stream, "wb") as clip:
            clip.setparams((1, 2, 44100, frames, "NONE", "not compressed"))
            clip.writeframes(b"\0\0" * frames)
        raw = stream.getvalue()
        digest = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        row = {"source_id": "fixture", "filename": "1-1-A-1.wav", "text": "An environmental audio recording.",
               "record": {"audio": "media/1-1-A-1.wav"}, "media_bytes": len(raw), "upstream_blob_sha": digest,
               "source_version": "git:" + ESC_REVISION,
               "upstream_url": f"https://raw.githubusercontent.com/karolpiczak/ESC-50/{ESC_REVISION}/audio/1-1-A-1.wav"}
        row["input_content_sha256"] = input_identity("audio", row["text"], "git-blob-sha1:" + digest)
        return raw, row

    def test_waveform_and_git_object_must_both_match(self):
        raw, row = self.fixture()
        self.assertEqual(verify_audio(raw, row)["frames"], 220500)
        with self.assertRaisesRegex(ValueError, "Git blob"):
            verify_audio(raw[:-1] + b"x", row)
        short, short_row = self.fixture(100)
        with self.assertRaisesRegex(ValueError, "five-second"):
            verify_audio(short, short_row)

    def test_existing_files_reverify_and_path_or_identity_changes_fail(self):
        raw, row = self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "media").mkdir()
            (root / row["record"]["audio"]).write_bytes(raw)
            self.assertEqual(acquire_one(root, row)["acquisition"], "verified_existing")
            row["input_content_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "identity"):
                acquire_one(root, row)
            row["record"]["audio"] = "../escaped.wav"
            with self.assertRaisesRegex(ValueError, "directory"):
                acquire_one(root, row)


if __name__ == "__main__":
    unittest.main()
