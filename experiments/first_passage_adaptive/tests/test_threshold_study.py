"""Identity and once-only opening tests using artificial data, never held-out seeds."""

import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments.first_passage_adaptive import threshold_study as study


class ThresholdStudyTest(unittest.TestCase):
    def test_checkpoint_rejects_identity_drift(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name)/"checkpoint.json"
            study.write_new(path, {"schema": "hepta.first-passage.threshold.checkpoint.v1",
                "source_identity": {"version": 1}, "study_id": "synthetic"})
            with patch.object(study, "identity", return_value={"version": 2}), \
                 patch.object(study, "load_protocol", return_value={"study_id": "synthetic"}):
                with self.assertRaisesRegex(ValueError, "identity"):
                    study.load_checkpoint(path)

    def test_checkpoint_rejects_missing_or_repeated_registered_fits(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name)/"checkpoint.json"
            study.write_new(path, {"schema": "hepta.first-passage.threshold.checkpoint.v1",
                "source_identity": {"version": 1}, "study_id": "synthetic",
                "fits": [{"fit_seed": 1}, {"fit_seed": 1}, {"fit_seed": 3}]})
            with patch.object(study, "identity", return_value={"version": 1}), \
                 patch.object(study, "load_protocol", return_value={
                     "study_id": "synthetic", "threshold_study": {"fit_seeds": [1, 2, 3]}}):
                with self.assertRaisesRegex(ValueError, "registered ordered"):
                    study.load_checkpoint(path)

    def test_copied_freeze_cannot_reopen_failed_confirmation(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            checkpoint, frozen = root/"model.json", root/"freeze.json"
            study.write_new(checkpoint, {"synthetic": True})
            identity = {"source": "artificial-only"}
            saved = {"study_id": "synthetic-study", "fits": [{"fit_seed": 1}]}
            protocol = {"study_id": saved["study_id"], "threshold_study": {"artificial": True}}
            study.write_new(frozen, {"schema": "hepta.first-passage.threshold.freeze.v1",
                "study_id": saved["study_id"], "source_identity": identity,
                "checkpoint_sha256": study.digest(checkpoint),
                "configuration": protocol["threshold_study"]})
            with patch.object(study, "CONFIRMATION_REGISTRY", root/"registry"), \
                 patch.object(study, "load_checkpoint", return_value=saved), \
                 patch.object(study, "load_protocol", return_value=protocol), \
                 patch.object(study, "identity", return_value=identity), \
                 patch.object(study, "evaluate_seed", side_effect=RuntimeError("artificial failure")) as evaluator:
                with self.assertRaisesRegex(RuntimeError, "artificial failure"):
                    study.confirm(checkpoint, frozen, root/"first")
                copied = root/"copied-freeze.json"
                copied.write_bytes(frozen.read_bytes())
                with self.assertRaises(FileExistsError):
                    study.confirm(checkpoint, copied, root/"second")
                self.assertEqual(evaluator.call_count, 1)
                self.assertTrue((root/"first/failure.json").exists())
                self.assertFalse((root/"second").exists())

    def test_compressed_raw_evidence_is_complete_and_nonoverwriting(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name)/"raw.jsonl.gz"
            with study.compressed_writer(path) as handle:
                handle.write(json.dumps({"record": [1, 2, 3]})+"\n")
            with gzip.open(path, "rt") as handle:
                self.assertEqual(json.loads(handle.read()), {"record": [1, 2, 3]})
            with self.assertRaises(FileExistsError):
                with study.compressed_writer(path):
                    pass


if __name__ == "__main__":
    unittest.main()
