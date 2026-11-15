"""Adversarial tests: a hashed training trace must still be parsed unambiguously."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from qualification.hcsn_differentiable.training_domain import read_trace


class StrictTrainingTraceTests(unittest.TestCase):
    def _check(
        self, *, header=None, visit=None, footer_extra=None, replace_footer=None
    ):
        header = header or '{"kind":"header","schema":"hcsn-training-domain-v1"}'
        visit = visit or '{"kind":"visit","index":0}'
        prefix = (header + "\n" + visit + "\n").encode("utf-8")
        footer = {
            "kind": "end",
            "retained_records": 1,
            "seen_records": 1,
            "dropped_records": 0,
            "truncated": False,
            "prefix_sha256": hashlib.sha256(prefix).hexdigest(),
        }
        footer.update(footer_extra or {})
        tail = json.dumps(footer, separators=(",", ":"), allow_nan=False)
        if replace_footer:
            tail = replace_footer(tail)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            path.write_bytes(prefix + tail.encode("utf-8") + b"\n")
            return read_trace(path)

    def test_valid_canonical_trace(self):
        head, visits, foot, digest = self._check()
        self.assertEqual(len(visits), 1)
        self.assertEqual(foot["retained_records"], 1)
        self.assertEqual(len(digest), 64)

    def test_duplicate_top_level_schema_rejected(self):
        with self.assertRaises(ValueError):
            self._check(
                header='{"kind":"header","schema":"wrong","schema":"hcsn-training-domain-v1"}'
            )

    def test_nested_duplicate_visit_key_rejected(self):
        with self.assertRaises(ValueError):
            self._check(visit='{"kind":"visit","index":0,"operator":{"mu":-3,"mu":0}}')

    def test_duplicate_footer_count_rejected(self):
        with self.assertRaises(ValueError):
            self._check(
                replace_footer=lambda s: s.replace(
                    '"retained_records":1', '"retained_records":7,"retained_records":1'
                )
            )

    def test_nan_constant_rejected(self):
        with self.assertRaises(ValueError):
            self._check(visit='{"kind":"visit","index":0,"aux":NaN}')

    def test_infinity_constant_rejected(self):
        with self.assertRaises(ValueError):
            self._check(
                header='{"kind":"header","schema":"hcsn-training-domain-v1","aux":Infinity}'
            )

    def test_overflow_float_rejected(self):
        with self.assertRaises(ValueError):
            self._check(visit='{"kind":"visit","index":0,"aux":1e9999}')

    def test_legitimate_small_finite_float(self):
        _, visits, _, _ = self._check(
            visit='{"kind":"visit","index":0,"aux":-1.25e-40}'
        )
        self.assertEqual(visits[0]["aux"], -1.25e-40)

    def test_negative_infinity_constant_rejected(self):
        with self.assertRaises(ValueError):
            self._check(visit='{"kind":"visit","index":0,"aux":-Infinity}')

    def test_nonobject_record_rejected_as_value_error(self):
        with self.assertRaises(ValueError):
            self._check(visit='["visit",0]')

    def test_trace_counter_types_reject_boolean_and_fractional_aliases(self):
        for name, value in (
            ("retained_records", True),
            ("retained_records", 1.0),
            ("seen_records", True),
            ("seen_records", 1.0),
            ("dropped_records", False),
            ("dropped_records", 0.0),
        ):
            with self.subTest(name=name, value=value):
                with self.assertRaisesRegex(ValueError, "counts"):
                    self._check(footer_extra={name: value})

    def test_trace_index_requires_an_integer(self):
        for value in ("false", "0.0"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "identities"):
                    self._check(visit='{"kind":"visit","index":' + value + "}")

    def test_trace_truncated_marker_requires_a_boolean(self):
        with self.assertRaisesRegex(ValueError, "counts"):
            self._check(footer_extra={"truncated": 0})

    def test_trace_header_requires_header_kind(self):
        with self.assertRaisesRegex(ValueError, "schema"):
            self._check(header='{"kind":"visit","schema":"hcsn-training-domain-v1"}')

    def test_trace_growth_cannot_bypass_the_read_budget(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "growing.jsonl"
            path.write_bytes(b"{}\n")
            before = path.stat()
            with path.open("r+b") as stream:
                stream.truncate(64 * 1024 * 1024 + 1)
            # Reproduce stale path metadata between the old stat and open.
            with patch.object(Path, "stat", return_value=before):
                with self.assertRaisesRegex(ValueError, "read budget"):
                    read_trace(path)

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "requires no-follow file opens")
    def test_trace_symlink_is_not_opened(self):
        prefix = b'{"kind":"header","schema":"hcsn-training-domain-v1"}\n'
        footer = {
            "kind": "end",
            "retained_records": 0,
            "seen_records": 0,
            "dropped_records": 0,
            "truncated": False,
            "prefix_sha256": hashlib.sha256(prefix).hexdigest(),
        }
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "original.jsonl"
            target.write_bytes(prefix + json.dumps(footer).encode() + b"\n")
            link = Path(directory) / "linked.jsonl"
            link.symlink_to(target.name)
            with self.assertRaisesRegex(ValueError, "regular"):
                read_trace(link)


if __name__ == "__main__":
    unittest.main()
