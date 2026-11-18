"""HIA profile activation and rejection of missing native continuation history.

The native sentinel is not executed here; actual native cold replay is exercised
by the joint qualification and the separately retained HIA store probe.
"""

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hepta_cells.component_types import CellError, Partition, PendingExecution
from hepta_cells.deterministic import NumericAlgorithm
from hepta_cells.hia_component import HiaCellComponent
from hepta_cells.lifecycle import CellOwner
from hepta_cells.owner_hia_store import HIA_SCHEMA


class HiaOwnerStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "owner.sqlite"
        self.partition = Partition("principal", "agent", "cell", "run")
        self.owner = CellOwner(self.path)
        self.addCleanup(lambda: self.owner.close())
        self.inner = NumericAlgorithm("dot", "a" * 64)

    def wrapper(self):
        return HiaCellComponent(
            self.owner,
            self.inner,
            object(),
            candidate_sha256="b" * 64,
            image_sha256="c" * 64,
        )

    def reject_cold_unchanged(self):
        self.owner.close()
        before = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in self.root.iterdir()
            if p.is_file()
        }
        with self.assertRaises(CellError):
            CellOwner(self.path)
        self.assertEqual(
            {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.iterdir()
                if p.is_file()
            },
            before,
        )

    def test_explicit_activation_preserves_plain_owner_and_cold_hia_state(self):
        self.owner.close()
        self.owner = CellOwner(self.path)
        component = self.wrapper()
        original = self.owner.create(self.partition, component)
        self.owner.close()
        self.owner = CellOwner(self.path)
        self.assertEqual(self.owner.checkpoint(self.partition), original)

    def test_legacy_exact_extension_is_accepted_without_schema_rewrite(self):
        self.owner.db.execute(HIA_SCHEMA)
        schema = self.owner.db.execute(
            "SELECT sql FROM sqlite_master WHERE name='hia_cell_calls'"
        ).fetchone()[0]
        self.wrapper()
        self.owner.close()
        self.owner = CellOwner(self.path)
        self.assertEqual(
            self.owner.db.execute(
                "SELECT sql FROM sqlite_master WHERE name='hia_cell_calls'"
            ).fetchone()[0],
            schema,
        )

    def test_missing_extension_with_retained_hia_identity_is_not_recreated(self):
        self.owner.create(self.partition, self.wrapper())
        self.owner.db.execute("DROP TABLE hia_cell_calls")
        with self.assertRaisesRegex(CellError, "lost its continuation table"):
            self.wrapper()
        self.reject_cold_unchanged()

    def test_empty_pre_begin_pending_remains_unknown_after_cold_open(self):
        component = self.wrapper()
        self.owner.create(self.partition, component)
        with patch.object(
            component, "step", side_effect=RuntimeError("before native BEGIN")
        ):
            with self.assertRaises(PendingExecution):
                self.owner.step(
                    self.partition, component, "pending", {"left": [1], "right": [2]}
                )
        before = self.owner.status(self.partition)
        self.owner.close()
        self.owner = CellOwner(self.path)
        component = self.wrapper()
        with self.assertRaises(PendingExecution):
            self.owner.reconcile(
                self.partition, component, "pending", component.readback
            )
        self.assertEqual(self.owner.status(self.partition), before)
        self.assertEqual(
            self.owner.db.execute("SELECT count(*) FROM hia_cell_calls").fetchone()[0],
            0,
        )

    def test_unrecognized_extra_table_is_rejected(self):
        self.wrapper()
        self.owner.db.execute("CREATE TABLE unrelated(value TEXT)")
        self.reject_cold_unchanged()

    def test_missing_extension_unique_constraint_is_rejected(self):
        self.wrapper()
        self.owner.db.execute("DROP TABLE hia_cell_calls")
        self.owner.db.execute(
            HIA_SCHEMA.replace(", PRIMARY KEY(partition, request)", "")
        )
        self.reject_cold_unchanged()


if __name__ == "__main__":
    unittest.main()
