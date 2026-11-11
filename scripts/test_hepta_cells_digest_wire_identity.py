"""Reject digest strings whose Python equality differs from native wire bytes.

These are producer-side read-only tests, never native owner or signing evidence.
"""

from dataclasses import asdict, replace
import unittest

from hepta_cells.bundle import digest_bytes
from hepta_cells.lineage_bundle_view import review_native_bundle_claims
from hepta_cells.lineage_policy import LineagePolicyError
from test_hepta_cells_lineage_bundle_view import case
from test_hepta_cells_lineage_policy import pin


class EqualitySpoofedDigest(str):
    """Valid raw hex but hostile Python equality unrelated to its hex bytes."""

    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False

    __hash__ = str.__hash__


class DigestWireIdentityTests(unittest.TestCase):
    def test_digest_codec_rejects_equality_overrides(self):
        frozen = pin(12)
        disguised = EqualitySpoofedDigest(pin(999))
        self.assertNotEqual(str(disguised), frozen)
        self.assertTrue(disguised == frozen)
        self.assertEqual({"encoder": disguised}, {"encoder": frozen})
        self.assertNotEqual(bytes.fromhex(disguised), bytes.fromhex(frozen))
        with self.assertRaisesRegex(ValueError, "digest"):
            digest_bytes(disguised)
        self.assertEqual(digest_bytes(frozen), bytes.fromhex(frozen))

    def test_bundle_component_and_lineage_digest_fields_are_exact_strings(self):
        _, _, _, candidate, _ = case()
        forged = EqualitySpoofedDigest(pin(999))
        for name, original in candidate.components.items():
            if original is None:
                continue
            with self.subTest(component=name):
                poisoned = replace(
                    candidate, components=dict(candidate.components, **{name: forged})
                )
                with self.assertRaisesRegex(ValueError, "digest"):
                    poisoned.digest()
        for name in candidate.training_lineage:
            with self.subTest(training_lineage=name):
                poisoned = replace(
                    candidate,
                    training_lineage=dict(candidate.training_lineage, **{name: forged}),
                )
                with self.assertRaisesRegex(ValueError, "digest"):
                    poisoned.digest()

    def test_forged_encoder_equality_cannot_bypass_frozen_component_scope(self):
        r, evidence, source, candidate, partition = case("VERIFY")
        forged = EqualitySpoofedDigest(pin(999))
        # A naive dict comparison says unchanged even though wire bytes differ.
        untrusted = replace(
            candidate, components=dict(candidate.components, encoder=forged)
        )
        self.assertEqual(untrusted.components, asdict(evidence.candidate_components))
        self.assertNotEqual(
            bytes.fromhex(untrusted.components["encoder"]),
            bytes.fromhex(source.components["encoder"]),
        )
        raw_candidate = replace(
            candidate, components=dict(candidate.components, encoder=str(forged))
        )
        claimed = replace(evidence, candidate_bundle=raw_candidate.digest())
        with self.assertRaisesRegex(
            LineagePolicyError, "invalid original native bundle"
        ):
            review_native_bundle_claims(r, claimed, source, untrusted, partition)


if __name__ == "__main__":
    unittest.main()
