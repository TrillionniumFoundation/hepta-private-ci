"""Real codec substitutions must not satisfy the frozen four-format contract."""
import copy
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from decoded_media_audit import DecodedMediaRejected, audit_decoded_media
import test_decoded_media_audit as media_fixtures


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "Codec tests require ffmpeg; dedicated CI job enforces tools")
class MediaTypeAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        media_fixtures.DecodedMediaAuditTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        media_fixtures.DecodedMediaAuditTests.tearDownClass()

    def check_transcode(self, modality, options, expected_codec=None):
        fixture = media_fixtures.DecodedMediaAuditTests
        manifest = copy.deepcopy(fixture.manifest)
        row = next(row for row in manifest["outputs"]
                   if row["modality"] == modality)
        with tempfile.TemporaryDirectory(prefix="dmgp-format-substitution-") as tmp:
            root = Path(tmp)
            for original in manifest["outputs"]:
                name = original["filename"]
                (root / name).write_bytes((fixture.root / name).read_bytes())
            target = root / row["filename"]
            subprocess.run([
                "ffmpeg", "-nostdin", "-v", "error", "-y", "-threads", "1",
                "-i", str(fixture.root / row["filename"]),
                *options, "-threads", "1", str(target),
            ], capture_output=True, check=True, timeout=20)
            # Correct hashes are necessary but cannot certify declared format.
            row["sha256"] = media_fixtures.digest(target.read_bytes())
            if expected_codec is None:
                with self.assertRaisesRegex(DecodedMediaRejected, "format|codec"):
                    audit_decoded_media(fixture.plan, manifest, asset_root=root)
            else:
                result = audit_decoded_media(fixture.plan, manifest, asset_root=root)
                self.assertEqual(result["observed"][modality]["codec"], expected_codec)
                self.assertFalse(result["production_blockers_closed"])
                self.assertTrue(result["no_promotion_authority"])

    def test_jpeg_renamed_png_rejected_after_rehash(self):
        self.check_transcode(
            "image", ["-c:v", "mjpeg", "-frames:v", "1", "-f", "image2"])

    def test_adpcm_wav_rejected_after_rehash(self):
        self.check_transcode(
            "audio", ["-c:a", "adpcm_ima_wav", "-f", "wav"])

    def test_matroska_renamed_mp4_rejected_after_rehash(self):
        self.check_transcode(
            "video", ["-c:v", "copy", "-f", "matroska"])

    def test_quicktime_renamed_mp4_rejected_after_rehash(self):
        self.check_transcode(
            "video", ["-c:v", "copy", "-f", "mov"])

    def test_legitimate_pcm_wav_variants_remain_admitted(self):
        for codec in ("pcm_u8", "pcm_s24le", "pcm_f32le", "pcm_alaw", "pcm_mulaw"):
            with self.subTest(codec=codec):
                self.check_transcode("audio", ["-c:a", codec, "-f", "wav"], codec)
        self.check_transcode(
            "audio", ["-c:a", "pcm_s16le", "-rf64", "always", "-f", "wav"],
            "pcm_s16le")

    def test_faststart_and_fragmented_mp4_remain_admitted(self):
        for flags in ("+faststart", "+frag_keyframe+empty_moov"):
            with self.subTest(flags=flags):
                self.check_transcode(
                    "video", ["-c:v", "copy", "-movflags", flags, "-f", "mp4"],
                    "mpeg4")


if __name__ == "__main__":
    unittest.main()
