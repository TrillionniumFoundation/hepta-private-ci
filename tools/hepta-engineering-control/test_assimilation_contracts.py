"""Review conversion binds real discovery bytes and preserves rejection bounds."""

from dataclasses import replace
import unittest

from assimilation.contracts import ProposalError, build_assimilation_proposal
from assimilation.contracts.proposal import EVIDENCE_FIELDS
import test_assimilation_discovery as discovery_fixture


class AssimilationContractTests(unittest.TestCase):
    def setUp(self):
        self.fixture = discovery_fixture.DiscoveryTests()
        self.fixture.setUp()
        self.candidate = self.fixture.run_discovery()
        self.options = {
            "system_id": "3" * 32,
            "proposal_id": "4" * 32,
            "objective_digest": "5" * 64,
            "owner_identity": "fixture-owner",
            "observed_at": "1970-01-01T00:00:00.000009Z",
            "evidence": {name: name.encode() for name in EVIDENCE_FIELDS},
        }

    def tearDown(self):
        self.fixture.tearDown()

    def test_exact_source_bytes_and_enrollment_nanosecond_boundary(self):
        valid = build_assimilation_proposal(self.candidate, **self.options)
        self.assertEqual(
            valid, build_assimilation_proposal(self.candidate, **self.options)
        )
        changed = replace(self.candidate, payload=self.candidate.payload + b" ")
        with self.assertRaisesRegex(ProposalError, "discovery_digest_mismatch"):
            build_assimilation_proposal(changed, **self.options)
        self.options["observed_at"] = "1970-01-01T00:00:00.000010Z"
        with self.assertRaisesRegex(ProposalError, "observation_outside_enrollment"):
            build_assimilation_proposal(self.candidate, **self.options)

    def test_retained_bytes_and_owner_identity_have_explicit_bounds(self):
        self.options["evidence"]["adapterSource"] = b"x" * 262_145
        with self.assertRaisesRegex(ProposalError, "invalid_evidence_bytes"):
            build_assimilation_proposal(self.candidate, **self.options)
        self.options["evidence"]["adapterSource"] = b"retained adapter"
        self.options["owner_identity"] = "x" * 257
        with self.assertRaisesRegex(ProposalError, "invalid_owner"):
            build_assimilation_proposal(self.candidate, **self.options)
