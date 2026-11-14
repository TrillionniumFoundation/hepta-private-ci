"""A lossy Unicode view is never accepted without a unique preimage witness."""
import base64
import unittest

from deno_lossy_projection_proof import (
    LOSSY_PROJECTION_BASE64, BLOB, ORIGINAL_BYTE_COUNT,
    frozen_proof, recover_single_byte_projection,
)


class ExhaustiveOriginalBlobProof(unittest.TestCase):
    def test_unique_actual_frozen_nonutf8_candidate(self):
        got = frozen_proof()
        self.assertEqual(got["sha1_recomputed_from_exhaustive_candidate"], BLOB)
        self.assertEqual(got["single_unknown_original_byte_hex"], "e9")
        self.assertEqual(got["original_byte_count"], ORIGINAL_BYTE_COUNT)
        self.assertEqual(got["candidate_bytes_tested"], 256)
        self.assertEqual(got["hash_matching_byte_candidates"], 1)
        self.assertFalse(got["actual_binary_github_api_response_received"])
        self.assertFalse(got["production_accepted"])

    def test_without_original_git_hash_no_unqualified_reconstruction(self):
        with self.assertRaisesRegex(ValueError, "no unique"):
            recover_single_byte_projection(LOSSY_PROJECTION_BASE64,
                                           original_sha="0" * 40)

    def test_extra_unicode_replacement_is_unsafe(self):
        bad = base64.b64encode("\ufffd\ufffd".encode()).decode()
        with self.assertRaisesRegex(ValueError, "exactly one"):
            recover_single_byte_projection(bad, original_size=2)

    def test_changed_original_length_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "byte count differs"):
            recover_single_byte_projection(LOSSY_PROJECTION_BASE64,
                                           original_size=ORIGINAL_BYTE_COUNT + 1)

    def test_valid_utf8_source_is_not_claimed_as_lost_byte(self):
        bad = base64.b64encode(b"genuine plain UTF8\n").decode()
        with self.assertRaisesRegex(ValueError, "exactly one"):
            recover_single_byte_projection(bad, original_size=19)

    def test_invalid_encoded_projection_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unverified"):
            recover_single_byte_projection("?illegal?====")


if __name__ == "__main__":
    unittest.main()
