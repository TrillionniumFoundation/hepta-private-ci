"""Source-revision and parameter-descendant invalidation regression cases."""
from dataclasses import replace
import unittest

from amcn_core import Refused, digest
from amcn_revocation import (SourceWitness, freeze_generation, revocation_census)


def sha(x):
    return digest(x)


def source(sid, *, version=1, revoked=False, scope="tenant:lab"):
    return SourceWitness(sid, "root-"+sid, scope, "g1", version,
                         sha((sid, version)), revoked)


def artifact(name, sources, *, parents=(), scope="tenant:lab", kind="semantic_head"):
    return freeze_generation(sha(name), kind, scope, "g1", sha("encoder"),
                             sha("head:"+name), tuple(parents), tuple(sources))


def pinned(current):
    return digest(sorted(s.immutable_key() + (s.revoked,) for s in current))


class ParameterLineageTests(unittest.TestCase):
    def network(self):
        a, b = source("a"), source("b")
        root_a = artifact("root-a", [a])
        child_a = artifact("child-a", [a], parents=(root_a.artifact_id,), kind="split_child")
        root_b = artifact("root-b", [b])
        merged = artifact("merged", [a, b], parents=(child_a.artifact_id, root_b.artifact_id),
                          kind="consolidation_student")
        return [root_a, child_a, root_b, merged], [a, b]

    def test_current_source_and_lineage_are_research_only(self):
        network, current = self.network()
        result = revocation_census(network, current, scope="tenant:lab", generation="g1",
                                   externally_pinned_frontier_sha256=pinned(current))
        m = result["metrics"]
        self.assertEqual(m["quarantined_artifact_ids"], [])
        self.assertEqual(m["artifact_count"], 4)
        self.assertFalse(m["production_head_activation_allowed"])
        self.assertFalse(m["parameter_unlearning_performed"])
        self.assertFalse(result["production_accepted"])

    def test_revoked_parent_invalidates_split_and_student_not_other_source(self):
        network, current = self.network()
        revoked = [replace(current[0], revoked=True), current[1]]
        result = revocation_census(list(reversed(network)), revoked, scope="tenant:lab",
                                   generation="g1", externally_pinned_frontier_sha256=pinned(revoked))
        invalid = set(result["metrics"]["quarantined_artifact_ids"])
        self.assertEqual(invalid, {network[0].artifact_id, network[1].artifact_id,
                                   network[3].artifact_id})
        self.assertEqual(result["metrics"]["unaffected_artifact_ids"], [network[2].artifact_id])

    def test_revised_source_does_not_revalidate_old_model(self):
        network, current = self.network()
        revised = [replace(current[0], revision=2, content_sha256=sha("new")), current[1]]
        report = revocation_census(network, revised, scope="tenant:lab", generation="g1",
                                   externally_pinned_frontier_sha256=pinned(revised))
        self.assertEqual(report["metrics"]["directly_invalid"], 3)
        self.assertFalse(report["metrics"]["safe_to_reactivate_previous_artifact"])

    def test_missing_source_is_not_a_permitted_empty_cache_result(self):
        network, current = self.network()
        report = revocation_census(network, current[:1], scope="tenant:lab", generation="g1",
                                   externally_pinned_frontier_sha256=pinned(current[:1]))
        self.assertIn(network[2].artifact_id, report["metrics"]["quarantined_artifact_ids"])
        self.assertIn(network[3].artifact_id, report["metrics"]["quarantined_artifact_ids"])

    def test_reentering_previous_quarantine_fails_closed_even_if_source_returns(self):
        network, current = self.network()
        outcome = revocation_census(network, current, scope="tenant:lab", generation="g1",
                                   externally_pinned_frontier_sha256=pinned(current),
                                   old_quarantined=[network[0].artifact_id])
        self.assertIn(network[1].artifact_id, outcome["metrics"]["quarantined_artifact_ids"])
        self.assertIn(network[3].artifact_id, outcome["metrics"]["quarantined_artifact_ids"])

    def test_missing_or_forged_external_pin_and_stale_manifest_refused(self):
        network, current = self.network()
        for pin in (None, sha("fake")):
            with self.assertRaises(Refused):
                revocation_census(network, current, scope="tenant:lab", generation="g1",
                                  externally_pinned_frontier_sha256=pin)
        with self.assertRaises(Refused):
            bad = replace(network[0], manifest_sha256=sha("changed"))
            # Dataclass replacement itself must invalidate before a new call.
            revocation_census([bad] + network[1:], current, scope="tenant:lab",
                              generation="g1", externally_pinned_frontier_sha256=pinned(current))

    def test_student_cannot_drop_inherited_training_sources(self):
        network, current = self.network()
        with self.assertRaises(Refused):
            candidate = artifact("bad-consolidation", [current[1]],
                                 parents=(network[1].artifact_id, network[2].artifact_id),
                                 kind="consolidation_student")
            revocation_census(network[:-1] + [candidate], current, scope="tenant:lab",
                              generation="g1", externally_pinned_frontier_sha256=pinned(current))

    def test_cycles_and_cross_scope_parents_refused(self):
        a = source("a")
        kid1 = artifact("c1", [a], parents=(sha("c2"),))
        kid2 = artifact("c2", [a], parents=(sha("c1"),))
        with self.assertRaises(Refused):
            revocation_census([kid1, kid2], [a], scope="tenant:lab", generation="g1",
                              externally_pinned_frontier_sha256=pinned([a]))
        cross = artifact("cross", [source("a",scope="other")], scope="other")
        with self.assertRaises(Refused):
            revocation_census([cross], [a], scope="tenant:lab", generation="g1",
                              externally_pinned_frontier_sha256=pinned([a]))


if __name__ == "__main__":
    unittest.main()
