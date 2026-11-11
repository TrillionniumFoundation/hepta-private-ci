"""Adversarial tests for the native-Bundle/1+2+7 read-only join."""

from dataclasses import asdict, replace
import hashlib
import unittest

from hepta_cells.bundle import Bundle
from hepta_cells.lineage_bundle_view import review_native_bundle_claims
from hepta_cells.lineage_policy import CellRoster, LineagePolicyError, review_update
from test_hepta_cells_lineage_policy import evidence, pin, roster


KEYS = ("principal_id", "agent_id", "cell_id", "run_id")


def case(lineage="VERIFY"):
    original = roster()
    old = next(c for c in original.cells if c.lineage == lineage)
    source = Bundle("artifact:cell127-source", old.generation, asdict(old.components))
    enrolled = replace(old, bundle_digest=source.digest())
    enrolled_roster = CellRoster(
        tuple(enrolled if c is old else c for c in original.cells)
    )
    candidate = source.successor(
        "artifact:cell127-candidate",
        dict(source.components, heads=pin(333)),
        pin(201),
        enrolled.update_rule,
        enrolled.evaluation_profile,
    )
    declaration = evidence(
        enrolled,
        source_bundle=source.digest(),
        training_source=source.digest(),
        candidate_bundle=candidate.digest(),
        candidate_generation=candidate.generation,
    )
    partition = dict(zip(KEYS, enrolled.partition))
    return enrolled_roster, declaration, source, candidate, partition


class NativeBundleClaimReviewTests(unittest.TestCase):
    def test_actual_native_bundle_and_partition_claims_remain_review_only(self):
        for lineage in ("VERIFY", "PRED"):
            with self.subTest(lineage=lineage):
                r, e, source, candidate, partition = case(lineage)
                review = review_native_bundle_claims(r, e, source, candidate, partition)
                self.assertEqual(review.status, "REVIEW_ONLY")
                self.assertEqual(review.source_bundle_digest, source.digest())
                self.assertEqual(review.candidate_bundle_digest, candidate.digest())
                self.assertEqual(len(review.state_partition_digest), 64)
                self.assertFalse(review.original_owner_authenticated)
                self.assertFalse(review.independent_signature_authenticated)
                self.assertFalse(review.adoption_authorized)
                self.assertTrue(any("native state owner" in x for x in review.missing))

    def test_untrusted_bundle_artifact_id_is_not_a_matching_native_identity(self):
        r, e, source, candidate, partition = case()
        disguised = replace(source, artifact_id="artifact:other")
        with self.assertRaisesRegex(LineagePolicyError, "Bundle bytes"):
            review_native_bundle_claims(r, e, disguised, candidate, partition)

    def test_wrong_candidate_predecessor_is_still_rejected(self):
        r, e, source, candidate, partition = case()
        unrelated = pin(777)
        wrong = replace(
            candidate,
            rollback_predecessor=unrelated,
            training_lineage=dict(candidate.training_lineage, source_bundle=unrelated),
        )
        claimed = replace(e, candidate_bundle=wrong.digest())
        with self.assertRaisesRegex(
            LineagePolicyError, "invalid original native bundle"
        ):
            review_native_bundle_claims(r, claimed, source, wrong, partition)

    def test_candidate_component_bytes_must_match_the_reviewed_claim(self):
        r, e, source, candidate, partition = case()
        changed = replace(
            candidate, components=dict(candidate.components, heads=pin(444))
        )
        # The digest-only reviewer cannot inspect the Bundle bytes.
        claimed = replace(e, candidate_bundle=changed.digest())
        self.assertEqual(review_update(r, claimed).status, "REVIEW_ONLY")
        with self.assertRaisesRegex(LineagePolicyError, "Bundle bytes"):
            review_native_bundle_claims(r, claimed, source, changed, partition)

    def test_bundle_subclass_must_not_override_canonical_source_or_candidate(self):
        r, e, source, candidate, partition = case()

        class MisleadingBundle(Bundle):
            def digest(self):
                return source.digest()

        forged = MisleadingBundle(
            "artifact:untrusted-source", source.generation, dict(source.components)
        )
        self.assertNotEqual(
            hashlib.sha256(Bundle.canonical_bytes(forged)).hexdigest(),
            source.digest(),
        )
        with self.assertRaisesRegex(LineagePolicyError, "native-compatible"):
            review_native_bundle_claims(r, e, forged, candidate, partition)

        class MisleadingCandidate(Bundle):
            def digest(self):
                return candidate.digest()

        altered = replace(candidate, artifact_id="artifact:untrusted-candidate")
        forged_candidate = MisleadingCandidate(
            altered.artifact_id,
            altered.generation,
            altered.components,
            altered.training_lineage,
            altered.rollback_predecessor,
        )
        with self.assertRaisesRegex(LineagePolicyError, "native-compatible"):
            review_native_bundle_claims(r, e, source, forged_candidate, partition)

    def test_plain_frozen_bundle_cannot_shadow_digest_or_canonical_bytes(self):
        r, e, source, candidate, partition = case()
        for side in ("source", "candidate"):
            for method in ("digest", "canonical_bytes"):
                with self.subTest(side=side, method=method):
                    original = source if side == "source" else candidate
                    forged = replace(original, artifact_id="artifact:forged-object")
                    # Frozen dataclasses without slots permit shadowing a method
                    # with object.__setattr__. Hashing must ignore that method.
                    object.__setattr__(forged, method, getattr(original, method))
                    self.assertNotEqual(
                        hashlib.sha256(Bundle.canonical_bytes(forged)).hexdigest(),
                        original.digest(),
                    )
                    with self.assertRaisesRegex(LineagePolicyError, "Bundle bytes"):
                        review_native_bundle_claims(
                            r,
                            e,
                            forged if side == "source" else source,
                            forged if side == "candidate" else candidate,
                            partition,
                        )

    def test_actual_bundle_dataset_cannot_be_relabelled(self):
        r, e, source, candidate, partition = case()
        changed = replace(
            candidate,
            training_lineage=dict(candidate.training_lineage, dataset=pin(987)),
        )
        claimed = replace(e, candidate_bundle=changed.digest())
        self.assertEqual(review_update(r, claimed).status, "REVIEW_ONLY")
        with self.assertRaisesRegex(LineagePolicyError, "training lineage"):
            review_native_bundle_claims(r, claimed, source, changed, partition)

    def test_rehashed_candidate_and_evidence_cannot_swap_frozen_dataset(self):
        r, e, source, candidate, partition = case()
        changed = replace(
            candidate,
            training_lineage=dict(candidate.training_lineage, dataset=pin(989)),
        )
        relabelled = replace(
            e, candidate_bundle=changed.digest(), dataset_digest=pin(989)
        )
        with self.assertRaisesRegex(LineagePolicyError, "frozen lineage"):
            review_native_bundle_claims(r, relabelled, source, changed, partition)

    def test_actual_bundle_rule_and_evaluation_are_not_caller_relabelled(self):
        r, e, source, candidate, partition = case()
        for key in ("update_rule", "evaluation_profile"):
            with self.subTest(field=key):
                changed = replace(
                    candidate,
                    training_lineage=dict(
                        candidate.training_lineage, **{key: pin(988)}
                    ),
                )
                claimed = replace(e, candidate_bundle=changed.digest())
                with self.assertRaisesRegex(LineagePolicyError, "training lineage"):
                    review_native_bundle_claims(r, claimed, source, changed, partition)

    def test_exact_four_field_partition_is_required(self):
        r, e, source, candidate, partition = case()
        for wrong in (
            dict(partition, principal_id="another-principal"),
            dict(partition, run_id="another-run"),
            dict(partition, state_owner="invented-owner"),
        ):
            with self.subTest(partition=wrong):
                with self.assertRaises(LineagePolicyError):
                    review_native_bundle_claims(r, e, source, candidate, wrong)
        with self.assertRaisesRegex(LineagePolicyError, "CellStatePartition"):
            review_native_bundle_claims(r, e, source, candidate, None)

    def test_original_native_local_update_scope_cannot_expand(self):
        r, e, source, candidate, partition = case("VERIFY")
        changed = source.successor(
            "artifact:changed-encoder",
            dict(source.components, encoder=pin(1000), heads=pin(333)),
            pin(201),
            e.update_rule,
            e.evaluation_profile,
        )
        claimed = replace(
            e,
            candidate_bundle=changed.digest(),
            candidate_components=replace(e.candidate_components, encoder=pin(1000)),
        )
        with self.assertRaises(LineagePolicyError):
            review_native_bundle_claims(r, claimed, source, changed, partition)

    def test_unknown_cost_remains_hold_with_exact_bundle_bytes(self):
        r, e, source, candidate, partition = case()
        costs = dict(e.costs, evaluation_cpu_seconds=None)
        out = review_native_bundle_claims(
            r, replace(e, costs=costs), source, candidate, partition
        )
        self.assertEqual(out.status, "HOLD")
        self.assertIn("evaluation_cpu_seconds", out.missing)
        self.assertFalse(out.adoption_authorized)

    def test_read_only_replay_does_not_mutate_bundles_or_claim_adoption(self):
        r, e, source, candidate, partition = case()
        before = source.record(), candidate.record(), dict(partition), dict(e.costs)
        one = review_native_bundle_claims(r, e, source, candidate, partition)
        two = review_native_bundle_claims(r, e, source, candidate, partition)
        self.assertEqual(one, two)
        self.assertEqual(
            before,
            (source.record(), candidate.record(), dict(partition), dict(e.costs)),
        )
        self.assertFalse(two.adoption_authorized)


if __name__ == "__main__":
    unittest.main()
