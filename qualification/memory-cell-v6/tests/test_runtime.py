"""Integration tests for actual writes, learned reads and coherent source epochs."""

from pathlib import Path
import tempfile
import unittest

from v6.artifacts import ArtifactOwner
from v6.contracts import MemoryRequest
from v6.runtime import MemoryRuntime, train_snapshot
from v6.store import EventStore, StaleSource
from v6.study_data import AT, SINCE, create_sources, expected


class RuntimeTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source, self.artifacts = self.root / "source.sqlite", self.root / "artifacts"
        self.truth = create_sources(self.source, seed=61, domain="engineering", count=8)
        self.record = next(iter(self.truth["entities"].values()))
        self.request = MemoryRequest(
            "runtime-test", self.truth["scope"], self.record["entity"], "read this memory", AT, SINCE
        )
        self.trained = train_snapshot(self.source, self.artifacts, scope=self.truth["scope"], seed=61)

    def tearDown(self):
        self.temporary.cleanup()

    def test_three_cells_new_information_cross_type_and_actual_wrong_shuffle_sources(self):
        runtime = MemoryRuntime(self.source, self.artifacts)
        try:
            for operation in ("current", "history", "semantic", "procedure", "change", "apply"):
                value, sources = expected(self.record, operation)
                read = runtime.read(self.request, operation)
                self.assertEqual((read["status"], read["value"], list(read["source_ids"])), ("ok", value, sources))
            shuffled = runtime.read(self.request, "semantic", permute=True)
            self.assertNotEqual(list(shuffled["source_ids"]), [self.record["sources"]["semantic"]])
            removed = runtime.read(self.request, "apply", disabled=("semantic",))
            self.assertEqual((removed["status"], removed["value"], list(removed["source_ids"])), ("stale", None, []))
            self.assertEqual(len(runtime.loaded), 2)
        finally:
            runtime.close()

    def test_correction_invalidates_old_epoch_rebuilds_and_bounds_serving_cache(self):
        runtime = MemoryRuntime(self.source, self.artifacts)
        runtime.read(self.request, "semantic")
        source = EventStore(self.source)
        replacement = {"factor": 101, "label": "corrected-after-training"}
        source.append(
            scope=self.request.scope,
            entity=self.request.entity,
            kind="semantic",
            effective_at=20240101,
            value=replacement,
            origin_id="correction",
            predecessor=self.record["sources"]["semantic"],
        )
        source.close()
        self.assertEqual(runtime.read(self.request, "semantic")["status"], "stale")
        train_snapshot(self.source, self.artifacts, scope=self.request.scope, seed=62, expected_generation=1)
        read = runtime.read(self.request, "semantic")
        self.assertEqual((read["generation"], read["value"]), (2, replacement))
        self.assertEqual(len(runtime.loaded), 2)
        runtime.close()

    def test_source_payload_and_metadata_corruption_are_rejected(self):
        source = EventStore(self.source)
        selected = self.record["sources"][str(AT)]
        source.db.execute("UPDATE records SET payload='999' WHERE source_id=?", (selected,))
        with self.assertRaises(StaleSource):
            source.record(selected)
        with self.assertRaises(StaleSource):
            source.rows(self.request.scope, "event", at=AT)
        support = self.record["sources"]["semantic"]
        with self.assertRaises(StaleSource):
            source.validate_support([support], scope=self.request.scope, cut=source.cut, expected_entity="another")
        with self.assertRaises(StaleSource):
            source.validate_support([support], scope=self.request.scope, cut=source.cut, expected_kind="procedure")
        source.db.execute("UPDATE records SET entity='another' WHERE source_id=?", (support,))
        with self.assertRaises(StaleSource):
            source.validate_support([support], scope=self.request.scope, cut=source.cut)
        source.close()

    def test_revoked_training_ancestor_invalidates_whole_parameter_bundle(self):
        other = list(self.truth["entities"].values())[-1]
        source = EventStore(self.source)
        source.revoke(other["sources"]["semantic"], "remove another training dependency")
        source.close()
        runtime = MemoryRuntime(self.source, self.artifacts)
        self.assertEqual(runtime.read(self.request, "semantic")["status"], "stale")
        runtime.close()
        train_snapshot(self.source, self.artifacts, scope=self.request.scope, seed=63, expected_generation=1)
        runtime = MemoryRuntime(self.source, self.artifacts)
        self.assertEqual(runtime.read(self.request, "semantic")["value"], self.record["semantic"])
        self.assertTrue(
            all(other["sources"]["semantic"] not in model.lineage_sources for model in runtime.loaded.values())
        )
        runtime.close()

    def test_publish_fault_cas_and_wrong_cell_type_never_change_active_bundle(self):
        owner = ArtifactOwner(self.artifacts)
        manifest, identity = owner.manifest()
        with self.assertRaises(RuntimeError):
            owner.publish(manifest, expected_generation=1, fail_before_commit=True)
        self.assertEqual(owner.active(), (1, identity))
        with self.assertRaises(StaleSource):
            owner.publish(manifest, expected_generation=0)
        manifest["cells"]["semantic"] = manifest["cells"]["procedure"]
        with self.assertRaises(ValueError):
            owner.publish(manifest, expected_generation=1)
        self.assertEqual(owner.active(), (1, identity))
        owner.close()

    def test_typed_writes_and_correction_times_fail_before_mutating_source(self):
        source = EventStore(self.source)
        cut = source.cut
        for kind, value in (
            ("event", True),
            ("semantic", {"factor": 2}),
            ("procedure", {"opcode": "exec", "bias": 1, "limit": 1}),
        ):
            with self.assertRaises(ValueError):
                source.append(
                    scope=self.request.scope,
                    entity=self.request.entity,
                    kind=kind,
                    effective_at=1,
                    value=value,
                    origin_id="bad",
                )
        with self.assertRaises(ValueError):
            source.append(
                scope=self.request.scope,
                entity=self.request.entity,
                kind="semantic",
                effective_at=AT,
                value=self.record["semantic"],
                origin_id="bad-correction",
                predecessor=self.record["sources"]["semantic"],
            )
        self.assertEqual(source.cut, cut)
        source.close()
