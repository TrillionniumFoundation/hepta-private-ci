"""Typed-output regression checks through the actual isolated worker and analyzer."""

import json
import unittest

from admission import Case, Run
from isolated_runner import run_arm
from routing_diagnostics import analyze
from routing_diagnostics_tests import fixture, seal
from typed_json import equal_json


class EqualityTrap:
    def __eq__(self, other):
        raise AssertionError("custom equality must never be called")


class IntegerTrap(int):
    def __eq__(self, other):
        raise AssertionError("subclass equality must never be called")


def execute(outputs, expected):
    cases = [Case(str(i), str(i), "typed", str(i), None, gold) for i, gold in enumerate(expected)]
    model = Run("typed-fixture", "memory", "inputs", "executor", "budget", lambda query: int(query))
    rows, receipt = run_arm(json.dumps([vars(case) for case in cases]), model,
        lambda: (lambda index, payload: outputs[index]), 1., cpu_seconds=10,
        wall_seconds=10., address_space_bytes=256 * 1024 * 1024)
    return rows, receipt


class TypedOutputTests(unittest.TestCase):
    def test_primitive_bool_integer_and_float_confusion_are_wrong_in_real_worker(self):
        rows, receipt = execute([True, 1, 1.0, 1, False, 0], [1, True, 1, 1.0, 0, False])
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual([(row["correct"], row["error"]) for row in rows], [(False, None)] * 6)

    def test_nested_types_are_compared_without_python_equality_coercion(self):
        rows, receipt = execute(
            [[True], {"answer": [1, False]}, {"x": {"y": 1.0}}],
            [[1], {"answer": [1, 0]}, {"x": {"y": 1}}])
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual([(row["correct"], row["error"]) for row in rows], [(False, None)] * 3)

    def test_original_valid_json_positive_controls_remain_correct(self):
        values = [None, True, False, 0, -17, 2**120, 1.25, "中文\n🧠", [1, "a", None],
                  {"nested": {"list": [False, 1, 1.0]}, "value": 1e200}]
        rows, receipt = execute(values, values)
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual([(row["correct"], row["error"]) for row in rows], [(True, None)] * len(values))

    def test_dictionary_order_is_ignored_array_order_is_not(self):
        rows, receipt = execute([{"b": 2, "a": [1, None]}, [2, 1]],
                                [{"a": [1, None], "b": 2}, [1, 2]])
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual([(row["correct"], row["error"]) for row in rows], [(True, None), (False, None)])

    def test_equal_finite_floats_include_signed_zero_deliberately(self):
        rows, receipt = execute([-0.0, 0.0, 1e-200, 1.5], [0.0, -0.0, 1e-200, 1.5])
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual([(row["correct"], row["error"]) for row in rows], [(True, None)] * 4)

    def test_unsupported_python_outputs_fail_then_next_valid_row_still_runs(self):
        outputs = [(1, 2), {1, 2}, b"text", {1: "value"}, {True: "value"}, [1, 2]]
        rows, receipt = execute(outputs, [[1, 2], [1, 2], "text", {"1": "value"}, {"true": "value"}, [1, 2]])
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual([(row["correct"], row["error"]) for row in rows],
                         [(False, "TypeError")] * 5 + [(True, None)])

    def test_custom_equality_and_numeric_subclasses_are_rejected(self):
        rows, receipt = execute([EqualityTrap(), IntegerTrap(1), {"value": EqualityTrap()}], [1, 1, {"value": 1}])
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual([(row["correct"], row["error"]) for row in rows], [(False, "TypeError")] * 3)

    def test_nonfinite_outputs_are_errors_not_correct_facts(self):
        rows, receipt = execute([float("nan"), float("inf"), float("-inf"), {"value": float("nan")}],
                                [None, 1.0, -1.0, {"value": None}])
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual([(row["correct"], row["error"]) for row in rows], [(False, "ValueError")] * 4)

    def test_worker_and_offline_analyzer_share_the_same_output_semantics(self):
        pairs = [(True, 1), (1, 1.0), (-0.0, 0.0), ({"b": 2, "a": True}, {"a": True, "b": 2}),
                 ([False], [0]), ([1, 2], [2, 1])]
        rows, receipt = execute([a for a, _ in pairs], [b for _, b in pairs])
        self.assertEqual(receipt["status"], "completed")
        diagnostic = []
        for actual, expected in pairs:
            data = fixture()
            query = data["queries"][0]
            query["expected_output"] = expected
            query["traces"]["a"]["reader"]["output"] = actual
            diagnostic.append(analyze(seal(data))["arms"]["a"]["rows"][0]["actual_correct"])
        self.assertEqual(diagnostic, [row["correct"] for row in rows])
        self.assertEqual(diagnostic, [False, False, True, True, False, False])

    def test_expected_values_are_validated_too(self):
        for value in (float("nan"), {1: "bad"}, (1,), EqualityTrap()):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises((TypeError, ValueError)):
                    equal_json(None, value)

    def test_type_validation_does_not_invoke_metaclass_equality(self):
        class Trap(type):
            def __eq__(self, other):
                raise AssertionError("metaclass equality must never be called")

        class Unsupported(metaclass=Trap):
            pass

        with self.assertRaises(TypeError):
            equal_json(Unsupported(), True)


if __name__ == "__main__":
    unittest.main()
