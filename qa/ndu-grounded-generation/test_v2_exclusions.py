"""Model-free positive/negative controls for the pinned v2 source exclusion assembler."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from v2_exclusions import (ExclusionError, EXPECTED_SPLITS, build_registry,
                           create, digest, _json_bytes)


def mock_input():
    def entry(i, historical=False):
        row = {"image_id": i,
               "image_sha256": digest(f"image{i}".encode()),
               "decoded_rgb_sha256": digest(f"rgb{i}".encode()),
               "dhash64": digest(f"dhash{i}".encode())[:16]}
        if not historical:
            row["source_id"] = f"coco:val2017:{i}"
        return row
    historical = {"schema": "hepta.ndu.historical-exclusions.v1",
                  "source_sample": {"images": [entry(i, True) for i in range(384)]}}
    offset, splits = 384, {}
    for split, count in EXPECTED_SPLITS.items():
        splits[split] = {"count": count, "sources": [entry(i) for i in range(offset, offset + count)]}
        offset += count
    cohort = {"schema": "hepta.grounded-cohort.v1", "splits": splits}
    return historical, cohort


class V2SourceExclusionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.historical, cls.cohort = mock_input()

    def test_all_640_inputs_and_compatible_wrapper(self):
        receipt = build_registry(self.historical, self.cohort)
        self.assertEqual(receipt["schema"], "hepta.ndu.historical-exclusions.v1")
        self.assertEqual(len(receipt["source_sample"]["images"]), 640)
        self.assertEqual([r["image_id"] for r in receipt["source_sample"]["images"]], list(range(640)))
        self.assertFalse(receipt["provenance"]["real_world_entity_disjointness_proven"])

    def test_byte_determinism_and_existing_destination(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            hfile, vfile, outfile = (path / p for p in ("historical.json", "v1.json", "combined.json"))
            hfile.write_bytes(_json_bytes(self.historical))
            vfile.write_bytes(_json_bytes(self.cohort))
            with patch("v2_exclusions.HISTORICAL_SHA256", digest(hfile.read_bytes())), patch(
                "v2_exclusions.V1_MANIFEST_SHA256", digest(vfile.read_bytes())
            ):
                first = create(hfile, vfile, outfile)
                second = create(hfile, vfile, outfile)
                self.assertEqual(first["exclusion_sha256"], second["exclusion_sha256"])
                outfile.write_text("tampered")
                with self.assertRaisesRegex(ExclusionError, "refuse to replace"):
                    create(hfile, vfile, outfile)

    def test_frozen_input_pin_detects_tampering(self):
        with tempfile.TemporaryDirectory() as root:
            a, b, out = (Path(root) / name for name in ("h.json", "v.json", "out.json"))
            a.write_bytes(_json_bytes(self.historical)); b.write_bytes(_json_bytes(self.cohort))
            with self.assertRaisesRegex(ExclusionError, "SHA256 mismatch"):
                create(a, b, out)
            self.assertFalse(out.exists())

    def test_previous_original_image_reuse_rejected(self):
        a, b = mock_input()
        b["splits"]["test"]["sources"][0]["image_id"] = 0
        b["splits"]["test"]["sources"][0]["source_id"] = "coco:val2017:0"
        with self.assertRaisesRegex(ExclusionError, "overlap"):
            build_registry(a, b)

    def test_same_image_bytes_under_different_id_rejected(self):
        a, b = mock_input()
        b["splits"]["dev"]["sources"][0]["image_sha256"] = a["source_sample"]["images"][1]["image_sha256"]
        with self.assertRaisesRegex(ExclusionError, "overlap"):
            build_registry(a, b)

    def test_near_duplicate_dhash_rejected(self):
        a, b = mock_input()
        b["splits"]["dev"]["sources"][0]["dhash64"] = a["source_sample"]["images"][1]["dhash64"]
        with self.assertRaisesRegex(ExclusionError, "near-duplicate"):
            build_registry(a, b)

    def test_wrong_source_identity_rejected(self):
        a, b = mock_input()
        b["splits"]["train"]["sources"][0]["source_id"] = "coco:val2017:other"
        with self.assertRaisesRegex(ExclusionError, "disagree"):
            build_registry(a, b)

    def test_incomplete_old_384_rejected(self):
        a, b = mock_input()
        a["source_sample"]["images"].pop()
        with self.assertRaisesRegex(ExclusionError, "384"):
            build_registry(a, b)

    def test_incomplete_v1_split_rejected(self):
        a, b = mock_input()
        b["splits"]["test"]["sources"].pop()
        with self.assertRaisesRegex(ExclusionError, "test"):
            build_registry(a, b)

    def test_missing_split_rejected(self):
        a, b = mock_input()
        b["splits"].pop("dev")
        with self.assertRaisesRegex(ExclusionError, "four"):
            build_registry(a, b)

    def test_forged_sha_rejected(self):
        a, b = mock_input()
        b["splits"]["dev"]["sources"][0]["image_sha256"] = "not-a-hash"
        with self.assertRaisesRegex(ExclusionError, "image_sha256"):
            build_registry(a, b)

    def test_duplicate_threshold_boundary(self):
        a, b = mock_input()
        h = int(a["source_sample"]["images"][0]["dhash64"], 16)
        b["splits"]["train"]["sources"][0]["dhash64"] = f"{h ^ 15:016x}"
        with self.assertRaisesRegex(ExclusionError, "near-duplicate"):
            build_registry(a, b)

    def test_boolean_image_id_rejected(self):
        a, b = mock_input()
        b["splits"]["train"]["sources"][0]["image_id"] = True
        with self.assertRaisesRegex(ExclusionError, "invalid original"):
            build_registry(a, b)


if __name__ == "__main__":
    unittest.main()
