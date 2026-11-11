"""Keep full-snapshot Training recovery on the original read-only typed owner."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("training_snapshot_proof", ROOT / "scripts/verify_hepta_callers.py")
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
SOURCE = "codex-rs/hepta-agentd/src/cell_q24_training_snapshot_readback.rs"
STAGE = "codex-rs/hepta-agentd/src/cell_q24_training_stage.rs"


class OriginalTrainingSnapshotSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.source = (ROOT / SOURCE).read_text()
        cls.rows = [row for row in cls.manifest["protected_file"] if row["path"] == SOURCE]

    def rejects(self, marker, replacement=""):
        self.assertIn(marker, self.source)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / SOURCE
            target.parent.mkdir(parents=True)
            target.write_text(self.source)
            PROOF._verify_protected_files(root, {"protected_file": self.rows})
            target.write_text(self.source.replace(marker, replacement, 1))
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": self.rows})

    def test_full_structure_retained_receipt_and_original_completion_are_all_required(self):
        for marker in (
            "LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;",
            "if expected.observation.stage() != LearningIterationStageV1::Training",
            "LearningIterationCoordinatorV1::new(snapshot.request.clone(), snapshot.owners.clone())?",
            "for retained in &snapshot.receipts",
            "if retained.observation.stage() == LearningIterationStageV1::Training",
            "if retained != expected",
            "dataset.record(retained.clone(), retained.observed_unix_seconds)?;",
            "if dataset.next_stage() != Some(LearningIterationStageV1::Training)",
            "extension.record(expected.clone(), expected.observed_unix_seconds)?;",
            "let completed = training.readback(dataset.snapshot()).await?;",
            "if &completed.receipt != expected",
        ):
            with self.subTest(marker=marker):
                self.rejects(marker)

    def test_checks_cannot_hide_in_dead_blocks_or_start_work(self):
        marker = "LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;"
        self.rejects(marker, "if false {" + marker + "}")
        for mutation in ("training.execute_training(dataset.snapshot(), cancellation).await?", "training.attest_original_completion(native)?"):
            with self.subTest(mutation=mutation):
                self.rejects("training.readback(dataset.snapshot()).await?", mutation)

    def test_only_snapshot_adapter_reads_stage_and_no_product_host_is_claimed(self):
        rows = {row.identifier: row for row in PROOF._boundary_rows(self.manifest)}
        sources = {path: PROOF._strip_rust_non_code((ROOT / path).read_text()) for path in (SOURCE, STAGE)}
        for name, callers in (
            ("learning_original_training_stage_readback", (SOURCE,)),
            ("learning_original_training_snapshot_readback", ()),
        ):
            row = rows[name]
            self.assertIn(name, self.manifest["privileged_inventory"]["required_boundary_ids"])
            self.assertEqual(row.product_callers, callers)
            PROOF._verify_boundary(ROOT, row, sources, ())
            changed = dict(sources)
            call = "read_cell_q24_training_snapshot_v1()" if not callers else "owner.readback()"
            changed["codex-rs/hepta-agentd/src/unregistered_training_read.rs"] = (
                f"fn unexpected(owner: &OriginalCellQ24TrainingStageV1) {{ {call}; }}"
            )
            with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                PROOF._verify_boundary(ROOT, row, changed, ())
        self.assertEqual(rows["root_learning_original_stage_assembly"].product_callers, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))


if __name__ == "__main__":
    unittest.main()
