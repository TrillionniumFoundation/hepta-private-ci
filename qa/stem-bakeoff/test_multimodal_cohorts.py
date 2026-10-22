"""Real file/decode/replay behavior using tiny test-only photo stand-ins."""

from collections import Counter, defaultdict
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
from PIL import Image

import multimodal_cohorts as m


class MultimodalCohortTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / "photos"
        self.cache.mkdir()
        self.counts = dict.fromkeys(("train", "dev", "calibration", "test"), 2)
        data = {"images": [], "annotations": [], "licenses": [
            {"id": 4, "name": "fixture attribution", "url": "https://example.invalid/license"}]}
        rng = np.random.default_rng(21)
        for image_id in range(101, 109):
            filename = f"{image_id:012d}.jpg"
            Image.fromarray(rng.integers(0, 256, (32, 32, 3), dtype=np.uint8)).save(
                self.cache / filename, format="JPEG", quality=92)
            data["images"].append({"id": image_id, "file_name": filename, "width": 32,
                "height": 32, "license": 4, "flickr_url": f"https://example.invalid/{image_id}",
                "coco_url": f"http://images.cocodataset.org/val2017/{filename}"})
            for version in (1, 2):
                data["annotations"].append({"image_id": image_id, "id": image_id * 10 + version,
                    "caption": f"Test-only original description {version} for photograph {image_id}."})
        caption_bytes = m.canonical(data)
        self.archive = self.root / "captions.zip"
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr(m.CAPTION_MEMBER, caption_bytes)
        self.pin_path = self.root / "sample.json"
        self.pin = {"archive_sha256": m.sha(self.archive.read_bytes()),
                    "captions_sha256": m.sha(caption_bytes), "selection_seed": m.SEED,
                    "split_images": self.counts, "images": []}
        for source in m.candidate_sources(data):
            self.pin["images"].append({**source,
                **m.image_fingerprint(self.cache / source["file_name"], source)})
        pin_bytes = m.canonical(self.pin) + b"\n"
        self.pin_path.write_bytes(pin_bytes)
        replacements = {"ARCHIVE_BYTES": self.archive.stat().st_size,
            "ARCHIVE_SHA256": self.pin["archive_sha256"], "CAPTIONS_SHA256": m.sha(caption_bytes),
            "SOURCE_SAMPLE": self.pin_path, "SOURCE_SAMPLE_SHA256": m.sha(pin_bytes),
            "SPLIT_IMAGES": self.counts}
        self.patches = patch.multiple(m, **replacements)
        self.patches.start()
        self.addCleanup(self.patches.stop)
        self.counter = 0

    def prepare(self):
        self.counter += 1
        output = self.root / f"cohorts-{self.counter}"
        manifest = m.prepare_cohorts(archive=self.archive, output=output, image_cache=self.cache)
        loaded, rows = m.load_cohorts(output,
            expected_manifest_sha256=m.sha((output / "manifest.json").read_bytes()))
        self.assertEqual(manifest, loaded)
        return output, manifest, rows

    def test_source_replay_preserves_disjoint_blocks_and_identical_unimodal_marginals(self):
        _, _, splits = self.prepare()
        previous_endpoints, previous_blocks, row_ids = set(), set(), set()
        for split, rows in splits.items():
            endpoints = {r["image_id"] for r in rows} | {r["source_caption_image_id"] for r in rows}
            blocks = defaultdict(list)
            self.assertFalse(previous_endpoints & endpoints)
            self.assertEqual(Counter((r["image_id"], r["label"]) for r in rows),
                             Counter({(image, label): 1 for image in endpoints for label in (0, 1)}))
            captions = {r["caption_id"] for r in rows}
            self.assertEqual(Counter((r["caption_id"], r["label"]) for r in rows),
                             Counter({(caption, label): 1 for caption in captions for label in (0, 1)}))
            for row in rows:
                self.assertEqual(row["label"], int(row["image_id"] == row["source_caption_image_id"]))
                self.assertEqual(row["split"], split)
                self.assertEqual(row["text_sha256"], m.sha(row["text"].encode()))
                self.assertNotIn(row["row_id"], row_ids)
                row_ids.add(row["row_id"])
                blocks[row["pair_block_id"]].append(row)
            for block in blocks.values():
                self.assertEqual((len(block), len({x["image_id"] for x in block}),
                                  Counter(x["label"] for x in block)), (4, 2, Counter({0: 2, 1: 2})))
            self.assertFalse(previous_blocks & set(blocks))
            previous_blocks.update(blocks)
            previous_endpoints.update(endpoints)

    def test_forged_caption_label_and_cross_split_endpoint_fail_even_after_rehashing(self):
        for attack in ("text", "label", "cross_split"):
            with self.subTest(attack=attack):
                output, manifest, splits = self.prepare()
                rows = splits["test"]
                if attack == "text":
                    rows[0]["text"] = "A fabricated label-bearing caption."
                    rows[0]["text_sha256"] = m.sha(rows[0]["text"].encode())
                elif attack == "label":
                    rows[0]["label"] = 1 - rows[0]["label"]
                else:
                    donor = splits["train"][0]
                    for key in ("caption_id", "text", "text_sha256", "source_caption_image_id"):
                        rows[0][key] = donor[key]
                rows[0]["row_id"] = m.sha(m.canonical({k: v for k, v in rows[0].items() if k != "row_id"}))
                payload = b"".join(m.canonical(row) + b"\n" for row in rows)
                (output / "test.jsonl").write_bytes(payload)
                manifest["splits"]["test"]["jsonl_sha256"] = m.sha(payload)
                manifest["splits"]["test"]["labels"] = dict(Counter(str(r["label"]) for r in rows))
                raw = m.canonical(manifest) + b"\n"
                (output / "manifest.json").write_bytes(raw)
                with self.assertRaisesRegex(m.MultimodalDataError, "replay"):
                    m.load_cohorts(output, expected_manifest_sha256=m.sha(raw))

    def test_modified_original_caption_source_is_not_authorized_by_new_manifest_hash(self):
        output, manifest, _ = self.prepare()
        source = json.loads((output / m.CAPTIONS_FILE).read_bytes())
        source["annotations"][0]["caption"] = "forged original"
        raw = m.canonical(source)
        (output / m.CAPTIONS_FILE).write_bytes(raw)
        manifest["captions_sha256"] = m.sha(raw)
        (output / "manifest.json").write_bytes(m.canonical(manifest))
        with self.assertRaisesRegex(m.MultimodalDataError, "original human caption"):
            m.load_cohorts(output)

    def test_decoded_duplicate_photos_are_rejected_before_dataset_publication(self):
        first, second = self.pin["images"][:2]
        (self.cache / second["file_name"]).write_bytes((self.cache / first["file_name"]).read_bytes())
        second.update(m.image_fingerprint(self.cache / second["file_name"], second))
        raw = m.canonical(self.pin)
        self.pin_path.write_bytes(raw)
        with patch.object(m, "SOURCE_SAMPLE_SHA256", m.sha(raw)):
            with self.assertRaisesRegex(m.MultimodalDataError, "duplicate"):
                self.prepare()

    def test_reencoded_near_duplicate_with_different_pixels_is_rejected(self):
        first, second = self.pin["images"][:2]
        with Image.open(self.cache / first["file_name"]) as photo:
            pixels = np.asarray(photo.convert("RGB")).copy()
        pixels[0, 0] = [0, 0, 0]
        Image.fromarray(pixels).save(self.cache / second["file_name"], format="JPEG", quality=92)
        second.update(m.image_fingerprint(self.cache / second["file_name"], second))
        self.assertNotEqual(first["decoded_rgb_sha256"], second["decoded_rgb_sha256"])
        self.assertLessEqual((int(first["dhash64"], 16) ^ int(second["dhash64"], 16)).bit_count(), 4)
        raw = m.canonical(self.pin)
        self.pin_path.write_bytes(raw)
        with patch.object(m, "SOURCE_SAMPLE_SHA256", m.sha(raw)):
            with self.assertRaisesRegex(m.MultimodalDataError, "near-duplicate"):
                self.prepare()

    def test_photo_mutation_and_symlink_are_rejected(self):
        output, _, rows = self.prepare()
        path = output / rows["train"][0]["image_path"]
        original = path.read_bytes()
        Image.new("RGB", (32, 32), "red").save(path, format="JPEG")
        with self.assertRaisesRegex(m.MultimodalDataError, "photo bytes"):
            m.load_cohorts(output)
        path.unlink()
        elsewhere = self.root / "outside.jpg"
        elsewhere.write_bytes(original)
        path.symlink_to(elsewhere)
        with self.assertRaisesRegex(m.MultimodalDataError, "symlink"):
            m.load_cohorts(output)

    def test_replay_rejects_self_attested_quality(self):
        output, manifest, _ = self.prepare()
        manifest["quality_qualified"] = True
        raw = m.canonical(manifest)
        (output / "manifest.json").write_bytes(raw)
        with self.assertRaisesRegex(m.MultimodalDataError, "claims"):
            m.load_cohorts(output, expected_manifest_sha256=m.sha(raw))

    def test_corrupted_archive_and_mutable_source_registry_are_rejected(self):
        self.archive.write_bytes(self.archive.read_bytes() + b"mutated")
        with self.assertRaises(m.MultimodalDataError):
            m.verify_archive(self.archive)
        self.pin_path.write_bytes(m.canonical({**self.pin, "selection_seed": "changed"}))
        with self.assertRaisesRegex(m.MultimodalDataError, "registry changed"):
            m._source_sample({})

    def test_download_checks_actual_bytes_and_never_replaces_conflicting_cache(self):
        payload = b"bounded file bytes"
        response = io.BytesIO(payload)
        response.headers = {"ETag": '"' + hashlib.md5(payload).hexdigest() + '"'}
        path = self.root / "download.jpg"
        url = "https://s3.amazonaws.com/images.cocodataset.org/val2017/000000000001.jpg"
        with patch.object(m, "urlopen", return_value=response):
            self.assertEqual(m.fetch_file(url, path, expected_sha256=m.sha(payload)), len(payload))
        self.assertEqual(path.read_bytes(), payload)
        with self.assertRaisesRegex(m.MultimodalDataError, "conflicts"):
            m.fetch_file(url, path, expected_sha256="0" * 64)
        self.assertEqual(path.read_bytes(), payload)
        wrong = io.BytesIO(payload)
        wrong.headers = {"ETag": '"' + "0" * 32 + '"'}
        rejected = self.root / "rejected.jpg"
        with patch.object(m, "urlopen", return_value=wrong):
            with self.assertRaisesRegex(m.MultimodalDataError, "ETag"):
                m.fetch_file(url, rejected)
        self.assertFalse(rejected.exists())
        self.assertFalse(rejected.with_name(rejected.name + ".partial").exists())


if __name__ == "__main__":
    unittest.main()
