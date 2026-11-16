"""Adversarial tests: a hashed training trace must still be parsed unambiguously."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from qualification.hcsn_differentiable.training_domain import read_trace


class StrictTrainingTraceTests(unittest.TestCase):
    def _check(self, *, header=None, visit=None, footer_extra=None, replace_footer=None):
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
            self._check(header='{"kind":"header","schema":"wrong","schema":"hcsn-training-domain-v1"}')

    def test_nested_duplicate_visit_key_rejected(self):
        with self.assertRaises(ValueError):
            self._check(visit='{"kind":"visit","index":0,"operator":{"mu":-3,"mu":0}}')

    def test_duplicate_footer_count_rejected(self):
        with self.assertRaises(ValueError):
            self._check(replace_footer=lambda s:s.replace('"retained_records":1', '"retained_records":7,"retained_records":1'))

    def test_nan_constant_rejected(self):
        with self.assertRaises(ValueError):
            self._check(visit='{"kind":"visit","index":0,"aux":NaN}')

    def test_infinity_constant_rejected(self):
        with self.assertRaises(ValueError):
            self._check(header='{"kind":"header","schema":"hcsn-training-domain-v1","aux":Infinity}')

    def test_overflow_float_rejected(self):
        with self.assertRaises(ValueError):
            self._check(visit='{"kind":"visit","index":0,"aux":1e9999}')

    def test_legitimate_small_finite_float(self):
        _, visits, _, _ = self._check(visit='{"kind":"visit","index":0,"aux":-1.25e-40}')
        self.assertEqual(visits[0]["aux"], -1.25e-40)

    def test_negative_infinity_constant_rejected(self):
        with self.assertRaises(ValueError):
            self._check(visit='{"kind":"visit","index":0,"aux":-Infinity}')

    def test_nonobject_record_rejected_as_value_error(self):
        with self.assertRaises(ValueError):
            self._check(visit='["visit",0]')


if __name__ == "__main__":
    unittest.main()
