"""No model or reference data is used in these isolation contract tests."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from cohort_firewall import CohortContractError, check_cohort, load_sources


def image(index, dhash=None):
    return {"source_id": f"coco:val2017:{index}", "task_id": f"task-{index}",
            "image_sha256": hashlib.sha256(f"image-{index}".encode()).hexdigest(),
            "decoded_rgb_sha256": hashlib.sha256(f"rgb-{index}".encode()).hexdigest(),
            "dhash64": f"{int.from_bytes(hashlib.sha256(f'fingerprint-{index}'.encode()).digest()[:8], 'big') if dhash is None else dhash:016x}"}


def manifest(offset=0):
    return {"schema": "hepta.grounded-cohort.v1", "splits": {
        part: {"count": 1, "sources": [image(offset + index)]}
        for index,part in enumerate(("train", "dev", "calibration", "test"))}}


class CohortFirewallTests(unittest.TestCase):
    def setUp(self):
        # 4 bits difference exactly must be blocked at default threshold.
        self.old = manifest(0)
        self.new = manifest(32)

    def test_clean_cohort_passes_without_claiming_entity_independence(self):
        v = check_cohort(self.new, [self.old])
        self.assertEqual(v["status"], "pass")
        self.assertEqual(v["candidate_sources"], 4)
        self.assertEqual(v["historical_sources"], 4)
        self.assertFalse(v["real_world_entity_disjointness_attested"])
        self.assertFalse(v["foundation_pretraining_contamination_excluded"])

    def test_exact_source_id_collision(self):
        v = copy.deepcopy(self.new)
        v["splits"]["train"]["sources"][0]["source_id"] = image(0)["source_id"]
        r = check_cohort(v, [self.old]); self.assertEqual(r["status"], "fail")
        self.assertTrue(any("source_id" in hit["reasons"] for hit in r["violations"]))

    def test_equal_bytes_and_equal_rgb_both_block(self):
        for key in ("image_sha256", "decoded_rgb_sha256"):
            with self.subTest(key=key):
                v = copy.deepcopy(self.new)
                v["splits"]["dev"]["sources"][0][key] = image(1)[key]
                r = check_cohort(v, [self.old]); self.assertEqual(r["status"], "fail")
                self.assertTrue(any(key in hit["reasons"] for hit in r["violations"]))

    def test_hamming_boundary(self):
        v = copy.deepcopy(self.new)
        v["splits"]["train"]["sources"][0]["dhash64"] = f"{int(image(0)['dhash64'],16) ^ 0b1111:016x}"  # distance 4
        self.assertEqual(check_cohort(v, [self.old])["status"], "fail")
        self.assertEqual(check_cohort(v, [self.old], max_hamming=3)["status"], "pass")

    def test_duplicate_inside_candidate(self):
        v = copy.deepcopy(self.new)
        v["splits"]["test"]["sources"][0]["image_sha256"] = v["splits"]["train"]["sources"][0]["image_sha256"]
        self.assertEqual(check_cohort(v, [self.old])["status"], "fail")

    def test_bad_contract_fails_closed(self):
        for bad in [None, {}, {"schema": "bad"}, {"schema": "hepta.grounded-cohort.v1", "splits": {}}]:
            with self.subTest(bad=bad), self.assertRaises(CohortContractError):
                load_sources(bad, "candidate")
        for distance in (-1, 65, 1.2, True):
            with self.subTest(distance=distance), self.assertRaises(CohortContractError):
                check_cohort(self.new, [self.old], max_hamming=distance)
        with self.assertRaises(CohortContractError):
            check_cohort(self.new, [])

    def test_historical_exclusion_wrapper(self):
        prior = image(2)
        prior["image_id"] = 2
        del prior["source_id"]
        wrapper = {"schema": "hepta.ndu.historical-exclusions.v1", "source_sample": {"images": [prior]}}
        result = check_cohort(self.new, [wrapper])
        self.assertEqual(result["status"], "pass")
        duplicate = copy.deepcopy(self.new)
        duplicate["splits"]["train"]["sources"][0]["decoded_rgb_sha256"] = prior["decoded_rgb_sha256"]
        result = check_cohort(duplicate, [wrapper])
        self.assertEqual(result["status"], "fail")

    def test_original_image_id_source_id_mismatch_fails_closed(self):
        mismatched_candidate = copy.deepcopy(self.new)
        mismatched_candidate["splits"]["train"]["sources"][0]["image_id"] = 1
        with self.assertRaisesRegex(CohortContractError, "inconsistent original image_id"):
            check_cohort(mismatched_candidate, [self.old])

        mismatched_history = image(120)
        mismatched_history["image_id"] = 1
        historical = {
            "schema": "hepta.ndu.historical-exclusions.v1",
            "source_sample": {"images": [mismatched_history]},
        }
        with self.assertRaisesRegex(CohortContractError, "inconsistent original image_id"):
            check_cohort(self.new, [historical])

    def test_historical_wrapper_requires_original_image_id_even_with_source_id(self):
        historical = {
            "schema": "hepta.ndu.historical-exclusions.v1",
            "source_sample": {"images": [image(120)]},
        }
        with self.assertRaisesRegex(CohortContractError, "invalid original image_id"):
            check_cohort(self.new, [historical])

    def test_matching_explicit_original_image_identity_still_passes(self):
        prior = image(120)
        prior["image_id"] = 120
        historical = {
            "schema": "hepta.ndu.historical-exclusions.v1",
            "source_sample": {"images": [prior]},
        }
        candidate = copy.deepcopy(self.new)
        candidate["splits"]["train"]["sources"][0]["image_id"] = 32
        self.assertEqual(check_cohort(candidate, [historical])["status"], "pass")

    def test_incomplete_candidate_rejects_cli(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root / "candidate.json").write_text("{}")
            (root / "history.json").write_text(json.dumps(self.old))
            result = subprocess.run([sys.executable, str(Path(__file__).parent / "cohort_firewall.py"),
                         "--candidate", str(root / "candidate.json"),
                         "--historical", str(root / "history.json"),
                         "--output", str(root / "receipt.json")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(json.loads((root / "receipt.json").read_text())["status"], "fail")


if __name__ == "__main__":
    unittest.main()
