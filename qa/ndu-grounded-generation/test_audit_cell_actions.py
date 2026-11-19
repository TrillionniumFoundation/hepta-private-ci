"""Synthetic adversarial checks for the frozen-v1 journal-only audit."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from audit_cell_actions import ACTIONS, METHODS, audit_pinned_journal, audit_rows


def fixture():
    rows = []
    for method in sorted(METHODS):
        c = {"action": 2, "checkpoint_changed": True, "modifier_applied": True,
             "weights": list(ACTIONS[2][1]), "argmax_changed": True,
             "base_argmax": 11, "controlled_argmax": 12}
        rows.append({"task_id": "task-a", "method": method, "seed": 23,
                     "split": "test", "budget_cap": 10.0, "budget_unit": "wall_seconds",
                     "score": {"task_id": "task-a", "method": method, "quality": .75},
                     "termination": "completed", "controls": [c] if method == "ndu" else []})
    return rows


class ActionAuditTests(unittest.TestCase):
    def test_good_roster_is_non_authorizing(self):
        result = audit_rows(fixture(), expected_sources=1)
        self.assertEqual(result["ndu_decisions_total"], 1)
        self.assertEqual(result["actions"]["vocab_cell"]["argmax_changes"], 1)
        self.assertFalse(result["scientific_authorization"])
        self.assertFalse(result["four_cell_cooperation_or_synergy_proven"])

    def test_missing_arm_rejected(self):
        with self.assertRaisesRegex(ValueError, "roster"):
            audit_rows(fixture()[:-1], expected_sources=1)

    def test_duplicate_arm_rejected(self):
        rows = fixture()
        rows[0] = copy.deepcopy(rows[1])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            audit_rows(rows, expected_sources=1)

    def test_invalid_action_weights_rejected(self):
        rows = fixture()
        c = next(r for r in rows if r["method"] == "ndu")["controls"][0]
        c["weights"] = [0.25] * 4
        with self.assertRaisesRegex(ValueError, "action/weights"):
            audit_rows(rows, expected_sources=1)

    def test_forged_argmax_flag_rejected(self):
        rows = fixture()
        c = next(r for r in rows if r["method"] == "ndu")["controls"][0]
        c["argmax_changed"] = False
        with self.assertRaisesRegex(ValueError, "argmax identity"):
            audit_rows(rows, expected_sources=1)

    def test_forged_inactive_switch_rejected(self):
        rows = fixture()
        c = next(r for r in rows if r["method"] == "ndu")["controls"][0]
        c["modifier_applied"] = False
        with self.assertRaisesRegex(ValueError, "without registered modifier"):
            audit_rows(rows, expected_sources=1)

    def test_termination_incomplete_remains_denominator(self):
        rows = fixture()
        next(r for r in rows if r["method"] == "ndu")["termination"] = "incomplete"
        result = audit_rows(rows, expected_sources=1)
        self.assertEqual(result["ndu_mean_only_jointly_completed"], 0)
        self.assertEqual(result["ndu_mean_only_not_jointly_completed"], 1)

    def test_nan_quality_rejected(self):
        rows = fixture()
        rows[0]["score"]["quality"] = float('nan')
        with self.assertRaisesRegex(ValueError, "invalid quality"):
            audit_rows(rows, expected_sources=1)

    def test_unpinned_journal_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'journal.jsonl'
            path.write_text(''.join(json.dumps(row) + '\n' for row in fixture()))
            with self.assertRaisesRegex(ValueError, "SHA256"):
                audit_pinned_journal(path)

    def test_modified_source_identity_denied(self):
        rows = fixture()
        next(r for r in rows if r["method"] == "ndu")["score"]["task_id"] = "alias"
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            audit_rows(rows, expected_sources=1)


if __name__ == "__main__":
    unittest.main()
