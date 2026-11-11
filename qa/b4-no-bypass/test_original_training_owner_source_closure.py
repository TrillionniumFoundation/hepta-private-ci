"""Keep native Generator receipts on original keys, observations and journals."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_training_owner_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
OWNER = "codex-rs/hepta-agentd/src/cell_q24_training_receipt_owner.rs"
STAGE = "codex-rs/hepta-agentd/src/cell_q24_training_stage.rs"
SNAPSHOT = "codex-rs/hepta-agentd/src/cell_q24_training_snapshot_readback.rs"


class OriginalTrainingOwnerSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.rows = [
            row for row in cls.manifest["protected_file"] if row["path"] == OWNER
        ]
        cls.source = (ROOT / OWNER).read_text()

    def rejects(self, function, marker, replacement="", path=OWNER):
        source = (ROOT / path).read_text()
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        start = source.index(function)
        end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
        self.assertIsNotNone(end)
        offset = source.index(marker, start, end + 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(
                source[:offset] + replacement + source[offset + len(marker) :]
            )
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_training_receipt_ports_remain_unassembled_and_caller_closed(self):
        rows = {row.identifier: row for row in PROOF._boundary_rows(self.manifest)}
        sources = {
            path: PROOF._strip_rust_non_code((ROOT / path).read_text())
            for path in (OWNER, STAGE)
        }
        for suffix in ("create", "recover", "attest", "readback"):
            row = rows["learning_original_training_receipt_" + suffix]
            self.assertIn(
                row.identifier,
                self.manifest["privileged_inventory"]["required_boundary_ids"],
            )
            self.assertEqual(
                row.product_callers,
                (STAGE,) if suffix in ("attest", "readback") else (),
            )
            PROOF._verify_boundary(ROOT, row, sources, ())
            method = row.symbol.rsplit("::", 1)[1]
            changed = dict(sources)
            changed["codex-rs/hepta-agentd/src/unregistered_training_signer.rs"] = (
                f"fn unexpected(owner: &OriginalCellQ24TrainingReceiptOwnerV1) {{ owner.{method}(); }}"
            )
            with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                PROOF._verify_boundary(ROOT, row, changed, ())
        self.assertEqual(
            rows["root_learning_original_stage_assembly"].product_callers, ()
        )

    def test_pair_consumer_is_the_only_native_execute_and_scope_caller(self):
        native = "codex-rs/hepta-agentd/src/cell_composed_q24_training_owner.rs"
        rows = {row.identifier: row for row in PROOF._boundary_rows(self.manifest)}
        sources = {
            path: PROOF._strip_rust_non_code((ROOT / path).read_text())
            for path in (OWNER, STAGE, native, SNAPSHOT)
        }
        for name in (
            "cell_q24_original_training_execute",
            "cell_q24_original_training_pair_binding",
        ):
            row = rows[name]
            self.assertIn(
                name, self.manifest["privileged_inventory"]["required_boundary_ids"]
            )
            self.assertEqual(row.product_callers, (STAGE,))
            PROOF._verify_boundary(ROOT, row, sources, ())
            changed = dict(sources)
            method = row.symbol.rsplit("::", 1)[1]
            changed["codex-rs/hepta-agentd/src/unregistered_fit.rs"] = (
                f"fn unexpected(owner: &CellQ24TrainingOwnerV1) {{ owner.{method}(); }}"
            )
            with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                PROOF._verify_boundary(ROOT, row, changed, ())
        for suffix in ("constructor", "execute", "readback", "attestation"):
            row = rows["learning_original_training_stage_" + suffix]
            self.assertEqual(
                row.product_callers, (SNAPSHOT,) if suffix == "readback" else ()
            )
            PROOF._verify_boundary(ROOT, row, sources, ())

    def test_pair_requires_exact_missing_enrollment_and_retained_blocking_lane(self):
        for function, markers in (
            (
                "fn execute_training(",
                (
                    "self.require_dataset(dataset)?",
                    "owners.prepare_training(&cancellation)?",
                    "owners.complete_training(prepared)",
                ),
            ),
            (
                "fn prepare_training(",
                (
                    "owners.receipts.journal.read(&owners.receipts.saved)",
                    ".read_original_completion()",
                    ".map(TrainingPreparation::Completed)",
                    "ProductEvaluationExecutionStoreErrorV1::Missing",
                    "let retained_outcome = match training.readback()",
                    "Ok(outcome) => Some(outcome)",
                    "Err(CellQ24TrainingOwnerErrorV1::Store(",
                    ")) => None",
                    "Err(error) => return Err(error.into())",
                    "super::now()",
                    ".require_signer_binding(",
                    "LearningEvidenceRoleV1::Generator",
                    "if now >= receipts.config.dataset.request.envelope.expiry_unix_seconds",
                    "return Err(Error::DeadlineExceeded)",
                    "Some(outcome) => outcome",
                    "None => training.fit_or_readback(cancellation)?",
                    "Ok(TrainingPreparation::Unattested(outcome))",
                ),
            ),
            (
                "fn complete_training(",
                (
                    "match prepared",
                    "TrainingPreparation::Completed(completed) => Ok(completed)",
                    "TrainingPreparation::Unattested(outcome)",
                    ".attest_original_completion(&mut self.training)?",
                ),
            ),
            (
                "fn in_lane<",
                (
                    ".try_acquire_owned()",
                    "let _permit = permit;",
                    "owners.try_lock()",
                    "training.require_original_dataset_scope(",
                ),
            ),
            (
                "fn receipt_attestation(",
                ("self.readback(dataset).await?", "if &completed.receipt != expected"),
            ),
            (
                "fn read_original_completion(&mut self)",
                ("self.receipts.readback(training)?", "training.readback()?"),
            ),
        ):
            for marker in markers:
                with self.subTest(function=function, marker=marker):
                    self.rejects(function, marker, path=STAGE)

    def test_signer_enrollment_exact_dataset_and_scope_precede_signature_custody(self):
        for function, markers in (
            ("fn create(", ("validate_config(&config, &key)?",)),
            ("fn recover(", ("validate_config(&config, &key)?",)),
            (
                "fn validate_config(",
                (
                    "LearningIterationCoordinatorV1::from_snapshot(config.dataset.clone())?",
                    "config.scope.validate_snapshot(&config.dataset)?",
                    "key.verifying_key().to_bytes() != config.signer.verifying_key",
                    "config.signer.principal.principal_id != config.dataset.owners.trainer",
                    "config.dataset.owners.evidence_trust_digest != config.verifier.trust_digest()",
                    "config.dataset.request.envelope.objective_digest != config.verifier.objective_digest()",
                    "config.verifier.require_signer_binding(",
                    "LearningEvidenceRoleV1::Generator",
                    "config.dataset.head_digest.as_array()",
                    "config.scope.binding().as_array()",
                    "config.verifier.trust_digest().as_array()",
                    "&config.signer.verifying_key",
                ),
            ),
        ):
            for marker in markers:
                with self.subTest(function=function, marker=marker):
                    self.rejects(function, marker)

    def test_native_completed_read_precedes_claim_and_no_caller_payload_is_signed(self):
        for marker in (
            "training.read_learning_observation(&self.config.dataset)?",
            "require_observation(&self.config, &observation)?",
            "self.journal.commit_once(saved, ||",
            "training_receipt(config, &observation, now()?)",
            "learning_iteration_receipt_signing_bytes_v1(&receipt)",
            "learning_owner_evidence::encode(&payload, &signed)",
            "self.authenticate_completed(training, &observation, &bytes)",
        ):
            with self.subTest(marker=marker):
                self.rejects("fn attest_original_completion(", marker)
        marker = "require_observation(&self.config, &observation)?;"
        self.rejects(
            "fn attest_original_completion(", marker, "if false {" + marker + "}"
        )

    def test_readback_requires_original_time_exact_payload_identity_and_both_current_heads(
        self,
    ):
        for marker in (
            "training_receipt(&self.config, observation, signed.issued_at)?",
            "if payload != learning_iteration_receipt_signing_bytes_v1(&receipt)?",
            "self.config.verifier.verify(",
            "LearningEvidenceRoleV1::Generator",
            "verified.principal() != &self.config.signer.principal",
            "verified.controller_id() != &self.config.signer.controller_id",
            "signed.evidence_id != evidence_id(self.saved.binding_digest)?",
            "training.read_learning_observation(&self.config.dataset)? != *observation",
            "self.journal.read(&self.saved)? != bytes",
        ):
            with self.subTest(marker=marker):
                self.rejects("fn authenticate_completed(", marker)


if __name__ == "__main__":
    unittest.main()
