"""Engineering fixtures for source isolation; not model efficacy evidence."""

import copy
import json
from pathlib import Path
import random
import tempfile
import unittest

from PIL import Image

from cohort import (OBSERVATION_KEYS, SPLITS, build_cohort, candidate_sources,
                    canonical, image_fingerprint, iter_pairs, load_observations,
                    sha, validate_splits)


class CohortTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cache = self.root / "images"
        self.cache.mkdir()
        self.annotations = self.root / "instances.json"
        self.output = self.root / "cohort"
        self.data = {"categories": [{"id": 1, "name": "cat"}], "images": [], "annotations": []}
        for iid in range(1, 21):
            name = f"{iid:012d}.jpg"
            pixels = random.Random(iid).randbytes(96 * 64 * 3)
            Image.frombytes("RGB", (96, 64), pixels).save(self.cache / name, quality=95)
            self.data["images"].append({"id": iid, "file_name": name, "width": 96,
                                        "height": 64, "license": 4})
            self.data["annotations"].append({"id": 1000 + iid, "image_id": iid,
                                             "category_id": 1, "iscrowd": 0,
                                             "bbox": [8, 8, 32, 32]})
        self.annotations.write_bytes(canonical(self.data))

    def build(self, **kwargs):
        return build_cohort(self.annotations, self.output, sizes=(2, 1, 1, 2),
                            image_cache=self.cache, fixture=True, **kwargs)

    def rewrite_split(self, split, kind, transform):
        path = self.output / f"{split}.{kind}.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        transform(rows)
        payload = b"".join(canonical(row) + b"\n" for row in rows)
        path.write_bytes(payload)
        manifest_path = self.output / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["splits"][split][kind]["sha256"] = sha(payload)
        manifest_path.write_bytes(canonical(manifest))

    def test_selection_rejects_ambiguous_and_incomplete_targets(self):
        data = copy.deepcopy(self.data)
        data["images"] = data["images"][:8]
        data["annotations"] = data["annotations"][:8]
        data["annotations"][1]["iscrowd"] = 1
        data["annotations"][3]["bbox"] = [-1, 8, 32, 32]
        data["annotations"][4]["bbox"] = [8, 8, 2, 2]
        data["annotations"][5]["bbox"] = [32, 8, 32, 32]
        for offset in range(3):
            data["annotations"].append({"id": 2000 + offset, "image_id": 3,
                                         "category_id": 1, "iscrowd": 0, "bbox": [1, 1, 3, 3]})
        data["annotations"].append({"id": 3000, "image_id": 7, "category_id": 1,
                                     "iscrowd": 0, "bbox": [50, 8, 32, 32]})
        data["annotations"].append({"id": 3001, "image_id": 1, "category_id": 1,
                                     "iscrowd": 0, "bbox": [60, 8, 16, 16]})
        selected = {image["id"]: reference for image, reference, _ in candidate_sources(data)}
        self.assertEqual(set(selected), {1, 8})
        self.assertEqual(selected[1]["count"], 2)
        self.assertEqual(selected[1]["boxes"], [[8/96, 8/64, 40/96, 40/64],
                                                [60/96, 8/64, 76/96, 24/64]])
        self.assertEqual(selected[1]["largest_side"], "left")
        self.assertEqual(list(candidate_sources(data)), list(candidate_sources(copy.deepcopy(data))))

    def test_real_cohort_rejects_unpinned_fixture_annotations(self):
        with self.assertRaisesRegex(ValueError, "official instances"):
            build_cohort(self.annotations, self.output, image_cache=self.cache)
        self.assertFalse((self.output / "manifest.json").exists())

    def test_build_separates_labels_and_rejects_historical_visual_duplicate(self):
        first = next(candidate_sources(self.data))[0]
        fingerprint = image_fingerprint(self.cache / first["file_name"], [96, 64])
        prior = self.root / "prior.json"
        prior.write_bytes(canonical({"source_sample": {"images": [{"image_id": 9999, **fingerprint}]}}))
        manifest = self.build(exclusion_manifest=prior)
        self.assertEqual(manifest["evidence_kind"], "synthetic-fixture")
        self.assertIn(first["id"], {row["image_id"] for row in manifest["rejected"]})
        ids = []
        for split in SPLITS:
            for observation, reference in iter_pairs(self.output, split):
                self.assertEqual(set(observation), OBSERVATION_KEYS)
                self.assertNotIn("count", observation)
                self.assertEqual(reference["count"], len(reference["boxes"]))
                ids.append(reference["source_id"])
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(validate_splits(self.output), {
            "valid": True, "evidence_kind": "synthetic-fixture", "source_groups": 6,
            "splits": {"train": 2, "dev": 1, "calibration": 1, "test": 2}})

    def test_actor_loader_rejects_extra_reference_field(self):
        self.build(exclusion_manifest=None)
        self.rewrite_split("train", "observations", lambda rows: rows[0].update(count=1))
        with self.assertRaisesRegex(ValueError, "reference leakage"):
            load_observations(self.output, "train")

    def test_validator_recomputes_reference_from_original_annotations(self):
        self.build(exclusion_manifest=None)
        self.rewrite_split("test", "references", lambda rows: rows[0].update(count=2))
        with self.assertRaisesRegex(ValueError, "original COCO annotation"):
            validate_splits(self.output)

    def test_cross_split_source_reuse_is_rejected_even_with_updated_file_hashes(self):
        self.build(exclusion_manifest=None)
        train_observation, train_reference = next(iter_pairs(self.output, "train"))
        self.rewrite_split("test", "observations", lambda rows: rows.__setitem__(0, train_observation))
        self.rewrite_split("test", "references", lambda rows: rows.__setitem__(0, train_reference))
        path = self.output / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["splits"]["test"]["sources"][0] = manifest["splits"]["train"]["sources"][0]
        path.write_bytes(canonical(manifest))
        with self.assertRaisesRegex(ValueError, "duplicate source"):
            validate_splits(self.output)

    def test_image_bytes_are_revalidated(self):
        self.build(exclusion_manifest=None)
        observation = load_observations(self.output, "test")[0]
        Image.new("RGB", (96, 64), "blue").save(observation["image_path"])
        with self.assertRaisesRegex(ValueError, "image custody"):
            validate_splits(self.output)

    def test_existing_cohort_is_not_overwritten(self):
        self.build(exclusion_manifest=None)
        before = (self.output / "manifest.json").read_bytes()
        with self.assertRaisesRegex(FileExistsError, "overwrite"):
            self.build(exclusion_manifest=None)
        self.assertEqual((self.output / "manifest.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
