"""Wrapper migration guards; native execution is exercised by the joint demo.

The transport sentinel is intentionally never called in these unit tests.
"""

import copy
from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hepta_cells.bundle import Bundle, OPTIONAL, REQUIRED
from hepta_cells.component_types import digest
from hepta_cells.hia_component import HiaCellComponent
from hepta_cells.lifecycle import CellError, CellOwner, Partition, PendingExecution, Qualification
from hepta_cells.temporal import TemporalConfig, TemporalKernel
from hepta_cells.temporal_component import TemporalComponent


class HiaMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.owner = CellOwner(Path(self.temp.name) / "owner.sqlite")
        self.native = object()
        self.kernel = TemporalKernel("memory", TemporalConfig(3, 1, 2, hidden_dim=4))
        parts = {name: digest(["fixture", name]) for name in REQUIRED}
        parts.update({name: None for name in OPTIONAL})
        parts.update(base=self.kernel.kernel_sha256, heads=self.kernel.heads_sha256, composition=self.kernel.config.sha256)
        old = TemporalComponent(self.kernel, Bundle("parent", 1, parts), "run")
        kernel = copy.deepcopy(self.kernel)
        kernel._model.params["by"][0] += 0.25
        bundle = old.bundle.successor("candidate", {**parts, "heads": kernel.heads_sha256}, digest("data"), digest("rule"), digest("evaluation"))
        new = TemporalComponent(kernel, bundle, "run")
        self.source = HiaCellComponent(self.owner, old, self.native, candidate_sha256=digest("old"), image_sha256=digest("image"))
        self.target = HiaCellComponent(self.owner, new, self.native, candidate_sha256=digest("new"), image_sha256=digest("image"))
        self.partition = Partition("fixture", "agent", "memory", "run")
        self.qualification = Qualification(self.source.identity.digest, self.target.identity.digest, digest("evaluation"))
        self.owner.qualify = lambda q: q == self.qualification
        self.owner.create(self.partition, self.source)

    def tearDown(self):
        self.owner.close()
        self.temp.cleanup()

    def test_real_gru_hidden_state_relation_survives_wrapper_conversion(self):
        state = self.kernel.observe(self.kernel.initial_state("run"), [1.0, -0.5, 0.25], episode_id="run", cursor=0)
        original = copy.deepcopy(state)
        migrated = self.target.migrate_state_from(self.source, state)
        self.assertEqual(migrated, {**state, "weights_sha256": self.target.inner.kernel.weights_sha256})
        self.assertEqual(state, original)

    def test_owner_cutover_is_atomic_and_original_migration_replays(self):
        checkpoint = self.owner.checkpoint(self.partition)
        arguments = dict(operation_id="upgrade", checkpoint_id=checkpoint["digest"])
        receipt = self.owner.migrate(self.partition, self.source, self.target, self.qualification, **arguments)
        self.assertEqual(self.owner.migrate(self.partition, self.source, self.target, self.qualification, **arguments), receipt)
        self.assertEqual(self.owner.status(self.partition)["identity"], asdict(self.target.identity))
        self.assertEqual(receipt["target_checkpoint"]["state"]["hidden"], checkpoint["state"]["hidden"])

    def test_native_owner_image_and_wrapper_subclass_changes_refuse(self):
        state = self.source.initial_state()
        for field, value in (("owner", object()), ("native", object()), ("image_sha256", digest("other-image"))):
            with self.subTest(field=field), patch.object(self.target, field, value), self.assertRaises(CellError):
                self.target.migrate_state_from(self.source, state)
        class Derived(HiaCellComponent):
            pass
        derived = Derived(self.owner, self.target.inner, self.native, candidate_sha256=digest("derived"), image_sha256=digest("image"))
        with self.assertRaises(CellError):
            derived.migrate_state_from(self.source, state)

    def test_converter_cannot_replace_both_transport_references(self):
        converter = self.target.inner.migrate_state_from
        def changed(source, state):
            migrated = converter(source, state)
            self.source.native = self.target.native = object()
            return migrated
        with patch.object(self.target.inner, "migrate_state_from", changed), self.assertRaises(CellError):
            self.target.migrate_state_from(self.source, self.source.initial_state())

    def test_pending_original_invocation_still_blocks_cutover(self):
        checkpoint = self.owner.checkpoint(self.partition)
        with patch.object(self.source, "step", side_effect=RuntimeError("fault before result")):
            with self.assertRaises(PendingExecution):
                self.owner.step(self.partition, self.source, "uncertain", {"operation": "predict", "action": [0.0]})
        before = self.owner.status(self.partition)
        with self.assertRaises(PendingExecution):
            self.owner.migrate(self.partition, self.source, self.target, self.qualification, operation_id="upgrade", checkpoint_id=checkpoint["digest"])
        self.assertEqual(self.owner.status(self.partition), before)
        self.assertEqual(self.owner.db.execute("SELECT count(*) FROM migrations").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
