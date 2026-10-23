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
from unittest import mock

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

    def test_candidate_task_key_must_not_alias_historical_cohort(self):
        candidate = copy.deepcopy(self.new)
        candidate["splits"]["dev"]["sources"][0]["task_id"] = (
            self.old["splits"]["train"]["sources"][0]["task_id"])
        self.assertNotEqual(
            candidate["splits"]["dev"]["sources"][0]["source_id"],
            self.old["splits"]["train"]["sources"][0]["source_id"])
        self.assertNotEqual(
            candidate["splits"]["dev"]["sources"][0]["image_sha256"],
            self.old["splits"]["train"]["sources"][0]["image_sha256"])
        with self.assertRaisesRegex(CohortContractError, "candidate task_id aliases historical"):
            check_cohort(candidate, [self.old])

    def test_historical_task_keys_must_be_unique_across_manifests(self):
        other = manifest(20000)
        other["splits"]["test"]["sources"][0]["task_id"] = (
            self.old["splits"]["train"]["sources"][0]["task_id"])
        self.assertNotEqual(
            other["splits"]["test"]["sources"][0]["source_id"],
            self.old["splits"]["train"]["sources"][0]["source_id"])
        with self.assertRaisesRegex(CohortContractError, "duplicate task_id across historical"):
            check_cohort(self.new, [self.old, other])

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
        aliased_candidate = manifest(10000)
        aliased_candidate["splits"]["test"]["sources"][0]["task_id"] = (
            v1["splits"]["train"]["sources"][0]["task_id"])
        with self.assertRaisesRegex(CohortContractError, "candidate task_id aliases historical"):
            check_cohort(aliased_candidate, [v1, wrapper],
                         require_complete_history=True)
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
        many = manifest(10000)
        for split in ("train", "dev", "calibration", "test"):
            many["splits"][split]["sources"] = [
                image(30000 + 1000 * n + i)
                for n, i in enumerate(range(400))]
            many["splits"][split]["count"] = 400
        old = manifest(2000)
        for split in ("train", "dev", "calibration", "test"):
            old["splits"][split]["sources"] = [
                image(40000 + 1000 * n + i)
                for n, i in enumerate(range(400))]
            old["splits"][split]["count"] = 400
        with self.assertRaisesRegex(CohortContractError, "comparison budget"):
            check_cohort(many, [old])

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

    def test_cli_refuses_direct_frozen_input_output_aliases(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candidate = root / "candidate.json"
            history = root / "history.json"
            candidate.write_text(json.dumps(self.new))
            history.write_text(json.dumps(self.old))
            original_candidate = candidate.read_bytes()
            original_history = history.read_bytes()
            args = [sys.executable, str(Path(__file__).parent / "cohort_firewall.py"),
                    "--candidate", str(candidate),
                    "--historical", str(history),
                    "--historical-sha256", hashlib.sha256(original_history).hexdigest(),
                    "--output"]
            for destination in (candidate, history):
                with self.subTest(destination=destination.name):
                    result = subprocess.run(args + [str(destination)],
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    denial = json.loads(result.stdout)
                    self.assertEqual(denial["status"], "fail")
                    self.assertFalse(denial["output_written"])
                    self.assertIn("aliases frozen input", denial["error"])
                    self.assertEqual(candidate.read_bytes(), original_candidate)
                    self.assertEqual(history.read_bytes(), original_history)

    def test_cli_refuses_symlink_and_hardlink_output_targets(self):
        if sys.platform == "win32":
            self.skipTest("symlink fixture requires a POSIX host")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candidate = root / "candidate.json"
            history = root / "history.json"
            candidate.write_text(json.dumps(self.new))
            history.write_text(json.dumps(self.old))
            original = history.read_bytes()
            alias = root / "receipt.json"
            args = [sys.executable, str(Path(__file__).parent / "cohort_firewall.py"),
                    "--candidate", str(candidate),
                    "--historical", str(history),
                    "--historical-sha256", hashlib.sha256(original).hexdigest(),
                    "--output", str(alias)]
            alias.symlink_to(history)
            denied = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(denied.returncode, 2, denied.stderr)
            self.assertIn("symlink", json.loads(denied.stdout)["error"])
            self.assertEqual(history.read_bytes(), original)
            alias.unlink()
            alias.hardlink_to(history)
            denied = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(denied.returncode, 2, denied.stderr)
            self.assertIn("unlinked regular file", json.loads(denied.stdout)["error"])
            self.assertEqual(history.read_bytes(), original)

    def test_cli_refuses_output_alias_through_symlinked_directory(self):
        if sys.platform == "win32":
            self.skipTest("symlink fixture requires a POSIX host")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candidate = root / "candidate.json"
            history = root / "history.json"
            candidate.write_text(json.dumps(self.new))
            history.write_text(json.dumps(self.old))
            before = candidate.read_bytes()
            (root / "alias-dir").symlink_to(root, target_is_directory=True)
            denied = subprocess.run(
                [sys.executable, str(Path(__file__).parent / "cohort_firewall.py"),
                 "--candidate", str(candidate),
                 "--historical", str(history),
                 "--historical-sha256", hashlib.sha256(history.read_bytes()).hexdigest(),
                 "--output", str(root / "alias-dir" / "candidate.json")],
                capture_output=True, text=True,
            )
            self.assertEqual(denied.returncode, 2, denied.stderr)
            self.assertIn("aliases frozen input", json.loads(denied.stdout)["error"])
            self.assertEqual(candidate.read_bytes(), before)

    def test_cli_still_writes_separate_denial_receipts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candidate = root / "candidate.json"
            history = root / "history.json"
            destination = root / "receipt.json"
            candidate.write_text("{}")
            history.write_text("{}")
            before = (candidate.read_bytes(), history.read_bytes())
            args = [sys.executable, str(Path(__file__).parent / "cohort_firewall.py"),
                    "--candidate", str(candidate),
                    "--historical", str(history),
                    "--historical-sha256", hashlib.sha256(before[1]).hexdigest(),
                    "--output", str(destination)]
            for _ in range(2):
                denied = subprocess.run(args, capture_output=True, text=True)
                self.assertEqual(denied.returncode, 2, denied.stderr)
                self.assertEqual(json.loads(destination.read_text())["status"], "fail")
                self.assertEqual((candidate.read_bytes(), history.read_bytes()), before)


    @unittest.skipUnless(os.name == "posix", "requires a POSIX named pipe")
    def test_cli_rejects_unopened_candidate_fifo_without_blocking(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fifo = root / "candidate.fifo"
            os.mkfifo(fifo)
            history = root / "history.json"
            history.write_text(json.dumps(self.old))
            output = root / "denial.json"
            result = subprocess.run(
                [sys.executable, str(Path(__file__).parent / "cohort_firewall.py"),
                 "--candidate", str(fifo),
                 "--historical", str(history),
                 "--historical-sha256", hashlib.sha256(history.read_bytes()).hexdigest(),
                 "--output", str(output)],
                capture_output=True, text=True, timeout=3,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("regular file", json.loads(output.read_text())["error"])

    @unittest.skipUnless(os.name == "posix", "requires a POSIX named pipe")
    def test_cli_rejects_unopened_historical_fifo_without_blocking(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candidate = root / "candidate.json"
            candidate.write_text(json.dumps(self.new))
            fifo = root / "history.fifo"
            os.mkfifo(fifo)
            output = root / "denial.json"
            result = subprocess.run(
                [sys.executable, str(Path(__file__).parent / "cohort_firewall.py"),
                 "--candidate", str(candidate),
                 "--historical", str(fifo),
                 "--historical-sha256", "0" * 64,
                 "--output", str(output)],
                capture_output=True, text=True, timeout=3,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("regular file", json.loads(output.read_text())["error"])

    def test_cli_rejects_oversized_sparse_cohort_before_full_read(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candidate = root / "candidate.json"
            with candidate.open("wb") as handle:
                handle.truncate(16 * 1024 * 1024 + 1)
            history = root / "history.json"
            history.write_text(json.dumps(self.old))
            output = root / "denial.json"
            result = subprocess.run(
                [sys.executable, str(Path(__file__).parent / "cohort_firewall.py"),
                 "--candidate", str(candidate),
                 "--historical", str(history),
                 "--historical-sha256", hashlib.sha256(history.read_bytes()).hexdigest(),
                 "--output", str(output)],
                capture_output=True, text=True, timeout=3,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("byte limit", json.loads(output.read_text())["error"])


    @unittest.skipUnless(os.name == "posix", "link-race tests require POSIX")
    def test_cli_atomic_receipt_does_not_follow_late_link_swap(self):
        # Reproduce a path replacement after all validation but before publish.
        # A direct Path.write_text call would overwrite the protected input.
        from cohort_firewall import main
        for alias_kind in ("symlink", "hardlink"):
            with self.subTest(alias=alias_kind), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                candidate = root / "candidate.json"
                history = root / "history.json"
                destination = root / "receipt.json"
                candidate.write_text("{}")  # Intentionally invalid cohort.
                history.write_text("{}")
                original_candidate = candidate.read_bytes()
                original_history = history.read_bytes()
                real_replace = os.replace

                def swap_late(temporary, target):
                    self.assertEqual(Path(target), destination)
                    if alias_kind == "symlink":
                        destination.symlink_to(candidate)
                    else:
                        destination.hardlink_to(candidate)
                    return real_replace(temporary, target)

                args = ["--candidate", str(candidate),
                        "--historical", str(history),
                        "--historical-sha256", hashlib.sha256(original_history).hexdigest(),
                        "--output", str(destination)]
                with mock.patch("cohort_firewall.os.replace", side_effect=swap_late) as patched:
                    status = main(args)
                self.assertEqual(status, 2)
                self.assertEqual(patched.call_count, 1)
                self.assertEqual(candidate.read_bytes(), original_candidate)
                self.assertEqual(history.read_bytes(), original_history)
                self.assertFalse(destination.is_symlink())
                self.assertEqual(json.loads(destination.read_text())["status"], "fail")



if __name__ == "__main__":
    unittest.main()
