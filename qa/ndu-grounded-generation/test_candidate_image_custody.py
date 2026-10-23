"""Real local JPEG negative controls for v2 candidate-image custody.

No model weights or reference labels are used; four tiny generated JPEGs only.
"""

import copy
import hashlib
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from cohort import image_fingerprint
import cohort_firewall as firewall
from test_cohort_firewall import image, manifest


def raw(document):
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()


class CandidateImageCustodyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.images = self.root / "images"
        self.images.mkdir()
        self.candidate = manifest(32)
        for n, split in enumerate(firewall.SPLITS):
            name = f"candidate-{n}.jpg"
            path = self.images / name
            pixels = random.Random(43790 + n).randbytes(32 * 24 * 3)
            Image.frombytes("RGB", (32, 24), pixels).save(path, "JPEG", quality=89)
            row = self.candidate["splits"][split]["sources"][0]
            row.update(image_fingerprint(path, (32, 24)))
            row["image_filename"] = name
            row["image_size"] = [32, 24]
        self.v1 = manifest(0)
        old_image = image(10)
        old_image["image_id"] = 10
        del old_image["source_id"]
        self.pre_v1 = {"schema": "hepta.ndu.historical-exclusions.v1",
                       "source_sample": {"images": [old_image]}}
        self.historical_blobs = [raw(self.v1), raw(self.pre_v1)]
        self.pins = {
            "hepta.grounded-cohort.v1":
                {"sha256": hashlib.sha256(self.historical_blobs[0]).hexdigest(), "sources": 4},
            "hepta.ndu.historical-exclusions.v1":
                {"sha256": hashlib.sha256(self.historical_blobs[1]).hexdigest(), "sources": 1},
        }

    def test_actual_bytes_match_all_three_claimed_hashes(self):
        proof = firewall.verify_candidate_image_bytes(self.candidate, self.images)
        self.assertEqual(proof["checked_images"], 4)
        self.assertTrue(proof["original_bytes_cryptographically_checked"])
        self.assertGreater(proof["source_jpeg_bytes"], 0)
        self.assertFalse(proof["independent_real_world_entities_proven"])

    def test_missing_image_dir_cannot_authorize_pass(self):
        with self.assertRaisesRegex(firewall.CohortContractError, "image bytes are required"):
            firewall.verify_candidate_image_bytes(self.candidate, None)

    def test_forged_candidate_image_or_rgb_digest_rejected(self):
        for key in ("image_sha256", "decoded_rgb_sha256", "dhash64", "image_bytes"):
            with self.subTest(key=key):
                changed = copy.deepcopy(self.candidate)
                first = changed["splits"]["train"]["sources"][0]
                if key == "image_bytes":
                    first[key] += 1
                else:
                    first[key] = ("0" if first[key][0] != "0" else "1") + first[key][1:]
                with self.assertRaisesRegex(firewall.CohortContractError, key):
                    firewall.verify_candidate_image_bytes(changed, self.images)

    def test_replaced_local_jpeg_rejected(self):
        path = self.images / "candidate-0.jpg"
        path.write_bytes((self.images / "candidate-1.jpg").read_bytes())
        with self.assertRaisesRegex(firewall.CohortContractError, "actual image bytes disagree"):
            firewall.verify_candidate_image_bytes(self.candidate, self.images)

    def test_image_traversal_and_symlink_refused(self):
        changed = copy.deepcopy(self.candidate)
        changed["splits"]["train"]["sources"][0]["image_filename"] = "../candidate-0.jpg"
        with self.assertRaisesRegex(firewall.CohortContractError, "safe image_filename"):
            firewall.verify_candidate_image_bytes(changed, self.images)
        link = self.images / "link.jpg"
        link.symlink_to(self.images / "candidate-0.jpg")
        changed["splits"]["train"]["sources"][0]["image_filename"] = "link.jpg"
        with self.assertRaisesRegex(firewall.CohortContractError, "symlink"):
            firewall.verify_candidate_image_bytes(changed, self.images)

    def test_wrong_dimensions_or_missing_jpeg_fails(self):
        changed = copy.deepcopy(self.candidate)
        changed["splits"]["train"]["sources"][0]["image_size"] = [12, 12]
        with self.assertRaisesRegex(firewall.CohortContractError, "invalid candidate JPEG"):
            firewall.verify_candidate_image_bytes(changed, self.images)
        changed["splits"]["train"]["sources"][0]["image_size"] = [32, 24]
        (self.images / "candidate-0.jpg").unlink()
        with self.assertRaisesRegex(firewall.CohortContractError, "missing image"):
            firewall.verify_candidate_image_bytes(changed, self.images)

    def test_cli_writes_real_image_and_history_custody_receipts(self):
        (self.root / "candidate.json").write_bytes(raw(self.candidate))
        for n, content in enumerate(self.historical_blobs):
            (self.root / f"history-{n}.json").write_bytes(content)
        output = self.root / "verdict.json"
        args = ["--candidate", str(self.root / "candidate.json"),
                "--historical", str(self.root / "history-0.json"),
                "--historical", str(self.root / "history-1.json"),
                "--image-dir", str(self.images),
                "--output", str(output)]
        with patch.object(firewall, "PINNED_HISTORIES", self.pins):
            self.assertEqual(firewall.main(args), 0)
        result = json.loads(output.read_text())
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["candidate_image_custody"]["checked_images"], 4)
        self.assertEqual(result["pinned_history_source_total"], 5)

    def test_cli_without_raw_images_fails_even_if_manifest_looks_disjoint(self):
        (self.root / "candidate.json").write_bytes(raw(self.candidate))
        for n, content in enumerate(self.historical_blobs):
            (self.root / f"history-{n}.json").write_bytes(content)
        output = self.root / "verdict.json"
        args = ["--candidate", str(self.root / "candidate.json"),
                "--historical", str(self.root / "history-0.json"),
                "--historical", str(self.root / "history-1.json"),
                "--output", str(output)]
        with patch.object(firewall, "PINNED_HISTORIES", self.pins):
            self.assertEqual(firewall.main(args), 2)
        result = json.loads(output.read_text())
        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["observable_image_identity_disjoint"])


if __name__ == "__main__":
    unittest.main()
