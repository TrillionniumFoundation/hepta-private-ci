"""Mutation controls for original Observer Experience/Dataset receipt owners."""

from pathlib import Path
import re
import tomllib
import unittest

import test_original_q24_dataset_source_closure as original


ROOT = Path(__file__).resolve().parents[2]
PROOF = original.PROOF
OWNER = original.AGENT + "cell_q24_source_receipt_owner.rs"
DERIVATION = original.RECEIPTS
SIGNING = original.AGENT + "cell_q24_source_receipt_signing.rs"
METHODS = ("create", "recover", "attest_experience", "readback_experience", "attest_dataset", "readback_dataset")


class OriginalQ24SourceReceiptClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def verify_source(self, path, source):
        original.OriginalQ24DatasetSourceClosureTests.verify_source(self, path, source)
        if path != OWNER:
            return
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        for method in METHODS[2:]:
            start, end = original.function_span(code, "fn " + method + "<")
            body = code[start:end]
            if "return Ok(" in body:
                raise PROOF.VerificationFailure("source receipt cannot return before its fences")
            if method.startswith("readback") and re.search(r"\b(?:sign_original|commit_once|attest_experience|attest_dataset)\s*\(", body):
                raise PROOF.VerificationFailure("original readback cannot issue work or a signature")
        allowed = [original.function_span(code, "fn " + method + "<") for method in ("attest_experience", "attest_dataset")]
        for method in ("sign_original", "commit_once"):
            calls = list(re.finditer(r"\b" + method + r"\s*\(", code))
            if len(calls) != 2 or any(not any(start < match.start() < end for start, end in allowed) for match in calls):
                raise PROOF.VerificationFailure("only original issuance may claim and sign")

    rejects = original.OriginalQ24DatasetSourceClosureTests.rejects
    rejects_each = original.OriginalQ24DatasetSourceClosureTests.rejects_each

    def test_six_public_apis_are_closed_and_do_not_install_root_or_stage_owners(self):
        sources = {path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / path).read_text())) for path in (OWNER, DERIVATION, SIGNING)}
        for method in METHODS:
            row = self.boundaries["cell_q24_original_source_receipt_" + method]
            self.assertEqual(row.product_callers, ())
            self.assertIn(row.identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
            PROOF._verify_boundary(ROOT, row, sources, ())
            changed = dict(sources)
            changed[original.AGENT + "unregistered_observer.rs"] = f"fn bypass(owner: &mut OriginalCellQ24SourceReceiptOwnerV1) {{ owner.{method}(); }}"
            with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                PROOF._verify_boundary(ROOT, row, changed, ())
        self.assertEqual(self.boundaries["root_learning_original_stage_assembly"].product_callers, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_original_files_complete_material_and_role_binding_precede_create_and_recover(self):
        for method in ("create", "recover"):
            self.rejects_each(OWNER, "fn " + method + "(", (
                "recovery::original_material_bytes(&material)?",
                "validate_config(&config, &key, &original_material)?",
                "LearningOwnerJournalV1::" + method + "(file, witness, saved.binding_digest)?",
            ))
        self.rejects_each(SIGNING, "fn validate_config(", (
            "coordinator.next_stage() != Some(config.predecessor.stage())",
            "key.verifying_key().to_bytes() != config.signer.verifying_key",
            "cut.owners.owner(config.predecessor.stage())",
            "cut.owners.evidence_trust_digest != config.verifier.trust_digest()",
            "cut.request.envelope.objective_digest != config.verifier.objective_digest()",
            "config.scope.validate_snapshot(cut)?",
            "Digest32::of_bytes(original_material).as_array()",
            "Digest32::of_bytes(&predecessor_evidence).as_array()",
        ))

    def test_experience_checks_stage_source_and_claim_before_signing(self):
        self.rejects_each(OWNER, "fn attest_experience<", (
            "self.require_stage(LearningIterationStageV1::Experience)?",
            "self.completed_or_admit()?", "None => self.journal.commit_once(saved, ||",
            "if checked != original", "sign_original(config, key, &original, saved.binding_digest)",
            "self.finish_experience(ledger, source, identity, &original, &bytes)",
        ))
        for occurrence in (0, 1):
            self.rejects(OWNER, "fn attest_experience<", "derivation::read(", occurrence=occurrence)

    def test_dataset_reads_actual_experience_before_claim_before_sign_and_after_completion(self):
        for occurrence in (0, 1, 2):
            self.rejects(OWNER, "fn attest_dataset<", "require_experience(", occurrence=occurrence)
        for occurrence in (0, 1):
            self.rejects(OWNER, "fn readback_dataset<", "require_experience(", occurrence=occurrence)
        self.rejects_each(OWNER, "fn require_experience<", (
            "experience.require_stage(LearningIterationStageV1::Experience)?",
            "experience.config.predecessor.snapshot() != initial.snapshot()",
            "experience.config.scope != config.scope",
            "experience.original_material != original_material",
            "OriginalCellQ24SourceReceiptOwnerV1::readback_experience(",
            "snapshot.receipts.as_slice() != std::slice::from_ref(&receipt)",
            "&original_signature != attestation",
        ))

    def test_completed_payload_original_time_and_current_observer_are_reauthenticated(self):
        self.rejects_each(OWNER, "fn authenticate(", (
            "learning_owner_evidence::decode(bytes)?",
            "derivation::receipt(&self.config, original, signed.issued_at)?",
            "payload != learning_iteration_receipt_signing_bytes_v1(&receipt)?",
            "LearningEvidenceRoleV1::Observer", "now()?",
            "verified.principal() != &self.config.signer.principal",
            "verified.controller_id() != &self.config.signer.controller_id",
            "signed.evidence_id != evidence_id(self.saved.binding_digest)?",
        ))

    def test_source_and_own_journal_fences_are_required_after_cross_owner_reads(self):
        for method in ("attest_dataset", "readback_dataset", "finish_experience"):
            self.rejects_each(OWNER, "fn " + method + "<", (
                "self.require_source(", "if self.journal.read(&self.saved)? != bytes",
                "return Err(LearningOriginalOwnerErrorV1::CommitUncertain.into())",
            ))
        self.rejects_each(OWNER, "fn require_source<", ("derivation::read(", "!= *original"))

    def test_missing_is_the_only_admission_path_and_deadline_and_role_stay_current(self):
        self.rejects_each(OWNER, "fn completed_or_admit(", (
            "self.journal.read(&self.saved)", "ProductEvaluationExecutionStoreErrorV1::Missing",
            "let at = now()?", "expiry_unix_seconds", "require_signer_binding(",
            "LearningEvidenceRoleV1::Observer", "Err(error) => Err(error.into())",
        ))
        self.rejects_each(SIGNING, "fn sign_original(", (
            "let issued_at = now()?", "expiry_unix_seconds", "require_signer_binding(",
            "checked_add(config.maximum_signature_lifetime_seconds)",
            "min(config.signer.principal.expires_at)",
            "key.sign(&signed.signing_bytes()).to_bytes()", "config.verifier.verify(",
            "learning_owner_evidence::encode(&payload, &signed)",
        ))

    def test_original_prefix_plan_payload_receipt_and_complete_selected_records_are_required(self):
        self.rejects_each(DERIVATION, "fn read<", (
            "recovery::original_material_bytes(material)? != original_material",
            "material.require_request_source(&request.source_run_id, request.completed_task_receipt)?",
            "recovery::original_prefix(", "material.dataset.snapshot.ledger_head_digest",
            "snapshot_id: material.dataset.snapshot.snapshot_id.clone()",
            "inclusion_policy_digest: material.dataset.inclusion_policy_digest",
            "dataset_freeze_signing_payload_v2(&prefix, &plan)?",
            "if payload != material.freeze_payload", "LearningEvidenceRoleV1::Evaluator",
            "freeze_dataset_from_ledger(&prefix, plan, verified.principal().clone(), at)?",
            "!= material.dataset", "LedgerWriter::read_dataset_records(ledger, &material.dataset, at)?",
            "!prefix.records().contains(*record)",
        ))

    def test_unique_trigger_terminal_outcome_original_publication_and_fresh_source_are_required(self):
        self.rejects_each(DERIVATION, "fn read<", (
            "decision.record_id == request.source_run_id", "decisions.next().is_some()",
            "outcome.episode_id == decision.episode_id", "outcomes.next().is_some()",
            "read_run_publication(identity, &request.source_run_id)",
            "!material.publications.contains(&published)", "Some(request.completed_task_receipt)",
            "outcome.support_digest != published.publication_digest()",
            "AuthenticatedOutcomeTerminality::Terminal",
            "super::super::current_ledger(ledger, identity, &material.profile)? != before",
        ))
        for occurrence in (0, 1):
            self.rejects(DERIVATION, "fn read<", "OriginalCellQ24DatasetV1::revalidate(material, ledger, source, identity)?", occurrence=occurrence)

    def test_experience_uses_the_actual_terminal_outcome_observer_identity(self):
        self.rejects_each(DERIVATION, "fn read<", (
            "config.predecessor.stage() == LearningIterationStageV1::Experience",
            "outcome.observer_id != config.signer.principal.principal_id",
            "outcome.observer_controller_id != config.signer.controller_id",
            "outcome.observer_credential_chain_digest",
            "config.signer.principal.credential_chain_digest",
            "outcome.observer_signing_key_digest",
            "config.signer.principal.signing_key_digest",
            "outcome.observer_scope_digest != config.signer.principal.scope_digest",
            "outcome.observer_authority_epoch != config.signer.principal.authority_epoch",
        ))

    def test_historical_identity_and_dataset_counts_are_derived_and_preserved(self):
        self.rejects_each(DERIVATION, "fn read<", (
            "ledger.binding_digest().as_array()", "decision.episode_id.as_str()",
            "decision_record.event_digest.as_array()", "outcome_record.event_digest.as_array()",
            "Digest32::of_bytes(original_material).as_array()", "decision_record.chain_digest.as_array()",
            "outcome_record.chain_digest.as_array()", "published.publication_digest().as_array()",
            "current: before", "dataset: material.dataset.snapshot.dataset_digest",
            "revocation_cut: material.dataset.revocation_cut_digest", "rows: material.batch.rows()",
            "bytes: material.batch.encoded().len() as u64",
        ))
        self.rejects_each(DERIVATION, "fn receipt(", (
            "withdrawal_frontier: original.revocation_cut", "observed_unix_seconds,\n        observation,",
            "coordinator.record(receipt.clone(), observed_unix_seconds)?",
            "config.scope.validate_snapshot(coordinator.snapshot())?",
        ))

    def test_readback_cannot_become_an_issuer_or_return_early(self):
        for method in ("readback_experience", "readback_dataset"):
            source = (ROOT / OWNER).read_text()
            start, end = original.function_span(source, "fn " + method + "<")
            offset = source.index("{", start, end)
            for insertion in (" sign_original(); ", " return Ok(unimplemented!()); "):
                changed = source[:offset + 1] + insertion + source[offset + 1:]
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verify_source(OWNER, changed)


if __name__ == "__main__":
    unittest.main()
