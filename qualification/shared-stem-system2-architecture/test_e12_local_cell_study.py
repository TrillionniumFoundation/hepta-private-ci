"""Independent original-arithmetic replay of sealed oracle-free Cell solvers."""

from hashlib import sha256
from pathlib import Path
import json
import tempfile
import unittest

from e12_local_cell_study import produce, review
from e12_study import read_strict, write_once


class LocalCellStudyTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)
        self.raw = self.path / "local.json"
        self.reviewed = self.path / "review.json"
        self.digest = produce(str(self.raw))

    def _corrupt(self, callback):
        obj = json.loads(self.raw.read_text())
        callback(obj)
        path = self.path / f"candidate-{len(tuple(self.path.iterdir()))}.json"
        return path, write_once(str(path), obj)

    def test_all_six_no_oracle_cases_independently_replayed(self):
        review_sha = review(str(self.raw), self.digest, str(self.reviewed))
        self.assertEqual(review_sha, sha256(self.reviewed.read_bytes()).hexdigest())
        item, _ = read_strict(str(self.reviewed))
        self.assertTrue(item["complete_source_roster_verified"])
        self.assertTrue(item["producer_local_messages_replayed_independently"])
        self.assertEqual(len(item["decisions"]), 6)
        self.assertFalse(item["online_reasoning_gain_proven"])
        self.assertFalse(item["production_accepted"])
        self.assertEqual(item["authority"], "DENY_ALL")

    def test_reject_wrong_seal_and_never_write_review(self):
        with self.assertRaises(ValueError):
            review(str(self.raw), "0" * 64, str(self.reviewed))
        self.assertFalse(self.reviewed.exists())

    def test_reject_forged_local_iteration_and_adversarial_residual(self):
        for modify in (
            lambda x: x["cases"][5]["iterations"][0].__setitem__("global_bound", "0"),
            lambda x: x["cases"][5]["iterations"][0].__setitem__("accepted", True),
            lambda x: x["cases"][5]["iterations"].pop(),
            lambda x: x["cases"][5].__setitem__("physical_forward_cells", 0),
        ):
            path, digest = self._corrupt(modify)
            with self.subTest(path=path), self.assertRaises(ValueError):
                review(str(path), digest, str(self.reviewed))

    def test_reject_wrong_z_value_and_source_model_identity(self):
        for modify in (
            lambda x: x["cases"][5]["boundary"]["segments"][0].__setitem__("z", "0"),
            lambda x: x["cases"][0]["solution"]["trace"]["states"][0].__setitem__("x", "0"),
            lambda x: x["cases"][2]["boundary"].__setitem__("scope_digest", "a" * 64),
        ):
            path, digest = self._corrupt(modify)
            with self.subTest(path=path), self.assertRaises(ValueError):
                review(str(path), digest, str(self.reviewed))

    def test_reject_missing_reordered_profiles_and_false_authority(self):
        for modify in (
            lambda x: x["cases"].pop(),
            lambda x: x["cases"].reverse(),
            lambda x: x.__setitem__("production_accepted", True),
            lambda x: x.__setitem__("original_global_solver_calls", 1),
            lambda x: x["cases"][4].__setitem__("reference_operator_calls", 1),
        ):
            path, digest = self._corrupt(modify)
            with self.subTest(path=path), self.assertRaises(ValueError):
                review(str(path), digest, str(self.reviewed))

    def test_create_only_guard_and_overwrite_denial(self):
        with self.assertRaises(FileExistsError):
            produce(str(self.raw))
        review(str(self.raw), self.digest, str(self.reviewed))
        with self.assertRaises(FileExistsError):
            review(str(self.raw), self.digest, str(self.reviewed))


if __name__ == "__main__":
    unittest.main()
