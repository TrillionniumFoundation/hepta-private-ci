"""Regression: evidence digests require exact built-in Python JSON values."""
import json
import unittest
from hepta_cells.component_types import CellError, _bounded_json, digest

class HiddenList(list):
    def __iter__(self):
        return iter(())

class HiddenDict(dict):
    def items(self):
        return iter(())
    def values(self):
        return iter(())

class PretendString(str):
    def __eq__(self, other):
        return other == "approved"
    __hash__ = str.__hash__

class BoundedCanonicalJsonTests(unittest.TestCase):
    def test_hidden_list_cannot_hash_as_an_empty_list(self):
        hidden = HiddenList([{"actually_present": "data"}])
        self.assertEqual(len(hidden), 1)
        self.assertEqual(json.dumps(hidden), "[]")
        with self.assertRaises(CellError):
            _bounded_json(hidden)
        with self.assertRaises(CellError):
            digest({"receipt": hidden})

    def test_virtual_mapping_is_not_canonical(self):
        with self.assertRaises(CellError):
            _bounded_json(HiddenDict({"action": "execute"}))

    def test_custom_string_value_is_not_canonical(self):
        with self.assertRaises(CellError):
            _bounded_json({"lineage": PretendString("evil")})

    def test_custom_string_key_is_not_canonical(self):
        with self.assertRaises(CellError):
            _bounded_json({PretendString("secret"): 1})

    def test_builtin_json_bytes_and_digest_stay_identical(self):
        value = {"b": [True, None, 3, -0.5, "x"], "a": {"key": "value"}}
        expected = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        self.assertEqual(_bounded_json(value), expected)
        self.assertEqual(digest(value), digest(json.loads(expected)))

    def test_builtin_depth_and_node_limits_remain(self):
        value = 1
        for _ in range(33):
            value = [value]
        with self.assertRaises(CellError):
            _bounded_json(value)
        with self.assertRaises(CellError):
            _bounded_json([1] * 32769)

    def test_non_json_and_nonfinite_still_fail(self):
        for value in ((1, 2), float("inf"), float("nan")):
            with self.subTest(value=str(value)), self.assertRaises(CellError):
                _bounded_json(value)

if __name__ == "__main__":
    unittest.main()
