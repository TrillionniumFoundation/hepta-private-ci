import unittest

from seal_luigi_dependency_runtime import merge_pins


class LuigiPinMergeTests(unittest.TestCase):
    def test_identical_repeated_bindings_preserve_all_sources(self):
        original = {"/original": "a", "/shared": "b"}
        built = {"/shared": "b", "/built": "c"}
        captured = {"/original": "a", "/attempt": "d"}
        self.assertEqual(merge_pins(original, built, captured),
                         {"/original": "a", "/shared": "b", "/built": "c", "/attempt": "d"})
        self.assertEqual(original, {"/original": "a", "/shared": "b"})

    def test_later_capture_cannot_override_earlier_expected_pin(self):
        with self.assertRaisesRegex(ValueError, "conflicting"):
            merge_pins({"/source": "expected"}, {"/new": "value"}, {"/source": "changed"})


if __name__ == "__main__":
    unittest.main()
