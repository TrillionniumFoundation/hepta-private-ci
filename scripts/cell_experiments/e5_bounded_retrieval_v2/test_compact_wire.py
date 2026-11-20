import copy
import unittest

from compact_wire import apply_compact
from retrieve_once import render, select_once
from test_support import visible
from v2_common import canonical, sha


class CompactWireTests(unittest.TestCase):
    def setUp(self):
        self.original = visible()
        self.view, _ = select_once(self.original)
        self.pin = self.view["view_digest"]

    def apply(self, edits, view=None, original=None):
        return apply_compact(
            original or self.original,
            view or self.view,
            self.pin,
            canonical([2, self.pin, edits]),
        )

    def test_single_edit_preserves_every_unedited_byte_and_task(self):
        before = copy.deepcopy(self.original)
        result = self.apply([[0, 0, 1, 2, "    return 'new'\n"]])
        self.assertEqual(
            result,
            {
                "pkg/core.py": b"def bug(value):\n    return 'new'\n\ndef other():\n    return 'keep'\n"
            },
        )
        self.assertEqual(self.original, before)
        self.assertEqual(self.apply([]), before["runtime"])

    def test_independent_pin_rejects_self_consistent_forged_view(self):
        forged = copy.deepcopy(self.view)
        forged["payload"]["diagnostic"]["failure"] = "forged context"
        forged["view_digest"] = sha(canonical(forged["payload"]))
        forged["prompt"] = render(forged["payload"], forged["view_digest"])
        forged["prompt_sha256"] = sha(forged["prompt"].encode())
        with self.assertRaisesRegex(ValueError, "view pin"):
            self.apply([], view=forged)

    def test_prompt_tampering_does_not_become_authority(self):
        changed = copy.deepcopy(self.view)
        changed["prompt"] += " extra"
        changed["prompt_sha256"] = sha(changed["prompt"].encode())
        with self.assertRaisesRegex(ValueError, "rendered prompt"):
            self.apply([], view=changed)

    def test_stale_source_or_task_refuses_even_when_identity_is_recomputed(self):
        changed = visible(
            runtime={"pkg/core.py": b"def bug(value):\n    return 'changed'\n"}
        )
        with self.assertRaisesRegex(ValueError, "view material"):
            self.apply([], original=changed)

    def test_scope_overlap_integer_and_unknown_operation_controls(self):
        cases = [
            [[99, 0, 1, 2, "    return 'new'\n"]],
            [[0, 0, 3, 5, "def other():\n    return 'changed'\n"]],
            [[0, 0, 1, 2, "    return 'new'\n"], [0, 0, 1, 2, "    return 'new'\n"]],
            [[False, 0, 1, 2, "    return 'new'\n"]],
            [[0, 4, 1, 2, "    return 'new'\n"]],
            [[0, 1, 4, 4, "def helper():\n    return 1\n"]],
        ]
        for edits in cases:
            with self.subTest(edits=edits), self.assertRaises(ValueError):
                self.apply(edits)

    def test_raw_bound_and_foreign_envelope_refused(self):
        for raw in [
            b" " * 32769,
            canonical([True, self.pin, []]),
            canonical([2, "0" * 64, []]),
            b'{"schema":2,"schema":2}',
        ]:
            with self.subTest(raw=raw[:50]), self.assertRaises(ValueError):
                apply_compact(self.original, self.view, self.pin, raw)

    def test_coupled_python_cython_omission_is_rejected(self):
        raw = b"def bug(value):\n    return 'old'\n"
        original = visible(runtime={"pkg/core.py": raw, "pkg/core.pyx": raw})
        view, _ = select_once(original)
        with self.assertRaisesRegex(ValueError, "counterpart omitted"):
            apply_compact(
                original,
                view,
                view["view_digest"],
                canonical(
                    [2, view["view_digest"], [[0, 0, 1, 2, "    return 'new'\n"]]]
                ),
            )
