"""Adversarial historical-evidence checks; these tests never train a model."""

from contextlib import ExitStack
import copy
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import strong_control_archive as archive


ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "strong-control-evidence" / "attempt-20261106-01"


def replace_json(contents, name, value):
    """Update the outer inventory too, so a test reaches the semantic checks."""
    raw = json.dumps(value, sort_keys=True).encode()
    contents[name] = raw
    inventory = json.loads(contents["INVENTORY.json"])
    for item in inventory:
        if item["path"] == name:
            item.update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    contents["INVENTORY.json"] = json.dumps(inventory).encode()


class StrongControlArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contents, cls.metadata = archive.read_archive(EVIDENCE)

    def verify(self, contents):
        return archive.audit_payload(contents, self.metadata, ROOT)

    def test_preserved_complete_denominator_yields_hold_without_training(self):
        with ExitStack() as stack:
            for target in ("strong_control.run_trial", "strong_control.fit", "strong_control.fit_unsplit",
                           "strong_control.diagnose", "study_model.fit", "study_model.diagnose"):
                stack.enter_context(patch(target, side_effect=AssertionError("training is forbidden in readback")))
            result = self.verify(self.contents)
        self.assertEqual({key: result[key] for key in ("planned_trials", "verified_original_trials",
                                                      "failed_original_trials", "scientific_decision",
                                                      "new_training_updates", "new_trial_executions")},
                         {"planned_trials": 10, "verified_original_trials": 6, "failed_original_trials": 4,
                          "scientific_decision": "HOLD", "new_training_updates": 0, "new_trial_executions": 0})
        self.assertFalse(result["full_campaign_cost_measured"])
        self.assertFalse(result["final_implementation_model_qualified"])

    def test_failed_trial_cannot_be_dropped_even_with_resealed_inventory(self):
        contents = dict(self.contents)
        removed = "actual-01/helpful_specialization-307.json"
        del contents[removed]
        contents["INVENTORY.json"] = json.dumps([item for item in json.loads(contents["INVENTORY.json"])
                                                 if item["path"] != removed]).encode()
        with self.assertRaisesRegex(ValueError, "trial file denominator"):
            self.verify(contents)

    def test_failed_trial_cannot_be_credited_zero_cost(self):
        contents = dict(self.contents)
        name = "actual-01/helpful_specialization-307.json"
        trial = json.loads(contents[name])
        trial["cost"] = 0
        replace_json(contents, name, trial)
        with self.assertRaisesRegex(ValueError, "unknown cost"):
            self.verify(contents)

    def test_hold_cannot_be_promoted_or_authority_granted(self):
        for key, value in (("decision", "RESEARCH_ELIGIBLE"), ("production_authority", True)):
            with self.subTest(key=key):
                contents = dict(self.contents)
                name = "actual-01/SUMMARY.json"
                summary = json.loads(contents[name])
                summary[key] = value
                replace_json(contents, name, summary)
                with self.assertRaisesRegex(ValueError, "HOLD|summary"):
                    self.verify(contents)

    def test_declared_kernel_costs_and_totals_are_recomputed(self):
        for field in ("ledger", "cost"):
            with self.subTest(field=field):
                contents = dict(self.contents)
                name = "actual-01/helpful_specialization-101.json"
                trial = json.loads(contents[name])
                arm = trial["arms"]["unsplit_selective"]
                if field == "ledger":
                    arm["ledger"][1]["estimated_float_ops"] -= 1
                else:
                    arm["cost"]["estimated_float_ops"] -= 1
                replace_json(contents, name, trial)
                with self.assertRaisesRegex(ValueError, "cost quantities|cost summary"):
                    self.verify(contents)

    def test_diagnostic_information_is_replayed_from_saved_models(self):
        contents = dict(self.contents)
        name = "actual-01/helpful_specialization-101.json"
        trial = json.loads(contents[name])
        trial["demand"]["before"]["summary"]["mse"] = 0
        replace_json(contents, name, trial)
        with self.assertRaisesRegex(ValueError, "diagnostic observations"):
            self.verify(contents)

    def test_archive_corruption_is_rejected_before_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for name in ("ARCHIVE.json", "MEMBERS.json", "original-attempt.tar.gz"):
                (directory / name).write_bytes((EVIDENCE / name).read_bytes())
            with (directory / "original-attempt.tar.gz").open("ab") as stream:
                stream.write(b"changed")
            with self.assertRaisesRegex(ValueError, "archive digest"):
                archive.read_archive(directory)

    def test_unsafe_archive_members_are_rejected_without_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            path = directory / "original-attempt.tar.gz"
            with tarfile.open(path, "w:gz") as stream:
                entry = tarfile.TarInfo("../must-not-be-written")
                entry.size = 1
                stream.addfile(entry, io.BytesIO(b"x"))
            members = b"[]"
            (directory / "MEMBERS.json").write_bytes(members)
            metadata = copy.deepcopy(self.metadata)
            metadata.update(archive_sha256=archive.sha256(path.read_bytes()), compressed_bytes=path.stat().st_size,
                            members_sha256=archive.sha256(members))
            (directory / "ARCHIVE.json").write_text(json.dumps(metadata))
            with self.assertRaisesRegex(ValueError, "unsafe"):
                archive.read_archive(directory)
            self.assertFalse((directory.parent / "must-not-be-written").exists())


if __name__ == "__main__":
    unittest.main()
