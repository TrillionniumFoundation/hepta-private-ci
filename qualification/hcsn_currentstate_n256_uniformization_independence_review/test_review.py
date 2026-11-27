import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qualification.hcsn_currentstate_n256_uniformization_independence_review import review


CANDIDATE = b"from scipy.sparse.linalg import expm_multiply\ndef run(x):\n return expm_multiply(x, x)\n"
ORACLE = b"from scipy.sparse.linalg import expm_multiply\ndef oracle(x):\n return expm_multiply(x, x)\n"
PROVIDER = b"import math\ndef stable_poisson_window(x):\n return math.exp(x)\ndef synthetic_uniformization_action(x):\n return stable_poisson_window(x)\n"


class IndependenceReviewTests(unittest.TestCase):
    def paths(self, directory, provider=PROVIDER):
        paths = tuple(Path(directory, name) for name in ("candidate.py", "oracle.py", "provider.py"))
        for path, raw in zip(paths, (CANDIDATE, ORACLE, provider)):
            path.write_bytes(raw)
        return paths

    def test_synthetic_distinct_algorithm_families(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self.paths(directory)
            hashes = tuple(review._digest(Path(path).read_bytes()) for path in paths)
            with patch.multiple(
                review,
                CANDIDATE_SHA256=hashes[0],
                ORACLE_SHA256=hashes[1],
                PROVIDER_SHA256=hashes[2],
            ):
                result = review.review_sources(*paths)
        self.assertTrue(result.implementation_independence_passed)
        self.assertTrue(result.provider_standard_library_only)
        self.assertEqual(result.provider_algorithm_family, "stdlib_modal_poisson_uniformization")
        self.assertFalse(result.external_reviewer_independence_certified)
        self.assertFalse(result.provider_admitted)
        self.assertEqual(result.numerical_calls, 0)

    def test_provider_importing_candidate_is_rejected(self):
        provider = PROVIDER + b"from qualification.hcsn_currentstate_n256_sparse_dynamic_intent import sparse_dynamic\n"
        with tempfile.TemporaryDirectory() as directory:
            paths = self.paths(directory, provider)
            hashes = tuple(review._digest(Path(path).read_bytes()) for path in paths)
            with patch.multiple(
                review,
                CANDIDATE_SHA256=hashes[0],
                ORACLE_SHA256=hashes[1],
                PROVIDER_SHA256=hashes[2],
            ):
                with self.assertRaisesRegex(review.IndependenceReviewError, "non-standard"):
                    review.review_sources(*paths)

    def test_provider_calling_expm_is_rejected(self):
        provider = PROVIDER + b"def coupled(x):\n return expm_multiply(x, x)\n"
        with tempfile.TemporaryDirectory() as directory:
            paths = self.paths(directory, provider)
            hashes = tuple(review._digest(Path(path).read_bytes()) for path in paths)
            with patch.multiple(
                review,
                CANDIDATE_SHA256=hashes[0],
                ORACLE_SHA256=hashes[1],
                PROVIDER_SHA256=hashes[2],
            ):
                with self.assertRaisesRegex(review.IndependenceReviewError, "reuses"):
                    review.review_sources(*paths)

    def test_exact_hash_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self.paths(directory)
            with self.assertRaisesRegex(review.IndependenceReviewError, "SHA-256"):
                review.review_sources(*paths)


if __name__ == "__main__":
    unittest.main()
