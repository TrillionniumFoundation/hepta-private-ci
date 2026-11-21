"""Small-fixture tests for the signed exact streaming candidate."""

import ast
import unittest
from pathlib import Path

from qualification.hcsn_currentstate_n256_non_substochastic_signed_interval.signed_interval import (
    NonSubstochasticSignedIntervalError,
    non_substochastic_signed_outputs_from_fp64_intervals,
)
from qualification.hcsn_currentstate_n256_signed_batch_candidate.batch_candidate import (
    non_substochastic_signed_batch_outputs_from_fp64_intervals,
)

from .streaming import non_substochastic_signed_stream_from_fp64_intervals


ROWS = (((0, "bff0000000000000"), (1, "4000000000000000")), ())
VECTORS = [
    ["3ff0000000000000", "bfd0000000000000"],
    ["bff0000000000000", "3fd0000000000000"],
    ["3fe0000000000000", "3fc0000000000000"],
    ["bfe0000000000000", "bfc0000000000000"],
    ["3ff4000000000000", "bfc0000000000000"],
]
DURATION = "3fe0000000000000"


class SignedStreamingCandidateTest(unittest.TestCase):
    def test_stream_equals_scalar_and_batch_results_exactly(self):
        scalar = tuple(
            non_substochastic_signed_outputs_from_fp64_intervals(
                ROWS, vector, DURATION
            )
            for vector in VECTORS
        )
        batch = non_substochastic_signed_batch_outputs_from_fp64_intervals(
            ROWS, VECTORS, DURATION
        )
        streamed = tuple(
            non_substochastic_signed_stream_from_fp64_intervals(
                ROWS, VECTORS, DURATION
            )
        )
        self.assertEqual(streamed, scalar)
        self.assertEqual(tuple(item[0] for item in streamed), batch.outputs)
        self.assertEqual(tuple(item[1] for item in streamed), batch.certificates)

    def test_all_vectors_are_frozen_and_validated_before_iteration(self):
        mutable = [list(vector) for vector in VECTORS]
        stream = non_substochastic_signed_stream_from_fp64_intervals(
            ROWS, mutable, DURATION
        )
        mutable[0][0] = "7ff0000000000000"
        expected = tuple(
            non_substochastic_signed_outputs_from_fp64_intervals(
                ROWS, vector, DURATION
            )
            for vector in VECTORS
        )
        self.assertEqual(tuple(stream), expected)

        malformed = [list(vector) for vector in VECTORS]
        malformed[-1][0] = "not-binary64"
        with self.assertRaises(NonSubstochasticSignedIntervalError):
            non_substochastic_signed_stream_from_fp64_intervals(
                ROWS, malformed, DURATION
            )

    def test_bounded_scope_and_one_vector_internal_liveness(self):
        with self.assertRaisesRegex(
            NonSubstochasticSignedIntervalError, "bounded batch limit"
        ):
            non_substochastic_signed_stream_from_fp64_intervals(
                ROWS, VECTORS * 4, DURATION
            )

        source = (Path(__file__).parent / "streaming.py").read_text()
        tree = ast.parse(source)
        public = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name
            == "non_substochastic_signed_stream_from_fp64_intervals"
        )
        calls = [
            node.func.id
            for node in ast.walk(public)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        self.assertEqual(calls.count("_canonical_operator"), 1)
        self.assertEqual(calls.count("_transition_rows"), 1)
        self.assertEqual(calls.count("_outputs_from_parsed"), 1)
        self.assertNotIn(
            "non_substochastic_signed_outputs_from_fp64_intervals", calls
        )
        self.assertNotIn("float", calls)


if __name__ == "__main__":
    unittest.main()
