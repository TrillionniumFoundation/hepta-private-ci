"""Source-specific Head withdrawal and cross-type non-resurrection regression."""
from dataclasses import replace
import unittest

from amcn_core import Refused, digest
from amcn_revocation import SourceWitness, revocation_census
from amcn_typed_budget import train_typed_budget, type_inventory_digest
from amcn_typed_lineage import freeze_typed_head_lineage, source_binding_digest
from test_amcn_typed_budget import trial


def witness(r):
    return SourceWitness(r.row_id, r.source_root, r.scope, r.generation,
                         1, digest(["immutable source", r.row_id]), False)


def frontier(rows):
    return digest(sorted(x.immutable_key() + (x.revoked,) for x in rows))


class TypedHeadLineageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matrix, cls.types, train, _ = trial()
        cls.trained = train_typed_budget(
            cls.matrix, train, cls.types,
            expected_type_digest=type_inventory_digest(cls.matrix, cls.types),
            steps=6, batch=2, seed=19)
        cls.sources = {r.row_id: witness(r) for r in cls.matrix.rows if r.split == "train"}
        cls.pin = source_binding_digest(cls.matrix, cls.sources)
        cls.result = freeze_typed_head_lineage(cls.matrix, cls.types, cls.trained,
                                               cls.sources, pinned_source_binding_sha256=cls.pin)

    def test_actual_physical_head_sha_and_complete_sources_bound(self):
        artifacts = self.result["artifacts"]
        self.assertEqual(len(artifacts), 4)
        self.assertEqual({a.kind for a in artifacts}, {"typed_memory_head"})
        self.assertEqual([len(a.source_witnesses) for a in artifacts], [8, 8, 4, 4])
        self.assertFalse(self.result["receipt"]["production_accepted"])
        self.assertFalse(self.result["receipt"]["metrics"]["original_artifact_cas_persisted"])

    def test_one_type_revoked_fences_all_shared_heads_but_only_local_child(self):
        artifacts = self.result["artifacts"]
        all_sources = list(self.sources.values())
        chosen = next(x for x in all_sources if "semantic" in x.evidence_id)
        updated = [replace(x, revoked=True) if x.evidence_id == chosen.evidence_id else x
                   for x in all_sources]
        verdict = revocation_census(artifacts, updated, scope="lab", generation="g1",
                                    externally_pinned_frontier_sha256=frontier(updated))
        invalid = set(verdict["metrics"]["quarantined_artifact_ids"])
        # Unsplit controls train on all original TRAIN rows, and both are poisoned.
        self.assertTrue(all(a.artifact_id in invalid for a in artifacts[:2]))
        specialized = {a.head_sha256: a.artifact_id for a in artifacts[2:]}
        self.assertEqual(len(invalid), 3)
        self.assertEqual(len(specialized), 2)
        self.assertFalse(verdict["metrics"]["parameter_unlearning_performed"])
        self.assertFalse(verdict["production_accepted"])

    def test_revision_or_missing_source_denies_old_head_use(self):
        artifacts = self.result["artifacts"]
        all_sources = list(self.sources.values())
        current = [replace(all_sources[0], revision=2, content_sha256=digest("updated"))]
        current.extend(all_sources[1:])
        verdict = revocation_census(artifacts, current, scope="lab", generation="g1",
                                    externally_pinned_frontier_sha256=frontier(current))
        self.assertEqual(len(verdict["metrics"]["quarantined_artifact_ids"]), 3)
        missing = current[1:]
        verdict = revocation_census(artifacts, missing, scope="lab", generation="g1",
                                    externally_pinned_frontier_sha256=frontier(missing))
        self.assertGreaterEqual(len(verdict["metrics"]["quarantined_artifact_ids"]), 3)

    def test_no_future_source_training_witness_admission(self):
        source = dict(self.sources)
        extra = next(r for r in self.matrix.rows if r.split == "future_a")
        source[extra.row_id] = witness(extra)
        with self.assertRaises(Refused):
            source_binding_digest(self.matrix, source)

    def test_same_root_scope_epoch_and_content_mismatch_refused(self):
        first = next(iter(self.sources))
        for changed in (replace(self.sources[first], source_root="other"),
                        replace(self.sources[first], scope="foreign"),
                        replace(self.sources[first], generation="g2"),
                        replace(self.sources[first], revoked=True)):
            sources = dict(self.sources)
            sources[first] = changed
            with self.assertRaises(Refused):
                source_binding_digest(self.matrix, sources)
        with self.assertRaises(Refused):
            freeze_typed_head_lineage(self.matrix, self.types, self.trained,
                                      self.sources, pinned_source_binding_sha256=digest("forged"))

    def test_physical_weights_cannot_be_relabelled_without_failing(self):
        from copy import deepcopy
        corrupted = deepcopy(self.trained)
        corrupted["receipt"]["metrics"]["typed_budget"]["head_sha256"]["semantic"] = digest("forged")
        with self.assertRaises(Refused):
            freeze_typed_head_lineage(self.matrix, self.types, corrupted,
                                      self.sources, pinned_source_binding_sha256=self.pin)


if __name__ == "__main__":
    unittest.main()
