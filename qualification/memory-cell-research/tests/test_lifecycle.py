from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from memory_cells.lifecycle import (
    ArtifactRecord,
    CandidateMetrics,
    LifecycleError,
    MemoryRegistry,
    choose_structure,
    plan_split,
)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.registry = MemoryRegistry()
        self.parent = ArtifactRecord("parent", "project", "a" * 64, ("event:r1",))
        self.child = ArtifactRecord(
            "child", "project", "b" * 64, ("other:r1",), ("parent",), 2
        )
        self.registry.register(self.parent)
        self.registry.register(self.child)

    def test_revocation_cascades_through_parameter_inheritance(self):
        self.registry.adopt("cell", "child", expected_revision=0)
        affected = self.registry.correct_source("event:r1", "event:r2")
        self.assertEqual(affected, ("child", "parent"))
        with self.assertRaisesRegex(LifecycleError, "unavailable"):
            self.registry.resolve("cell", scope="project")
        with self.assertRaisesRegex(LifecycleError, "unavailable"):
            self.registry.adopt("cell", "parent", expected_revision=1)
        with self.assertRaisesRegex(LifecycleError, "revoked parent"):
            self.registry.register(
                ArtifactRecord("grandchild", "project", "c" * 64, (), ("child",), 3)
            )
        clean = ArtifactRecord("clean", "project", "d" * 64, ("event:r2", "other:r1"))
        self.registry.register(clean)
        self.registry.adopt("cell", "clean", expected_revision=1)
        self.assertEqual(self.registry.resolve("cell", scope="project"), clean)

    def test_stale_backup_requires_current_frontier(self):
        self.registry.adopt("cell", "child", expected_revision=0)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "before-revocation.json"
            self.registry.save(path)
            self.registry.revoke_source("event:r1")
            restored = MemoryRegistry.load(
                path, current_revoked_sources=self.registry.revoked_sources
            )
            self.assertEqual(restored.revoked_sources, self.registry.revoked_sources)
            with self.assertRaisesRegex(LifecycleError, "unavailable"):
                restored.resolve("cell", scope="project")

    def test_cas_and_identity_conflicts_do_not_change_selection(self):
        selection = self.registry.adopt("cell", "parent", expected_revision=0)
        with self.assertRaisesRegex(LifecycleError, "CAS"):
            self.registry.adopt("cell", "child", expected_revision=0)
        with self.assertRaisesRegex(LifecycleError, "identity conflict"):
            self.registry.register(replace(self.parent, parameter_digest="e" * 64))
        self.assertEqual(self.registry.selections["cell"], selection)
        self.assertEqual(self.registry.resolve("cell", scope="project"), self.parent)

    def test_reopen_preserves_records_and_detects_corruption(self):
        self.registry.adopt("cell", "child", expected_revision=0)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "registry.json"
            self.registry.save(path)
            reopened = MemoryRegistry.load(path, current_revoked_sources=())
            self.assertEqual(dict(reopened.records), dict(self.registry.records))
            self.assertEqual(reopened.resolve("cell", scope="project"), self.child)
            payload = json.loads(path.read_text())
            payload["payload"]["selections"]["cell"]["artifact_id"] = "parent"
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(LifecycleError, "digest"):
                MemoryRegistry.load(path, current_revoked_sources=())

    def test_split_never_assigns_hidden_queries_to_training(self):
        plan = plan_split(
            ("a", "b", "c"),
            ("dev",),
            ("hidden",),
            {"a": "left", "b": "right", "c": "right"},
        )
        self.assertEqual(plan.children, (("left", ("a",)), ("right", ("b", "c"))))
        with self.assertRaisesRegex(LifecycleError, "overlapping"):
            plan_split(("a", "b"), ("a",), ("hidden",), {"a": "left", "b": "right"})
        with self.assertRaisesRegex(LifecycleError, "assign every"):
            plan_split(
                ("a", "b"),
                ("dev",),
                ("hidden",),
                {"a": "left", "b": "right", "hidden": "right"},
            )

    def test_structure_selection_requires_retention_and_net_benefit(self):
        baseline = CandidateMetrics("parent", "no_change", 0.20, 0.10, 100, 0.0, 0.01)
        forgetting = CandidateMetrics("bad", "split", 0.01, 0.30, 100, 0.1, 0.01)
        expensive = CandidateMetrics("costly", "grow", 0.02, 0.10, 1000, 2.0, 0.01)
        good = CandidateMetrics("children", "split", 0.08, 0.10, 100, 0.1, 0.01)
        decision = choose_structure(
            (baseline, forgetting, expensive, good),
            training_price=0.1,
            byte_price=0.001,
        )
        self.assertEqual((decision.selected_id, decision.accepted), ("children", True))
        self.assertAlmostEqual(decision.estimated_gain, 0.11)
        self.assertEqual(
            decision.rejected,
            (("bad", "retention_regression"), ("costly", "insufficient_net_gain")),
        )
        rejected = choose_structure(
            (baseline, forgetting, expensive), training_price=0.1, byte_price=0.001
        )
        self.assertEqual(
            (rejected.selected_id, rejected.accepted, rejected.estimated_gain),
            ("parent", False, 0.0),
        )


if __name__ == "__main__":
    unittest.main()
