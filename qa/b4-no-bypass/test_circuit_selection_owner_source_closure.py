"""Keep original retained-model Selection on live owners and pinned signatures."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_selection_owner_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
OWNER = "codex-rs/hepta-agentd/src/circuit_selection_receipt_owner.rs"
CELL = "codex-rs/hepta-agentd/src/circuit_feature_current_learning.rs"


class OriginalCircuitSelectionOwnerSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.rows = [
            row for row in cls.manifest["protected_file"] if row["path"] == OWNER
        ]
        cls.source = (ROOT / OWNER).read_text()

    def rejects(self, function, marker):
        start = self.source.index(function)
        end = PROOF._rust_item_end(PROOF._strip_rust_non_code(self.source), start)
        self.assertIsNotNone(end)
        offset = self.source.index(marker, start, end + 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / OWNER
            target.parent.mkdir(parents=True)
            target.write_text(self.source)
            PROOF._verify_protected_files(root, {"protected_file": self.rows})
            target.write_text(
                self.source[:offset] + self.source[offset + len(marker):]
            )
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": self.rows})

    def test_original_selector_authority_entries_stay_closed(self):
        rows = {
            row.identifier: row for row in PROOF._boundary_rows(self.manifest)
        }
        sources = {
            OWNER: PROOF._strip_rust_non_code(self.source),
        }
        for suffix in ("create", "recover", "attest", "readback"):
            row = rows["learning_original_circuit_selection_receipt_" + suffix]
            self.assertIn(
                row.identifier,
                self.manifest["privileged_inventory"]["required_boundary_ids"],
            )
            self.assertEqual(row.product_callers, ())
            PROOF._verify_boundary(ROOT, row, sources, ())
            method = row.symbol.rsplit("::", 1)[1]
            changed = dict(sources)
            changed["codex-rs/hepta-agentd/src/unregistered_selector.rs"] = (
                "fn unexpected(owner: &OriginalCircuitSelectionReceiptOwnerV1) {"
                f" owner.{method}(); }}"
            )
            with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                PROOF._verify_boundary(ROOT, row, changed, ())
        self.assertEqual(
            rows["root_learning_original_stage_assembly"].product_callers, ()
        )

    def test_selection_reads_the_original_sealed_publication(self):
        rows = {
            row.identifier: row for row in PROOF._boundary_rows(self.manifest)
        }
        row = rows["circuit_feature_original_selection_observation"]
        self.assertIn(
            row.identifier,
            self.manifest["privileged_inventory"]["required_boundary_ids"],
        )
        self.assertEqual(row.product_callers, (OWNER,))
        sources = {
            path: PROOF._strip_rust_non_code((ROOT / path).read_text())
            for path in (OWNER, CELL)
        }
        PROOF._verify_boundary(ROOT, row, sources, ())
        self.rejects("fn prepare(", "cell.read_learning_selection(&coordinator)?")
        self.rejects(
            "fn prepare(", "self.config.scope.validate_snapshot(source.snapshot)?"
        )

    def test_original_training_pin_and_physical_readbacks_cannot_be_skipped(self):
        for function, marker in (
            ("fn authenticate_training(", "if evidence != &config.training_evidence"),
            ("fn validate_config(", "&config.training_evidence.signature"),
            ("fn training_evidence(", "training_receipt(&self.config)?"),
            ("fn authenticate_completed(", "if self.prepare(source)? != *observed"),
            ("fn authenticate_completed(", "if self.journal.read(&self.saved)? != bytes"),
            ("fn authenticate_completed(", "signed.issued_at"),
        ):
            self.rejects(function, marker)

    def test_missing_pending_deadline_and_role_separation_remain_distinct(self):
        for function, marker in (
            ("fn attest_original_selection(", "let started_at = now()?;"),
            ("fn attest_original_selection(", "require_new_attestation(&self.config, started_at, now()?)?"),
            ("fn attest_original_selection(", "require_new_attestation(&self.config, started_at, claim_at)?"),
            ("fn attest_original_selection(", "ProductEvaluationExecutionStoreErrorV1::Missing"),
            ("fn attest_original_selection(", "require_new_attestation(config, started_at, issued_at)?"),
            ("fn require_new_attestation(", "current >= config.decision.request.envelope.expiry_unix_seconds"),
            ("fn authenticate_completed(", "if current < started_at"),
            ("fn authenticate_training(", "verify_independent_roles(verified.principal(), &config.signer.principal, current)"),
            ("fn authenticate_training(", "if verified.controller_id() == &config.signer.controller_id"),
            ("fn training_receipt(", "LearningIterationObservationV1::TrainingNoUpdateV2(_)"),
        ):
            self.rejects(function, marker)


if __name__ == "__main__":
    unittest.main()
