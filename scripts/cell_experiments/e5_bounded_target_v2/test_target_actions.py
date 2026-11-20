"""Synthetic target controls; no original upstream task or model is executed."""

import copy
import json
import unittest

from retrieve_once import select_once
from target_actions import target_for_view
from test_support import visible


class TargetActionsTests(unittest.TestCase):
    def setUp(self):
        self.visible = visible()
        self.view, _ = select_once(self.visible)
        self.pin = self.view["view_digest"]

    def target(self, after, view=None):
        return target_for_view(self.visible, view or self.view, self.pin, after)

    def test_exact_roundtrip_preserves_original_view_and_fixed_task(self):
        original, frozen = copy.deepcopy(self.visible), copy.deepcopy(self.view)
        after = {
            p: b.replace(b"'old'", b"'new'") for p, b in original["runtime"].items()
        }
        result = self.target(after)
        self.assertTrue(result["visible_action_roundtrip"])
        self.assertEqual(self.visible, original)
        self.assertEqual(self.view, frozen)
        self.assertEqual(json.loads(result["target"])[0:2], [2, self.pin])
        self.assertEqual(len(json.loads(result["target"])[2]), result["edit_count"])

    def test_missing_visible_owner_refuses_entire_target(self):
        after = {
            p: b.replace(b"'old'", b"'new'").replace(b"'keep'", b"'changed'")
            for p, b in self.visible["runtime"].items()
        }
        result = self.target(after)
        self.assertTrue(result["structural_roundtrip"])
        self.assertFalse(result["visible_action_roundtrip"])
        self.assertTrue(result["missing_visible_unit_ids"])
        self.assertEqual(result["edit_count"], 2)
        self.assertIsNone(result["target"])

    def test_independent_view_pin_rejects_forgery(self):
        changed = copy.deepcopy(self.view)
        changed["view_digest"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "view pin"):
            self.target(self.visible["runtime"], changed)

    def test_new_or_deleted_after_files_refused(self):
        for after in [{}, dict(self.visible["runtime"], extra=b"x=1\n")]:
            with (
                self.subTest(after=after),
                self.assertRaisesRegex(ValueError, "new/deleted"),
            ):
                self.target(after)

    def test_coupled_python_cython_exact_target_requires_both_files(self):
        raw = b"def bug(value):\n    return 'old'\n"
        original = visible(runtime={"pkg/core.py": raw, "pkg/core.pyx": raw})
        view, _ = select_once(original)
        after = {
            p: b.replace(b"'old'", b"'new'") for p, b in original["runtime"].items()
        }
        result = target_for_view(original, view, view["view_digest"], after)
        self.assertTrue(result["visible_action_roundtrip"])
        self.assertEqual(len(json.loads(result["target"])[2]), 2)
        after["pkg/core.pyx"] = raw
        with self.assertRaisesRegex(ValueError, "counterpart omitted"):
            target_for_view(original, view, view["view_digest"], after)

    def test_oversized_reference_rejected_without_truncation(self):
        after = {
            "pkg/core.py": b"def bug(value):\n    return '"
            + b"x" * 33000
            + b"'\n\ndef other():\n    return 'keep'\n"
        }
        with self.assertRaisesRegex(ValueError, "32768-byte"):
            self.target(after)


if __name__ == "__main__":
    unittest.main()
