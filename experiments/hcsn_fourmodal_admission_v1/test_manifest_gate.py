"""Source-integrity and adversarial preflight tests; generated media is only a fixture."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from PIL import Image

from experiments.hcsn_fourmodal_admission_v1.manifest_gate import (
    AdmissionError, SCHEMA, load_manifest, validate_manifest,
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FourModalAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise RuntimeError("actual video preflight tests require ffmpeg + ffprobe")
        cls.temp = tempfile.TemporaryDirectory(prefix="hcsn-p3-")
        cls.root = Path(cls.temp.name) / "assets"
        cls.root.mkdir()
        samples = []
        for i, (split, color) in enumerate(zip(("train", "val", "test"), ("red", "green", "blue"))):
            base = cls.root / split
            base.mkdir()
            caption = base / "caption.txt"
            caption.write_text(f"person {i} is walking at event {i}\n", encoding="utf-8")
            photo = base / "scene.png"
            Image.new("RGB", (16, 16), ((i * 83 + 13) % 256, 30, 220)).save(photo)
            sound = base / "sound.wav"
            with wave.open(str(sound), "wb") as f:
                f.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
                frames = b"".join(int(((j * (i + 4)) % 180) * 100).to_bytes(2, "little", signed=True) for j in range(800))
                f.writeframes(frames)
            movie = base / "clip.mp4"
            cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                   "-f", "lavfi", "-i", f"color=c={color}:s=16x16:r=5:d=0.4",
                   "-an", "-c:v", "mpeg4", "-pix_fmt", "yuv420p", str(movie)]
            subprocess.run(cmd, check=True, timeout=30, capture_output=True)
            media = {}
            for modality, file in zip(("text", "image", "audio", "video"),
                                      (caption, photo, sound, movie)):
                media[modality] = {
                    "path": file.relative_to(cls.root).as_posix(),
                    "sha256": _digest(file),
                    "source_id": f"raw_{split}_{modality}",
                    "event_id": f"event_{i}",
                    "entity_id": f"entity_{i}",
                    "start_ms": i * 2000,
                    "end_ms": i * 2000 + 1000,
                }
            samples.append({
                "sample_id": f"sample_{i}", "split": split,
                "actor_id": f"actor_{i}", "session_id": f"session_{i}",
                "event_id": f"event_{i}", "entity_id": f"entity_{i}",
                "label": f"action_{i}", "modalities": media,
            })
        cls.manifest = {
            "schema_version": SCHEMA, "max_skew_ms": 100,
            "encoders": {name: {"encoder_id": f"{name}-encoder", "revision_sha256": f"{i+1:064x}"}
                         for i, name in enumerate(("text", "image", "audio", "video"))},
            "samples": samples,
        }

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def manifest_copy(self):
        return copy.deepcopy(self.manifest)

    def expect(self, manifest, code):
        with self.assertRaises(AdmissionError) as e:
            validate_manifest(manifest, self.root)
        self.assertEqual(e.exception.code, code)

    def test_valid_four_decoded_modalities_and_all_splits(self):
        receipt = validate_manifest(self.manifest_copy(), self.root)
        self.assertEqual(receipt["status"], "STRUCTURAL_SOURCE_PREFLIGHT_ONLY")
        self.assertEqual(receipt["sample_counts"], {"train": 1, "val": 1, "test": 1})
        self.assertEqual(receipt["modality_assets_verified"], 12)
        self.assertFalse(receipt["real_four_modal_quality_established"])
        self.assertFalse(receipt["production_activation_allowed"])
        self.assertEqual(receipt, validate_manifest(self.manifest_copy(), self.root))

    def test_reject_missing_modality(self):
        m = self.manifest_copy()
        del m["samples"][0]["modalities"]["video"]
        self.expect(m, "SCHEMA")

    def test_reject_missing_encoder_and_reused_encoder(self):
        m = self.manifest_copy()
        del m["encoders"]["video"]
        self.expect(m, "SCHEMA")
        m = self.manifest_copy()
        m["encoders"]["video"]["revision_sha256"] = m["encoders"]["image"]["revision_sha256"]
        self.expect(m, "ENCODER")

    def test_reject_entity_or_event_pair_shuffle(self):
        m = self.manifest_copy()
        m["samples"][1]["modalities"]["video"]["entity_id"] = "other-person"
        self.expect(m, "PAIRING")
        m = self.manifest_copy()
        m["samples"][1]["modalities"]["audio"]["event_id"] = "event_0"
        self.expect(m, "PAIRING")

    def test_reject_unpaired_time_or_reversed_time(self):
        m = self.manifest_copy()
        m["samples"][2]["modalities"]["video"]["start_ms"] = 10_000
        m["samples"][2]["modalities"]["video"]["end_ms"] = 11_000
        self.expect(m, "TIME")
        m = self.manifest_copy()
        m["samples"][0]["modalities"]["text"]["end_ms"] = 0
        m["samples"][0]["modalities"]["text"]["start_ms"] = 1
        self.expect(m, "TIME")
        m = self.manifest_copy()
        m["max_skew_ms"] = 50_000
        self.expect(m, "TIME")

    def test_reject_leakage_across_actors_sessions_and_sources(self):
        for key in ("actor_id", "session_id", "event_id"):
            m = self.manifest_copy()
            m["samples"][1][key] = m["samples"][0][key]
            self.expect(m, "LEAKAGE")
        m = self.manifest_copy()
        m["samples"][1]["modalities"]["video"]["source_id"] = m["samples"][0]["modalities"]["video"]["source_id"]
        self.expect(m, "LEAKAGE")

    def test_reject_duplicate_sample_id(self):
        m = self.manifest_copy()
        m["samples"][1]["sample_id"] = m["samples"][0]["sample_id"]
        self.expect(m, "LEAKAGE")

    def test_reject_byte_mutation_after_manifest_freeze(self):
        path = self.root / "test" / "caption.txt"
        original = path.read_bytes()
        try:
            path.write_bytes(b"injected unversioned content")
            self.expect(self.manifest_copy(), "HASH")
        finally:
            path.write_bytes(original)

    def test_reject_relabelled_media_with_correct_matching_hash(self):
        m = self.manifest_copy()
        wrong = self.root / "train" / "fake.png"
        wrong.write_bytes((self.root / "train" / "sound.wav").read_bytes())
        try:
            media = m["samples"][0]["modalities"]["image"]
            media["path"] = "train/fake.png"
            media["sha256"] = _digest(wrong)
            self.expect(m, "MEDIA")
        finally:
            wrong.unlink()

    def test_reject_path_traversal_and_symlink(self):
        m = self.manifest_copy()
        m["samples"][0]["modalities"]["text"]["path"] = "../escape.txt"
        self.expect(m, "PATH")
        target = self.root / "train" / "caption.txt"
        link = self.root / "train" / "alias.txt"
        link.symlink_to(target)
        try:
            m = self.manifest_copy()
            m["samples"][0]["modalities"]["text"]["path"] = "train/alias.txt"
            self.expect(m, "PATH")
        finally:
            link.unlink()

    def test_reject_duplicate_json_keys(self):
        json_path = Path(self.temp.name) / "duplicates.json"
        json_path.write_text('{"x":1,"x":2}', encoding="utf-8")
        with self.assertRaises(AdmissionError) as e:
            load_manifest(json_path)
        self.assertEqual(e.exception.code, "SCHEMA")

    def test_reject_reused_byte_equal_cross_split_content(self):
        m = self.manifest_copy()
        val_path = self.root / "val" / "caption.txt"
        old = val_path.read_bytes()
        try:
            val_path.write_bytes((self.root / "train" / "caption.txt").read_bytes())
            m["samples"][1]["modalities"]["text"]["sha256"] = _digest(val_path)
            self.expect(m, "LEAKAGE")
        finally:
            val_path.write_bytes(old)

    def test_reject_zero_or_boolean_timestamp(self):
        m = self.manifest_copy()
        m["samples"][0]["modalities"]["audio"]["start_ms"] = True
        self.expect(m, "SCHEMA")
        m = self.manifest_copy()
        m["samples"][0]["modalities"]["audio"]["end_ms"] = -1
        self.expect(m, "SCHEMA")

    def test_reject_non_json_numeric_constants(self):
        path = Path(self.temp.name) / "nan.json"
        path.write_text('{"x":NaN}', encoding="utf-8")
        with self.assertRaises(AdmissionError) as e:
            load_manifest(path)
        self.assertEqual(e.exception.code, "SCHEMA")

    def test_reject_missing_validation_split(self):
        m = self.manifest_copy()
        m["samples"] = [x for x in m["samples"] if x["split"] != "val"]
        self.expect(m, "SPLIT")


if __name__ == "__main__":
    unittest.main()
