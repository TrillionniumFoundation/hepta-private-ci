"""Offline source transport behavior; no project imports or native test replay."""

import json
import unittest
from source_units import inventory

from source_actions import apply, bind, canonical, reference_action


class SourceActions(unittest.TestCase):
    def test_class_header_does_not_swallow_first_method_decorators(self):
        raw = b"class Box:\n @classmethod\n def value(cls):\n  return 1\n"
        units = inventory("box.py", raw)
        self.assertEqual(
            [(u["kind"], u["start_line"], u["end_line"]) for u in units],
            [("class_header", 0, 1), ("function", 1, 4)],
        )
        self.assertEqual(
            units[1]["text"], " @classmethod\n def value(cls):\n  return 1\n"
        )

    def test_cython_decorator_does_not_rename_the_function_boundary(self):
        raw = b"@cache(10)\ncpdef str value(str arg):\n    return arg\n"
        units = inventory("box.pyx", raw)
        self.assertEqual(
            [(u["kind"], u["qualname"], u["text"]) for u in units],
            [("cython_function", "value", raw.decode())],
        )

    def roundtrip(self, before, after):
        payload, binding, units = reference_action("fixture-source", before, after)
        allowed = {u["unit_id"] for u in units}
        self.assertEqual(apply(before, binding, payload, allowed), after)
        self.assertEqual(reference_action("fixture-source", before, after)[0], payload)
        return payload, binding, allowed

    def test_decorated_method_utf8_comments_and_exact_untouched_bytes(self):
        before = {
            "module.py": '# π\nclass C:\n    """kept"""\n    @staticmethod\n    def f(x):\n        # note\n        return x + "é"\n\n# trailing comment\n'.encode()
        }
        after = {"module.py": before["module.py"].replace(b"x +", b"x or")}
        self.roundtrip(before, after)

    def test_conditional_module_binding_is_complete(self):
        before = {
            "locale.py": b'try:\n    import icu\n    maximum = b"x"\nexcept ImportError:\n    maximum = b"z"\n'
        }
        after = {"locale.py": before["locale.py"].replace(b'b"x"', b'b"xx"')}
        payload, binding, _ = self.roundtrip(before, after)
        self.assertEqual(len(binding["units"]), 1)
        self.assertEqual(json.loads(payload)["edits"][0]["start_line"], 2)

    def test_complete_new_helper_and_multiple_existing_regions(self):
        before = {
            "module.py": b"CONST = 1\n\ndef a(x):\n    return x\n\nclass C:\n    def b(self, x):\n        return x\n"
        }
        after = {
            "module.py": b"CONST = 2\n\ndef a(x):\n    return helper(x)\n\nclass C:\n    def b(self, x):\n        return x + 1\n\ndef helper(x):\n    return x * 2\n"
        }
        self.roundtrip(before, after)

    def test_python_cython_pair_and_counterpart_omission(self):
        before = {
            "cd.py": b"def f(x):\n    return x + 1\n",
            "cd.pyx": b"from libc.math cimport floor\n\ncpdef double f(double x):\n    cdef double y = x\n    return y + 1\n",
        }
        after = {p: raw.replace(b"+ 1", b"+ 2") for p, raw in before.items()}
        payload, binding, allowed = self.roundtrip(before, after)
        bad = json.loads(payload)
        bad["edits"] = bad["edits"][:1]
        with self.assertRaisesRegex(ValueError, "counterpart"):
            apply(before, binding, canonical(bad), allowed)

    def test_old_source_and_binding_tamper_are_rejected(self):
        before = {"x.py": b"def f():\n    return 1\n"}
        after = {"x.py": b"def f():\n    return 2\n"}
        payload, binding, allowed = self.roundtrip(before, after)
        with self.assertRaisesRegex(ValueError, "binding"):
            apply({"x.py": before["x.py"] + b"# modified\n"}, binding, payload, allowed)
        bad = json.loads(payload)
        bad["binding_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "binding"):
            apply(before, binding, canonical(bad), allowed)

    def test_visibility_overlap_and_outside_unit_rejected(self):
        before = {"x.py": b"def f():\n    return 1\n\ndef g():\n    return 3\n"}
        after = {"x.py": before["x.py"].replace(b"return 1", b"return 2")}
        payload, binding, allowed = self.roundtrip(before, after)
        with self.assertRaisesRegex(ValueError, "visible"):
            apply(before, binding, payload, set())
        bad = json.loads(payload)
        bad["edits"] *= 2
        with self.assertRaisesRegex(ValueError, "overlapping|duplicate"):
            apply(before, binding, canonical(bad), allowed)
        bad = json.loads(payload)
        bad["edits"][0]["end_line"] = 5
        with self.assertRaisesRegex(ValueError, "crosses"):
            apply(before, binding, canonical(bad), allowed)

    def test_invalid_syntax_does_not_execute(self):
        before = {"x.py": b"def f():\n    return 1\n"}
        payload, binding, allowed = self.roundtrip(
            before, {"x.py": b"def f():\n    return 2\n"}
        )
        bad = json.loads(payload)
        bad["edits"][0]["replacement"] = "    return (\n"
        with self.assertRaises(SyntaxError):
            apply(before, binding, canonical(bad), allowed)

    def test_empty_action_preserves_original_as_no_change(self):
        before = {"x.py": b"def f():\n    return 1\n"}
        self.roundtrip(before, before)

    def test_envelope_and_size_reject_before_reconstruction(self):
        before = {"x.py": b"def f():\n    return 1\n"}
        payload, binding, allowed = self.roundtrip(
            before, {"x.py": b"def f():\n    return 2\n"}
        )
        with self.assertRaisesRegex(ValueError, "duplicate JSON"):
            apply(before, binding, b'{"schema":1,"schema":2}', allowed)
        with self.assertRaisesRegex(ValueError, "32768"):
            apply(before, binding, b" " * 32769, allowed)
        with self.assertRaises(UnicodeDecodeError):
            apply(before, binding, payload.decode().encode("utf-16"), allowed)

    def test_file_creation_and_path_escape_are_not_implicit(self):
        with self.assertRaisesRegex(ValueError, "file-creation"):
            reference_action("x", {"x.py": b"pass\n"}, {"y.py": b"pass\n"})
        with self.assertRaisesRegex(ValueError, "unsafe"):
            bind("x", {"../x.py": b"pass\n"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
