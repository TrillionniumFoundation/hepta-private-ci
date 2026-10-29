import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments.first_passage_adaptive import adaptive_study as study


class SourceBoundStudyTests(unittest.TestCase):
    def fixture(self, directory):
        checkpoint,development = directory/"checkpoint.json",directory/"development.json"
        saved = {"schema":"hepta.first-passage.adaptive.checkpoint.v1",
                 "study_id":study.protocol()["study_id"],"source_identity":study.identity(),
                 "physical_training":{"final":[.2,.8,.4]},"meta_training":{"final":[.4,.9,.45]},
                 "training_complete":True,"confirmation_opened":False}
        study.write_new(checkpoint,saved)
        study.write_new(development,{"split":"development","source_identity":study.identity(),
                                     "checkpoint_sha256":study.digest(checkpoint)})
        return checkpoint,development

    def test_source_changed_since_checkpoint_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint,_ = self.fixture(Path(temporary))
            saved = json.loads(checkpoint.read_text())
            saved["source_identity"]["source_sha256"]["gradients.py"] = "0"*64
            checkpoint.write_text(json.dumps(saved))
            with self.assertRaisesRegex(ValueError,"identity mismatch"):
                study.load_checkpoint(checkpoint)

    def test_model_tampering_after_freeze_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            checkpoint,development = self.fixture(directory)
            frozen = directory/"freeze.json"
            study.freeze(checkpoint,development,frozen)
            saved = json.loads(checkpoint.read_text())
            saved["meta_training"]["final"][0] += .1
            checkpoint.write_text(json.dumps(saved))
            registry = directory/"registry"
            with patch.object(study,"CONFIRMATION_REGISTRY",registry):
                with self.assertRaisesRegex(ValueError,"freeze mismatch"):
                    study.confirm(checkpoint,frozen,directory/"confirmation")
            self.assertFalse(registry.exists())

    def test_confirmation_opens_once_even_with_different_output_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            checkpoint,development = self.fixture(directory)
            frozen = directory/"freeze.json"
            study.freeze(checkpoint,development,frozen)
            with patch.object(study,"CONFIRMATION_REGISTRY",directory/"registry"):
                with patch.object(study,"evaluate",return_value={"split":"confirmation"}) as evaluate:
                    study.confirm(checkpoint,frozen,directory/"first")
                    copied = directory/"copied-freeze.json"
                    copied.write_bytes(frozen.read_bytes())
                    with self.assertRaises(FileExistsError):
                        study.confirm(checkpoint,copied,directory/"second")
                    self.assertEqual(evaluate.call_count,1)

    def test_failed_confirmation_retains_failure_and_consumes_opening(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            checkpoint,development = self.fixture(directory)
            frozen = directory/"freeze.json"
            study.freeze(checkpoint,development,frozen)
            with patch.object(study,"CONFIRMATION_REGISTRY",directory/"registry"):
                with patch.object(study,"evaluate",side_effect=ArithmeticError("numerical failure")):
                    with self.assertRaises(ArithmeticError):
                        study.confirm(checkpoint,frozen,directory/"failed")
                self.assertTrue((directory/"failed"/"failure.json").is_file())
                with self.assertRaises(FileExistsError):
                    study.confirm(checkpoint,frozen,directory/"retry")


if __name__ == "__main__":
    unittest.main()
