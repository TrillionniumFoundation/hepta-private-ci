"""Tamper-resistant postrun checks; fixtures are not new model inference."""

from pathlib import Path
import hashlib
import os
import tempfile
import unittest
import zipfile

from locomo_publisher_completion_receipt import (
    EXPECTED,
    REFUSAL,
    audit,
    read_archive,
    refusal_shape,
    sha,
    strict_json,
)


class PostrunReceiptTests(unittest.TestCase):
    def test_exact_refusal_is_not_mixed_explanation(self):
        self.assertEqual(refusal_shape(REFUSAL), "strict_refusal")
        self.assertEqual(refusal_shape(" " + REFUSAL + "\n"), "strict_refusal")

    def test_mixed_refusal_is_never_strict(self):
        self.assertEqual(
            refusal_shape(REFUSAL + " [E1] says something"),
            "mixed_refusal_and_extra_text",
        )
        self.assertEqual(
            refusal_shape("[E1] claims success. " + REFUSAL),
            "mixed_refusal_and_extra_text",
        )

    def test_nonrefusal_and_empty(self):
        self.assertEqual(refusal_shape("a citation [E1]"), "no_canonical_refusal")
        with self.assertRaises(ValueError):
            refusal_shape("  ")

    def test_duplicate_json_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            strict_json('{"id":1,"id":2}')

    def test_nonfinite_json_rejected(self):
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            strict_json('{"result":NaN}')

    def test_outer_sha_change_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "raw.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("row.json", b"{}")
            with self.assertRaisesRegex(ValueError, "ZIP SHA"):
                read_archive(archive, "f" * 64, has_manifest=False)

    def test_archive_duplicate_and_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "unsafe.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("../unsafe.json", b"{}")
            with self.assertRaisesRegex(ValueError, "unsafe"):
                read_archive(archive, sha(archive.read_bytes()), has_manifest=False)
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("same.json", b"{}")
                z.writestr("same.json", b"{}")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                read_archive(archive, sha(archive.read_bytes()), has_manifest=False)

    def test_manifest_must_list_complete_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "reader.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("real.json", b"{}")
                z.writestr("SHA256SUMS", b"")
            with self.assertRaisesRegex(ValueError, "integrity"):
                read_archive(archive, sha(archive.read_bytes()), has_manifest=True)

    def test_immutable_real_16_when_three_zips_supplied(self):
        root = os.environ.get("HEPTA_LOCOMO_PUBLISHER_POSTRUN_ARCHIVES")
        if not root:
            self.skipTest("original three GitHub Actions artifact ZIPs not staged")
        path = Path(root)
        result = audit(
            path / "locomo-publisher-ids-20261013.zip",
            path / "locomo-publisher-raw-20261013.zip",
            path / "locomo-publisher-diagnostic-20261013.zip",
        )
        self.assertEqual(result["original_model_calls"], 16)
        self.assertEqual(result["original_input_tokens"], 3427)
        self.assertEqual(result["original_generated_tokens"], 675)
        self.assertEqual(result["answers_with_delivered_citation_label"], 14)
        self.assertEqual(
            sum(
                x["mixed_refusal_and_extra_text"]
                for x in result["refusal_shapes_by_mode"].values()
            ),
            5,
        )
        self.assertEqual(result["matched_public_family_proxies"], 2)
        self.assertTrue(result["publisher_source_selection_is_privileged"])
        self.assertFalse(result["production_accepted"])
        self.assertEqual(set(result["exact_zip_sha256"]), set(EXPECTED))


if __name__ == "__main__":
    unittest.main()
