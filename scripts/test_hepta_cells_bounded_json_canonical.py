"""Canonical Cell JSON requires exact built-in values and keys."""

import json
import unittest

from hepta_cells.component_types import CellError, _bounded_json, digest


class CustomList(list):
    pass


class CustomDict(dict):
    pass


class CustomString(str):
    pass


class BoundedCanonicalJsonTests(unittest.TestCase):
    def test_custom_containers_and_strings_are_rejected(self):
        candidates = [
            CustomList(["data"]),
            CustomDict({"value": 1}),
            {"value": CustomString("data")},
            {CustomString("key"): 1},
        ]
        for value in candidates:
            with self.subTest(value_type=type(value)), self.assertRaises(CellError):
                digest({"record": value})

    def test_builtin_receipt_keeps_exact_encoding_and_digest(self):
        value = {"b": [True, None, 3, -0.5, "x"], "a": {"key": "value"}}
        expected = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        self.assertEqual(_bounded_json(value), expected)
        self.assertEqual(digest(value), digest(json.loads(expected)))

    def test_builtin_input_remains_bounded(self):
        deep = 1
        for _ in range(33):
            deep = [deep]
        for value in (deep, [1] * 32769, (1, 2), float("inf"), float("nan")):
            with self.assertRaises(CellError):
                _bounded_json(value)
