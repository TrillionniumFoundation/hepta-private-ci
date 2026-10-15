"""Research-only pre-use lease and no-resurrection control tests."""
import unittest
from dataclasses import replace
from amcn_core import digest, Refused
from amcn_preuse import preuse_cell_candidate
from test_amcn_revocation import ParameterLineageTests, pinned


class ResearchPreUseLeaseTests(unittest.TestCase):
    def setUp(self):
        self.models, self.sources = ParameterLineageTests().network()
        self.student = self.models[-1].artifact_id

    def call(self, *, models=None, sources=None, old=(), current_generation="g1",
             lease_sha=None, frontier_sha=None):
        models = self.models if models is None else models
        sources = self.sources if sources is None else sources
        return preuse_cell_candidate(
            self.student, models, sources,
            scope="tenant:lab", generation="g1", runtime_generation=current_generation,
            pinned_frontier_sha256=frontier_sha or pinned(sources),
            persisted_quarantine_ids=old,
            quarantine_ledger_sha256=lease_sha or digest(sorted(old)))

    def test_current_candidate_research_only_never_product(self):
        result = self.call()
        self.assertTrue(result["metrics"]["artifact_admissible_for_isolated_research_only"])
        self.assertFalse(result["metrics"]["production_execution_permitted"])
        self.assertFalse(result["metrics"]["final_use_permitted"])
        self.assertFalse(result["production_accepted"])

    def test_revoked_ancestor_blocks_student(self):
        revoked = [replace(self.sources[0], revoked=True), self.sources[1]]
        result = self.call(sources=revoked)
        self.assertFalse(result["metrics"]["artifact_admissible_for_isolated_research_only"])

    def test_persistent_tombstone_blocks_restored_source(self):
        old = (self.models[0].artifact_id,)
        result = self.call(old=old)
        self.assertFalse(result["metrics"]["artifact_admissible_for_isolated_research_only"])

    def test_stale_generation_and_ledger_refuse(self):
        with self.assertRaises(Refused):
            self.call(current_generation="g2")
        with self.assertRaises(Refused):
            self.call(old=(self.models[0].artifact_id,), lease_sha="a"*64)
        with self.assertRaises(Refused):
            self.call(frontier_sha="f"*64)

    def test_unregistered_parent_or_missing_candidate_refuse(self):
        with self.assertRaises(Refused):
            self.call(models=self.models[:-1])


if __name__=="__main__":
    unittest.main()
