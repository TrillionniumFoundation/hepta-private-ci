import ast
import hashlib
import tempfile
import unittest
from pathlib import Path

from qualification.hcsn_currentstate_n256_exact_generator_review.generator_review import (
    METADATA_SHA256,
    GeneratorReviewError,
    review_exact_generator,
)
from qualification.hcsn_currentstate_n256_stdlib_loader.loader import (
    BASE64_SHA256,
    PHASE_SHA256,
    STATE_SHA256,
)


ROOT = Path(__file__).resolve().parents[2]
ORIGINALS = ROOT / "qualification/hcsn_n256_new_export/evidence/attempt001"


def _canonical(value):
    return value.rstrip(b"\n") + b"\n"


def _copies(root):
    expected = {
        "METADATA.json": METADATA_SHA256,
        "N256_STATE.json": STATE_SHA256,
        "N256_PHASE.json": PHASE_SHA256,
        "N256_STATE.npz.b64": BASE64_SHA256,
    }
    paths = {}
    for name, digest in expected.items():
        value = _canonical((ORIGINALS / name).read_bytes())
        if hashlib.sha256(value).hexdigest() != digest:
            raise AssertionError(f"fixture {name} does not reconstruct exact Git bytes")
        path = root / name
        path.write_bytes(value)
        paths[name] = path
    return paths


class N256ExactGeneratorReviewTest(unittest.TestCase):
    def test_reconstructs_all_rows_and_reset_exactly(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _copies(Path(directory))
            certificate = review_exact_generator(
                paths["METADATA.json"],
                paths["N256_STATE.json"],
                paths["N256_PHASE.json"],
                paths["N256_STATE.npz.b64"],
            )
        self.assertEqual(certificate.nodes_bound, 257)
        self.assertEqual(certificate.metadata_fraction_exact_matches, 2)
        self.assertEqual(certificate.metadata_fraction_roundtrip_matches, 257)
        self.assertEqual(certificate.interior_rows, 255)
        self.assertEqual(certificate.off_diagonal_rates, 510)
        self.assertEqual(certificate.row_balance_identities, 255)
        self.assertEqual(certificate.reset_nonzero_coordinates, 2)
        self.assertEqual(
            (certificate.reset_left_interior_index, certificate.reset_right_interior_index),
            (119, 120),
        )
        self.assertTrue(certificate.independent_exact_rational_reconstruction)
        self.assertTrue(certificate.permanent_upper_escape_reviewed)
        self.assertTrue(certificate.lower_hit_flux_reviewed)
        self.assertFalse(certificate.provider_admitted)
        self.assertFalse(certificate.largegrid_qualification)
        self.assertEqual(certificate.dynamic_calls, 0)
        self.assertEqual(certificate.matrix_exponential_calls, 0)
        self.assertEqual(certificate.numerical_reference_records, 0)

    def test_rejects_changed_metadata_before_review(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _copies(Path(directory))
            value = paths["METADATA.json"].read_bytes()
            paths["METADATA.json"].write_bytes(
                value.replace(b"new-export", b"new-exporX", 1)
            )
            with self.assertRaisesRegex(GeneratorReviewError, "SHA-256 mismatch"):
                review_exact_generator(
                    paths["METADATA.json"],
                    paths["N256_STATE.json"],
                    paths["N256_PHASE.json"],
                    paths["N256_STATE.npz.b64"],
                )

    def test_source_excludes_numeric_providers(self):
        source = (Path(__file__).parent / "generator_review.py").read_text()
        tree = ast.parse(source)
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        imported.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        self.assertFalse(imported & {"numpy", "scipy", "torch"})
        self.assertNotIn("expm_multiply", source)
        self.assertNotIn("n256_sparse_dynamic_intent", source)
        self.assertNotIn("n256_independent_oracle_intent", source)


if __name__ == "__main__":
    unittest.main()
