"""No model or reference data is used in these isolation contract tests."""

import copy
import hashlib
import json
import os
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

    def test_task_id_aliases_are_rejected_across_and_within_splits(self):
        # A task ID is a score/journal join key, independently of image bytes.
        for first, second in (("train", "dev"), ("train", "test"),
                              ("dev", "calibration"), ("calibration", "test")):
            with self.subTest(first=first, second=second):
                candidate = copy.deepcopy(self.new)
                candidate["splits"][second]["sources"][0]["task_id"] = (
                    candidate["splits"][first]["sources"][0]["task_id"])
                with self.assertRaisesRegex(CohortContractError, "duplicate task_id"):
                    check_cohort(candidate, [self.old])
        candidate = copy.deepcopy(self.new)
        duplicate = image(98765)
        duplicate["task_id"] = candidate["splits"]["train"]["sources"][0]["task_id"]
        candidate["splits"]["train"]["sources"].append(duplicate)
        candidate["splits"]["train"]["count"] = 2
        with self.assertRaisesRegex(CohortContractError, "duplicate task_id"):
            check_cohort(candidate, [self.old])
        historical = copy.deepcopy(self.old)
        historical["splits"]["test"]["sources"][0]["task_id"] = (
            historical["splits"]["train"]["sources"][0]["task_id"])
        with self.assertRaisesRegex(CohortContractError, "duplicate task_id"):
            check_cohort(self.new, [historical])

    def test_noncanonical_task_ids_are_rejected_before_scoring(self):
        for task_id in ("", " ", "two words", " leading", "trailing ",
                        "x\\ny", "a/b", "a" * 129, "🚫", "\\t"):
            with self.subTest(task_id=task_id):
                candidate = copy.deepcopy(self.new)
                candidate["splits"]["test"]["sources"][0]["task_id"] = task_id
                with self.assertRaisesRegex(CohortContractError, "task_id"):
                    check_cohort(candidate, [self.old])
        self.assertEqual(check_cohort(self.new, [self.old])["status"], "pass")

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


    def test_historical_wrapper_malformed_and_identity_mismatch(self):
        for sample in (None, [], 0, {"images": None}):
            with self.subTest(sample=sample), self.assertRaises(CohortContractError):
                load_sources({"schema": "hepta.ndu.historical-exclusions.v1",
                              "source_sample": sample}, "history", historical=True)
        prior = image(17)
        prior["image_id"] = 18
        with self.assertRaisesRegex(CohortContractError, "source_id/image_id mismatch"):
            load_sources({"schema": "hepta.ndu.historical-exclusions.v1",
                          "source_sample": {"images": [prior]}}, "history", historical=True)

    def test_complete_v2_history_rosters_are_required(self):
        with self.assertRaisesRegex(CohortContractError, "requires both"):
            check_cohort(self.new, [self.old], require_complete_history=True)
        v1 = manifest()
        next_id = 0
        for split, count in zip(("train", "dev", "calibration", "test"), (128, 32, 32, 64)):
            v1["splits"][split] = {
                "count": count,
                "sources": [image(next_id + i) for i in range(count)],
            }
            next_id += count
        wrapper = {"schema": "hepta.ndu.historical-exclusions.v1",
                   "source_sample": {"images": [
                       {**image(i + 1000), "image_id": i + 1000}
                       for i in range(384)]}}
        with self.assertRaisesRegex(CohortContractError, "384-source"):
            check_cohort(manifest(10000), [v1, {
                "schema": wrapper["schema"],
                "source_sample": {"images": wrapper["source_sample"]["images"][:383]},
            }], require_complete_history=True)
        result = check_cohort(manifest(10000), [v1, wrapper],
                              require_complete_history=True)
        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["historical_roster_shape_confirmed"])
        self.assertFalse(result["independent_history_trust_established"])
        duplicate = copy.deepcopy(wrapper)
        duplicate["source_sample"]["images"][1] = duplicate["source_sample"]["images"][0]
        with self.assertRaisesRegex(CohortContractError, "duplicate identities"):
            check_cohort(manifest(10000), [v1, duplicate],
                         require_complete_history=True)

    def test_unbounded_candidate_and_comparison_budget_fail_closed(self):
        too_many = manifest(32)
        too_many["splits"]["train"]["sources"] = [image(20000 + i) for i in range(2049)]
        too_many["splits"]["train"]["count"] = 2049
        with self.assertRaisesRegex(CohortContractError, "source limit exceeded"):
            check_cohort(too_many, [self.old])
        # Give each split unique IDs so the comparison-limit test reaches
        # its intended guard instead of the independent task-ID alias guard.
        many = manifest(10000)
        for split_index, split in enumerate(("train", "dev", "calibration", "test")):
            many["splits"][split]["sources"] = [
                image(30000 + 1000 * split_index + i) for i in range(400)]
            many["splits"][split]["count"] = 400
        old = manifest(2000)
        for split_index, split in enumerate(("train", "dev", "calibration", "test")):
            old["splits"][split]["sources"] = [
                image(40000 + 1000 * split_index + i) for i in range(400)]
            old["splits"][split]["count"] = 400
        with self.assertRaisesRegex(CohortContractError, "comparison budget"):
            check_cohort(many, [old])

    @unittest.skipUnless(hasattr(os, "mkfifo") and hasattr(os, "O_NONBLOCK"),
                         "POSIX FIFO tests require nonblocking file opens")
    def test_cli_refuses_fifo_without_waiting_for_writer(self):
        # Regression: Path.read_bytes() on an unguarded FIFO can hang forever.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.mkfifo(root / "candidate.fifo")
            raw = json.dumps(self.old).encode()
            (root / "history.json").write_bytes(raw)
            args = [sys.executable, str(Path(__file__).parent / "cohort_firewall.py"),
                    "--candidate", str(root / "candidate.fifo"),
                    "--historical", str(root / "history.json"),
                    "--historical-sha256", hashlib.sha256(raw).hexdigest(),
                    "--output", str(root / "receipt.json")]
            try:
                result = subprocess.run(args, capture_output=True, text=True,
                                        timeout=5)
            except subprocess.TimeoutExpired:
                self.fail("a special input file blocked the firewall process")
            self.assertEqual(result.returncode, 2, result.stderr)
            receipt = json.loads((root / "receipt.json").read_text())
            self.assertEqual(receipt["status"], "fail")
            self.assertIn("regular cohort manifest file required", receipt["error"])

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW") and hasattr(os, "symlink"),
                         "no-follow open is unavailable on this platform")
    def test_cli_does_not_follow_mutable_manifest_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "real.json").write_text(json.dumps(self.new))
            (root / "alias.json").symlink_to(root / "real.json")
            raw = json.dumps(self.old).encode()
            (root / "history.json").write_bytes(raw)
            args = [sys.executable, str(Path(__file__).parent / "cohort_firewall.py"),
                    "--candidate", str(root / "alias.json"),
                    "--historical", str(root / "history.json"),
                    "--historical-sha256", hashlib.sha256(raw).hexdigest(),
                    "--output", str(root / "receipt.json")]
            result = subprocess.run(args, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(json.loads((root / "receipt.json").read_text())["status"],
                             "fail")

    def test_cli_refuses_unpinned_or_incomplete_history(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "candidate.json").write_text(json.dumps(self.new))
            raw = json.dumps(self.old).encode()
            (root / "history.json").write_bytes(raw)
            base = [sys.executable, str(Path(__file__).parent / "cohort_firewall.py"),
                    "--candidate", str(root / "candidate.json"),
                    "--historical", str(root / "history.json"),
                    "--output", str(root / "receipt.json")]
            for extra, expected_error in [
                ([], "out-of-band SHA256"),
                (["--historical-sha256", "0" * 64], "historical SHA256 mismatch"),
                (["--historical-sha256", hashlib.sha256(raw).hexdigest()],
                 "requires both"),
            ]:
                result = subprocess.run(base + extra, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, result.stderr)
                receipt = json.loads((root / "receipt.json").read_text())
                self.assertEqual(receipt["status"], "fail")
                self.assertIn(expected_error, receipt["error"])


if __name__ == "__main__":
    unittest.main()
