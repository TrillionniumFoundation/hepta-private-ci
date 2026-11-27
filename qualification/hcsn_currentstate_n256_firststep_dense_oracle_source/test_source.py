"""Small stdlib controls; no N256 arrays or numerical modules are opened."""

import json
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from qualification.hcsn_currentstate_n256_firststep_dense_oracle_source.admission import (
    AdmissionError,
    require_admission,
)
from qualification.hcsn_currentstate_n256_firststep_dense_oracle_source.dense_oracle import (
    DensePacket,
    _block_rows,
    _phase_alpha,
    _reset_weights,
    _source_identity,
    _spatial_coefficients,
)


class DenseOracleSourceTest(unittest.TestCase):
    def test_spatial_rows_conserve_with_boundary_flux(self):
        rows, lower, upper = _spatial_coefficients(-0.1, 0.3, (0.0, 0.2, 0.5, 1.0))
        self.assertEqual(len(rows), 2)
        for index, row in enumerate(rows):
            self.assertAlmostEqual(sum(row) + lower[index] + upper[index], 0.0)

    def test_reset_weights_are_interior_interpolation(self):
        weights = _reset_weights(0.4, (0.0, 0.2, 0.5, 1.0))
        self.assertAlmostEqual(sum(weights), 1.0)
        self.assertAlmostEqual(weights[0], 1.0 / 3.0)
        self.assertAlmostEqual(weights[1], 2.0 / 3.0)

    def test_block_rows_preserve_parent_output_coupling(self):
        parent = DensePacket("p", 1, 0, 1, Fraction(0), Fraction(1), ((-2.0,),), ((3.0,),), (4.0,))
        rows, output = _block_rows((parent,), ((-1.0, 1.0), (2.0, -2.0)), (5.0, 0.0), (0.25, 0.75))
        self.assertEqual(rows[0], [-2.0, 1.0, 3.0])
        self.assertEqual(output, [0.0, 5.0, 0.0])

    def test_source_identity_sorts_parents_but_binds_interval(self):
        first = _source_identity("kind", Fraction(0), Fraction(1, 1000), 2, 1, ("b", "a"))
        same = _source_identity("kind", Fraction(0), Fraction(1, 1000), 2, 1, ("a", "b"))
        changed = _source_identity("kind", Fraction(0), Fraction(1, 500), 2, 1, ("a", "b"))
        self.assertEqual(first, same)
        self.assertNotEqual(first, changed)

    def test_phase_alpha_retains_signed_ambient_channels(self):
        alpha = _phase_alpha((Fraction(1, 2), Fraction(-1, 4), Fraction(3, 8)))
        self.assertEqual(alpha, (0.5, -0.25, 0.375))

    def test_current_request_rejects_before_missing_admission_is_opened(self):
        root = Path(__file__).parent
        with tempfile.TemporaryDirectory() as temporary:
            request = json.loads((root / "REQUEST.json").read_text())
            request_path = Path(temporary) / "REQUEST.json"
            request_path.write_text(json.dumps(request))
            with self.assertRaisesRegex(AdmissionError, "not admitted"):
                require_admission(request_path, Path(temporary) / "missing.json", root / "dense_oracle.py")


if __name__ == "__main__":
    unittest.main()
