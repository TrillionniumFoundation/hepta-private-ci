"""Qualification observes the actual closed-loop mode and keeps labels outside it."""
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

import torch

import test_revision_training as fixtures
from retention_feedback import feedback_panel


class RetentionFeedbackTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.fixture = fixtures.RevisionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        ids = {c.case_id: i for i, c in enumerate(self.fixture.cases)}
        self.bank = SimpleNamespace(batch=lambda cases: self.fixture.binding.take(
            [ids[c.case_id] for c in cases]))

    def panel(self, mode, cases=None, binding=True):
        f = self.fixture
        root = Path(f.temp.name)
        feedback_panel(root, mode, f.core, f.verifier, f.provenance,
                       f.cases if cases is None else cases, self.bank, mode, binding=binding)
        return json.loads((root / (mode+".json")).read_text())

    def test_real_qualification_executes_and_consumes_actual_verifier_feedback(self):
        record = self.panel("real")
        execution = record["physical_batches"][0]["execution"]
        self.assertEqual(execution["cost"]["calls"],
            dict(reader_prepare=1, reader_step=3, verifier_prepare=1, verifier_step=2))
        consumed = [row["feedback"] for row in execution["events"] if row["step"] == 2]
        self.assertTrue(all(value is not None and sum(value[:2]) > .99 for value in consumed))
        self.assertTrue(all(row["feedback"] is None for row in execution["events"] if row["step"] == 1))

    def test_zero_mode_matches_core_and_scoring_labels_never_change_execution(self):
        f = self.fixture
        original = f.core(*f.binding.features(), steps=3).softmax(-1)[:, 1].tolist()
        record = self.panel("zero", binding=False)
        self.assertEqual(record["probabilities"], original)
        changed = self.panel("zero", tuple(replace(c, label=1-c.label) for c in f.cases), binding=False)
        self.assertEqual(changed["probabilities"], original)
        self.assertNotEqual(record["metrics"]["probability_CE"], changed["metrics"]["probability_CE"])
        self.assertEqual(record["physical_batches"][0]["execution"]["cost"]["calls"],
                         changed["physical_batches"][0]["execution"]["cost"]["calls"])


if __name__ == "__main__":
    unittest.main()
