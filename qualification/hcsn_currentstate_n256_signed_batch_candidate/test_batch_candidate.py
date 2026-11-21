"""Small-fixture tests for the shared-parse signed batch candidate."""

import ast
import unittest
from pathlib import Path

from qualification.hcsn_currentstate_n256_non_substochastic_signed_interval.signed_interval import (
    NonSubstochasticSignedIntervalError,
    non_substochastic_signed_outputs_from_fp64_intervals,
)

from .batch_candidate import (
    non_substochastic_signed_batch_outputs_from_fp64_intervals,
)


ROWS = (((0, "bff0000000000000"), (1, "4000000000000000")), ())
VECTORS = (
    ("3ff0000000000000", "bfd0000000000000"),
    ("bff0000000000000", "3fd0000000000000"),
    ("3fe0000000000000", "3fc0000000000000"),
    ("bfe0000000000000", "bfc0000000000000"),
    ("3ff4000000000000", "bfc0000000000000"),
)
DURATION = "3fe0000000000000"


class SharedParseBatchCandidateTest(unittest.TestCase):
    def test_five_vector_batch_equals_five_scalar_calls_exactly(self):
        expected = tuple(
            non_substochastic_signed_outputs_from_fp64_intervals(
                ROWS, vector, DURATION
            )
            for vector in VECTORS
        )
        actual = non_substochastic_signed_batch_outputs_from_fp64_intervals(
            ROWS, VECTORS, DURATION
        )
        self.assertEqual(actual.outputs, tuple(item[0] for item in expected))
        self.assertEqual(actual.certificates, tuple(item[1] for item in expected))
        self.assertEqual(actual.vector_count, 5)
        self.assertEqual(actual.operator_parse_count, 1)
        self.assertEqual(actual.duration_parse_count, 1)
        self.assertFalse(actual.authentic_n256_bundle_loaded)
        self.assertFalse(actual.n256_qualified)

    def test_zero_duration_and_input_guards_match_scalar_domain(self):
        signed_zero_vectors = VECTORS[:4] + (
            ("8000000000000000", "bfc0000000000000"),
        )
        unchanged = non_substochastic_signed_batch_outputs_from_fp64_intervals(
            ROWS, signed_zero_vectors, "8000000000000000"
        )
        scalar_unchanged = tuple(
            non_substochastic_signed_outputs_from_fp64_intervals(
                ROWS, vector, "8000000000000000"
            )[0]
            for vector in signed_zero_vectors
        )
        self.assertEqual(unchanged.outputs, scalar_unchanged)
        with self.assertRaisesRegex(
            NonSubstochasticSignedIntervalError, "non-empty sequence"
        ):
            non_substochastic_signed_batch_outputs_from_fp64_intervals(
                ROWS, (), DURATION
            )
        with self.assertRaisesRegex(
            NonSubstochasticSignedIntervalError, "vector dimension mismatch"
        ):
            non_substochastic_signed_batch_outputs_from_fp64_intervals(
                ROWS, (("3ff0000000000000",),), DURATION
            )
        with self.assertRaisesRegex(
            NonSubstochasticSignedIntervalError, "bounded batch limit"
        ):
            non_substochastic_signed_batch_outputs_from_fp64_intervals(
                ROWS, VECTORS * 4, DURATION
            )

    def test_public_batch_path_parses_shared_inputs_once(self):
        source = (Path(__file__).parent / "batch_candidate.py").read_text()
        tree = ast.parse(source)
        public = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name
            == "non_substochastic_signed_batch_outputs_from_fp64_intervals"
        )
        call_names = [
            node.func.id
            for node in ast.walk(public)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        self.assertEqual(call_names.count("_canonical_operator"), 1)
        self.assertEqual(call_names.count("_transition_rows"), 1)
        self.assertNotIn(
            "non_substochastic_signed_outputs_from_fp64_intervals", call_names
        )
        self.assertNotIn("float", call_names)


if __name__ == "__main__":
    unittest.main()
