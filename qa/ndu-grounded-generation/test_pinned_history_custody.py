"""Negative controls for mandatory byte-pinned v1 and pre-v1 cohort custody.

Synthetic fixtures test the validator logic, not the science or authenticity
of the real source images. The deployed digest constants are immutable receipts.
"""

import copy
import hashlib
import json
import random
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from cohort import image_fingerprint
import cohort_firewall as firewall
from test_cohort_firewall import image, manifest


def raw(document):
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()


class PinnedHistoryCustodyTests(unittest.TestCase):
    def setUp(self):
        self.old_v1 = manifest(0)
        previous = image(16)
        previous["image_id"] = 16
        previous.pop("source_id")
        self.old_before_v1 = {"schema": "hepta.ndu.historical-exclusions.v1",
                              "source_sample": {"images": [previous]}}
        self.old_bytes = [raw(self.old_v1), raw(self.old_before_v1)]
        self.candidate = manifest(32)
        self.synthetic_pins = {
            "hepta.grounded-cohort.v1":
                {"sha256": hashlib.sha256(self.old_bytes[0]).hexdigest(), "sources": 4},
            "hepta.ndu.historical-exclusions.v1":
                {"sha256": hashlib.sha256(self.old_bytes[1]).hexdigest(), "sources": 1},
        }

    def test_accepts_complete_authentic_history_in_any_order(self):
        with patch.object(firewall, "PINNED_HISTORIES", self.synthetic_pins):
            for blobs in (self.old_bytes, list(reversed(self.old_bytes))):
                histories, receipts = firewall.verify_pinned_histories(blobs)
                self.assertEqual(len(histories), 2)
                self.assertEqual(sum(x["sources"] for x in receipts.values()), 5)
                result = firewall.check_cohort(self.candidate, histories)
                self.assertEqual(result["status"], "pass")

    def test_rejects_omission_and_duplicates(self):
        with patch.object(firewall, "PINNED_HISTORIES", self.synthetic_pins):
            for data in ([], [self.old_bytes[0]], [self.old_bytes[0]] * 2,
                         [self.old_bytes[1]] * 2):
                with self.subTest(len=len(data)), self.assertRaises(
                        firewall.CohortContractError):
                    firewall.verify_pinned_histories(data)

    def test_refuses_plausible_replacement_instead_of_trusting_fake_history(self):
        replacement = manifest(900)
        self.assertEqual(firewall.check_cohort(self.candidate, [replacement])["status"], "pass")
        with patch.object(firewall, "PINNED_HISTORIES", self.synthetic_pins):
            with self.assertRaisesRegex(firewall.CohortContractError, "unpinned"):
                firewall.verify_pinned_histories([raw(replacement), self.old_bytes[1]])

    def test_refuses_byte_mutations_even_with_same_decoded_identity(self):
        changed = self.old_bytes[0] + b" "
        self.assertEqual(json.loads(changed), self.old_v1)
        with patch.object(firewall, "PINNED_HISTORIES", self.synthetic_pins):
            with self.assertRaisesRegex(firewall.CohortContractError, "unpinned"):
                firewall.verify_pinned_histories([changed, self.old_bytes[1]])

    def test_cli_emits_custody_receipts_for_real_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # A CLI PASS must exercise actual source-byte custody, not just
            # trust the synthetic manifest fingerprints. Use four distinct,
            # deterministic JPEGs and compute fingerprints with the frozen
            # v1 cohort algorithm required by the production gate.
            image_dir = root / "images"
            image_dir.mkdir()
            candidate = copy.deepcopy(self.candidate)
            for index, split in enumerate(firewall.SPLITS):
                rng = random.Random(702100 + index)
                picture = Image.new("RGB", (128, 96))
                picture.putdata([
                    (rng.randrange(256), rng.randrange(256), rng.randrange(256))
                    for _ in range(128 * 96)
                ])
                filename = f"candidate-{split}.jpg"
                path = image_dir / filename
                picture.save(path, format="JPEG", quality=95, subsampling=0)
                record = candidate["splits"][split]["sources"][0]
                record.update(image_fingerprint(path, [128, 96]))
                record["image_size"] = [128, 96]
                record["image_filename"] = filename
            (root / "candidate.json").write_bytes(raw(candidate))
            for n, blob in enumerate(self.old_bytes):
                (root / f"history-{n}.json").write_bytes(blob)
            output = root / "gate.json"
            args = ["--candidate", str(root / "candidate.json"),
                    "--historical", str(root / "history-1.json"),
                    "--historical", str(root / "history-0.json"),
                    "--image-dir", str(image_dir),
                    "--output", str(output)]
            with patch.object(firewall, "PINNED_HISTORIES", self.synthetic_pins):
                self.assertEqual(firewall.main(args), 0)
            receipt = json.loads(output.read_text())
            self.assertEqual(receipt["status"], "pass")
            self.assertEqual(receipt["pinned_history_source_total"], 5)
            self.assertEqual(set(receipt["pinned_history_receipts"]), set(self.synthetic_pins))
            self.assertEqual(receipt["candidate_image_custody"]["checked_images"], 4)
            self.assertTrue(receipt["candidate_image_custody"]["original_bytes_cryptographically_checked"])
            self.assertGreater(receipt["candidate_image_custody"]["source_jpeg_bytes"], 0)

    def test_cli_missing_history_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "candidate.json").write_bytes(raw(self.candidate))
            (root / "history.json").write_bytes(self.old_bytes[0])
            output = root / "gate.json"
            args = ["--candidate", str(root / "candidate.json"),
                    "--historical", str(root / "history.json"),
                    "--output", str(output)]
            with patch.object(firewall, "PINNED_HISTORIES", self.synthetic_pins):
                self.assertEqual(firewall.main(args), 2)
            receipt = json.loads(output.read_text())
            self.assertEqual(receipt["status"], "fail")
            self.assertFalse(receipt["observable_image_identity_disjoint"])

    def test_real_pin_constants_bind_256_and_384_not_mutable_fixtures(self):
        # Do not assert raw JPEG authenticity; only the pinned evidence IDs.
        with patch.object(firewall, "PINNED_HISTORIES", firewall.PINNED_HISTORIES):
            self.assertEqual(
                firewall.PINNED_HISTORIES["hepta.grounded-cohort.v1"]["sha256"],
                "71168c26fffdd913d71a69d8708cec957f55dc2bece112c9c50153fbf31de75d")
            self.assertEqual(
                firewall.PINNED_HISTORIES["hepta.ndu.historical-exclusions.v1"]["sources"],
                384)


if __name__ == "__main__":
    unittest.main()
