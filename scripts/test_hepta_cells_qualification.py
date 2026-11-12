"""Canonical qualification values across the experimental host callback."""

from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import unittest

from hepta_cells.lifecycle import CellError, CellOwner, Partition, Qualification
import test_hepta_cells_lifecycle as lifecycle_support
import test_hepta_cells_population_owner as population_support


class DerivedQualification(Qualification):
    pass


class DerivedDigest(str):
    pass


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = population_support.PopulationOwnerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.owner = self.fixture.owner
        self.partition = self.fixture.partition()
        self.source = self.fixture.components["pred"]
        self.candidate = self.fixture.temporal_candidate()
        self.fixture.observe("qualification-one", 0)
        self.fixture.observe("qualification-two", 1)
        self.expected = (
            self.source.identity.digest,
            self.candidate.identity.digest,
            population_support.fingerprint("host-evaluation-result"),
        )
        self.calls = []
        self.owner.qualify = self.qualify

    def qualify(self, value):
        fields = (
            value.source_identity,
            value.candidate_identity,
            value.evaluation_digest,
        )
        self.calls.append(fields)
        return fields == self.expected

    def snapshot(self):
        return tuple(self.owner.db.iterdump())

    def test_canonical_qualification_adopts_real_temporal_successor(self):
        qualification = Qualification(*self.expected)
        received = []

        def qualify(value):
            received.append(value)
            return self.qualify(value)

        self.owner.qualify = qualify
        checkpoint = self.owner.adopt(self.partition, self.candidate, qualification)
        self.assertEqual(self.calls, [self.expected])
        self.assertEqual(received, [qualification])
        self.assertEqual(
            (checkpoint["identity"], checkpoint["state"], checkpoint["epoch"]),
            (asdict(self.candidate.identity), self.candidate.initial_state(), 1),
        )
        self.owner.close()
        self.fixture.owner = CellOwner(self.fixture.database, qualify=self.qualify)
        self.assertEqual(self.fixture.owner.checkpoint(self.partition), checkpoint)

    def test_other_value_object_is_rejected_without_callback_or_write(self):
        value = SimpleNamespace(**asdict(Qualification(*self.expected)))
        before = self.snapshot()
        with self.assertRaises(CellError):
            self.owner.adopt(self.partition, self.candidate, value)
        self.assertEqual((self.calls, self.snapshot()), ([], before))

    def test_derived_qualification_is_rejected_without_callback_or_write(self):
        before = self.snapshot()
        with self.assertRaises(CellError):
            self.owner.adopt(
                self.partition, self.candidate, DerivedQualification(*self.expected)
            )
        self.assertEqual((self.calls, self.snapshot()), ([], before))

    def reject_derived_field(self, field):
        value = Qualification(*self.expected)
        object.__setattr__(value, field, DerivedDigest(getattr(value, field)))
        before = self.snapshot()
        with self.assertRaises(CellError):
            self.owner.adopt(self.partition, self.candidate, value)
        self.assertEqual((self.calls, self.snapshot()), ([], before))

    def test_source_field_requires_an_exact_string(self):
        self.reject_derived_field("source_identity")

    def test_candidate_field_requires_an_exact_string(self):
        self.reject_derived_field("candidate_identity")

    def test_evaluation_field_requires_an_exact_string(self):
        self.reject_derived_field("evaluation_digest")

    def reject_callback_change(self, field):
        def qualify(value):
            accepted = self.qualify(value)
            object.__setattr__(value, field, "f" * 64)
            return accepted

        self.owner.qualify = qualify
        before = self.snapshot()
        with self.assertRaises(CellError):
            self.owner.adopt(
                self.partition, self.candidate, Qualification(*self.expected)
            )
        self.assertEqual((self.calls, self.snapshot()), ([self.expected], before))

    def test_source_field_cannot_change_during_callback(self):
        self.reject_callback_change("source_identity")

    def test_candidate_field_cannot_change_during_callback(self):
        self.reject_callback_change("candidate_identity")

    def test_evaluation_field_cannot_change_during_callback(self):
        self.reject_callback_change("evaluation_digest")

    def test_callback_cannot_replace_fields_with_derived_strings(self):
        def qualify(value):
            accepted = self.qualify(value)
            object.__setattr__(
                value, "evaluation_digest", DerivedDigest(value.evaluation_digest)
            )
            return accepted

        self.owner.qualify = qualify
        before = self.snapshot()
        with self.assertRaises(CellError):
            self.owner.adopt(
                self.partition, self.candidate, Qualification(*self.expected)
            )
        self.assertEqual((self.calls, self.snapshot()), ([self.expected], before))

    def test_host_refusal_does_not_change_population_or_owner_rows(self):
        value = Qualification(self.expected[0], self.expected[1], "f" * 64)
        before = self.snapshot()
        with self.assertRaises(CellError):
            self.owner.adopt(self.partition, self.candidate, value)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.calls, [(self.expected[0], self.expected[1], "f" * 64)])

    def test_identity_change_during_callback_is_rejected_without_write(self):
        owner = CellOwner(Path(self.fixture.temporary.name) / "identity.sqlite")
        self.addCleanup(owner.close)
        partition = Partition("principal", "agent", "counter", "run")
        source = lifecycle_support.Counter("1")
        candidate = lifecycle_support.Counter("2")
        owner.create(partition, source)
        qualification = Qualification(
            source.identity.digest, candidate.identity.digest, "a" * 64
        )
        expected = asdict(qualification)

        def qualify(value):
            accepted = asdict(value) == expected
            object.__setattr__(candidate.identity, "bundle_digest", "3" * 64)
            return accepted

        owner.qualify = qualify
        before = tuple(owner.db.iterdump())
        with self.assertRaises(CellError):
            owner.adopt(partition, candidate, qualification)
        self.assertEqual(tuple(owner.db.iterdump()), before)


if __name__ == "__main__":
    unittest.main()
