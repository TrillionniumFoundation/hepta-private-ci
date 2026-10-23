"""Original-byte decode checks; generated signal fixtures are NOT model outputs."""
import copy
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import wave

from decoded_media_audit import DecodedMediaRejected, audit_decoded_media


H = "a" * 64
I = "b" * 64


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "Codec tests require ffmpeg; dedicated CI job enforces tools")
class DecodedMediaAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise RuntimeError("required real ffmpeg/ffprobe media decoders unavailable")
        cls.temp = tempfile.TemporaryDirectory(prefix="dmgp-real-media-")
        cls.root = Path(cls.temp.name)
        (cls.root / "out.txt").write_text("describes a real encoded event", encoding="utf8")
        # A WAV file with actual PCM frames. No generated-model capability.
        with wave.open(str(cls.root / "out.wav"), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(8000)
            wf.writeframes(b"\x00\x00" * 8000)
        for args in (
            ["-f", "lavfi", "-i", "color=c=red:s=64x64:d=1",
             "-frames:v", "1", str(cls.root / "out.png")],
            ["-f", "lavfi", "-i", "color=c=red:s=64x64:d=1",
             "-c:v", "mpeg4", "-q:v", "3", str(cls.root / "out.mp4")],
        ):
            result = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner",
                                     "-loglevel", "error", "-y", *args],
                                    capture_output=True, timeout=30)
            if result.returncode:
                raise RuntimeError(result.stderr.decode(errors="replace"))
        cls.events = [{"id": "event1", "entity": "subject1",
                       "start_ms": 0, "end_ms": 500}]
        cls.plan = {"schema": "hepta.ndu-dmgp.media-plan.v1",
                    "objective_digest": H, "input_digest": I, "generation": 1,
                    "required_modalities": ["text", "image", "audio", "video"],
                    "max_skew_ms": 60, "timeline": cls.events}
        cls.manifest = {"schema": "hepta.ndu-dmgp.media-output.v1",
                        "objective_digest": H, "input_digest": I, "generation": 1,
                        "outputs": [
                            {"modality": mod, "filename": filename,
                             "sha256": digest((cls.root / filename).read_bytes()),
                             "events": copy.deepcopy(cls.events)}
                            for mod, filename in (("text", "out.txt"),
                                                  ("image", "out.png"),
                                                  ("audio", "out.wav"),
                                                  ("video", "out.mp4"))]}

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "temp"):
            cls.temp.cleanup()

    def run_audit(self, plan=None, manifest=None, root=None):
        return audit_decoded_media(
            self.plan if plan is None else plan,
            self.manifest if manifest is None else manifest,
            asset_root=self.root if root is None else root)

    def test_physically_decodes_all_four_modalities_without_promotion(self):
        result = self.run_audit()
        self.assertTrue(result["verified_original_bytes_and_real_media_decode"])
        self.assertEqual(set(result["observed"]), {"text", "image", "audio", "video"})
        self.assertGreater(result["observed"]["video"]["duration_ms"], 500)
        self.assertGreater(result["observed"]["audio"]["duration_ms"], 500)
        self.assertGreater(result["local_decoder_audit_wall_ms"], 0)
        self.assertFalse(result["semantic_entities_independently_recognized"])
        self.assertFalse(result["host_energy_calibrated"])
        self.assertFalse(result["production_blockers_closed"])
        self.assertTrue(result["no_promotion_authority"])

    def test_refuses_unmatched_model_sources_or_required_modality(self):
        plan = dict(self.plan, objective_digest="c"*64)
        with self.assertRaisesRegex(DecodedMediaRejected, "unbound"):
            self.run_audit(plan=plan)
        manifest = copy.deepcopy(self.manifest)
        manifest["outputs"] = manifest["outputs"][:-1]
        with self.assertRaisesRegex(DecodedMediaRejected, "four-modal"):
            self.run_audit(manifest=manifest)
        plan = dict(self.plan, required_modalities=["text", "image"])
        with self.assertRaisesRegex(DecodedMediaRejected, "four-modal"):
            self.run_audit(plan=plan)

    def test_rejects_material_substitution_even_with_same_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            for row in self.manifest["outputs"]:
                name = row["filename"]
                (dst / name).write_bytes((self.root / name).read_bytes())
            (dst / "out.txt").write_text("changed bytes", encoding="utf8")
            with self.assertRaisesRegex(DecodedMediaRejected, "hash mismatch"):
                self.run_audit(root=dst)

    def test_forged_hash_still_cannot_claim_corrupt_media_decoded(self):
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            for row in self.manifest["outputs"]:
                name = row["filename"]
                (dst / name).write_bytes((self.root / name).read_bytes())
            bad = b"not a playable compressed video"
            (dst / "out.mp4").write_bytes(bad)
            manifest = copy.deepcopy(self.manifest)
            manifest["outputs"][3]["sha256"] = digest(bad)
            with self.assertRaisesRegex(DecodedMediaRejected, "decode"):
                self.run_audit(root=dst, manifest=manifest)

    def test_rejects_forged_file_type_and_timeline(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["outputs"][2]["modality"] = "video"
        with self.assertRaises(DecodedMediaRejected):
            self.run_audit(manifest=manifest)
        manifest = copy.deepcopy(self.manifest)
        manifest["outputs"][2]["events"][0]["entity"] = "other"
        with self.assertRaisesRegex(DecodedMediaRejected, "unmatched"):
            self.run_audit(manifest=manifest)
        manifest = copy.deepcopy(self.manifest)
        manifest["outputs"][3]["events"][0]["end_ms"] = 5000
        with self.assertRaisesRegex(DecodedMediaRejected, "unmatched"):
            self.run_audit(manifest=manifest)

    def test_rejects_unrealistic_av_skew(self):
        plan = copy.deepcopy(self.plan)
        plan["max_skew_ms"] = 120
        manifest = copy.deepcopy(self.manifest)
        manifest["outputs"][2]["events"][0]["start_ms"] = 100
        manifest["outputs"][3]["events"][0]["start_ms"] = 0
        self.run_audit(plan=plan, manifest=manifest)
        manifest["outputs"][2]["events"][0]["start_ms"] = 121
        with self.assertRaisesRegex(DecodedMediaRejected, "unmatched"):
            self.run_audit(plan=plan, manifest=manifest)

    def test_symlink_and_path_traversal_fail_closed(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["outputs"][0]["filename"] = "../out.txt"
        with self.assertRaisesRegex(DecodedMediaRejected, "unsafe"):
            self.run_audit(manifest=manifest)
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            for row in self.manifest["outputs"]:
                name = row["filename"]
                (dst / name).write_bytes((self.root / name).read_bytes())
            (dst / "out.txt").unlink()
            os.symlink(self.root / "out.txt", dst / "out.txt")
            with self.assertRaisesRegex(DecodedMediaRejected, "unsafe"):
                self.run_audit(root=dst)

    def test_rejects_noninteger_clock_or_obvious_bypass(self):
        for value in (True, 60.0, -1, 121):
            plan = dict(self.plan, max_skew_ms=value)
            with self.assertRaises(DecodedMediaRejected):
                self.run_audit(plan=plan)
        manifest = copy.deepcopy(self.manifest)
        manifest["outputs"][0]["events"][0]["start_ms"] = True
        with self.assertRaises(DecodedMediaRejected):
            self.run_audit(manifest=manifest)


if __name__ == "__main__":
    unittest.main()