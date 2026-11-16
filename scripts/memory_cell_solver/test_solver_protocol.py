"""Meaningful admission tests without a model download or hidden repair gold."""

import json
import unittest

from edit_protocol import apply_edits, candidate_document


def response(edits):
    return json.dumps({"schema": "hepta.memory-cell.code-edits.v1", "edits": edits})


class EditProtocolTests(unittest.TestCase):
    def test_cumulative_exact_edits_keep_untouched_source(self):
        original = {"impl.py": "import unused\nx = lambda a: a\n", "runner.py": None}
        first = apply_edits(
            response([{"path": "impl.py", "old": "import unused\n", "new": ""}]),
            original,
            list(original),
        )
        second = apply_edits(
            response(
                [
                    {
                        "path": "impl.py",
                        "old": "x = lambda a: a",
                        "new": "def x(a):\n    return a",
                    }
                ]
            ),
            first,
            list(original),
        )
        self.assertEqual(
            candidate_document(second, original),
            {
                "schema": "hepta.memory-cell.implementation-candidate.v1",
                "files": [{"path": "impl.py", "content": "def x(a):\n    return a\n"}],
            },
        )
        self.assertEqual(original["impl.py"], "import unused\nx = lambda a: a\n")

    def test_only_absent_admitted_file_can_be_created(self):
        original = {"runner.py": None}
        fixed = apply_edits(
            response(
                [{"path": "runner.py", "old": None, "new": "raise SystemExit(1)\n"}]
            ),
            original,
            list(original),
        )
        self.assertEqual(fixed, {"runner.py": "raise SystemExit(1)\n"})
        with self.assertRaisesRegex(ValueError, "absent"):
            apply_edits(
                response([{"path": "runner.py", "old": None, "new": "pass"}]),
                fixed,
                list(original),
            )

    def test_ambiguous_missing_empty_and_outside_edits_refused(self):
        current = {"impl.py": "a\na\n"}
        for path, old in [
            ("impl.py", "a"),
            ("impl.py", "absent"),
            ("impl.py", ""),
            ("../test.py", "a"),
        ]:
            with self.subTest(path=path, old=old), self.assertRaises(ValueError):
                apply_edits(
                    response([{"path": path, "old": old, "new": "b"}]),
                    current,
                    list(current),
                )

    def test_duplicate_fields_and_nonjson_output_refused(self):
        inputs = [
            '{"schema":"hepta.memory-cell.code-edits.v1","schema":"x","edits":[]}',
            "I fixed it",
            response([]),
            response([{"path": "a", "old": "x", "new": "x"}]),
        ]
        for raw in inputs:
            with self.subTest(raw=raw), self.assertRaises((ValueError, TypeError)):
                apply_edits(raw, {"a": "x"}, ["a"])

    def test_failed_late_edit_does_not_partially_mutate_input(self):
        current = {"a": "original"}
        raw = response(
            [
                {"path": "a", "old": "original", "new": "changed"},
                {"path": "a", "old": "missing", "new": "bad"},
            ]
        )
        with self.assertRaises(ValueError):
            apply_edits(raw, current, ["a"])
        self.assertEqual(current, {"a": "original"})

    def test_candidate_content_bound_cannot_be_bypassed(self):
        with self.assertRaisesRegex(ValueError, "64 KiB"):
            apply_edits(
                response([{"path": "a", "old": None, "new": "a" * 65537}]),
                {"a": None},
                ["a"],
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
