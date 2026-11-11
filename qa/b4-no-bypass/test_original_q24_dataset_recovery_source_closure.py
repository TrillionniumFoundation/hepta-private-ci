"""Mutation controls for complete original Dataset recovery, never a custody grant."""

from pathlib import Path
import re
import tomllib
import unittest

import test_original_q24_dataset_source_closure as original


ROOT = Path(__file__).resolve().parents[2]
PROOF = original.PROOF
OWNER = original.AGENT + "cell_q24_dataset_recovery.rs"
CODEC = original.AGENT + "cell_q24_dataset_recovery_codec.rs"
PREFIX = "cell_q24_original_dataset_recovery_"


class OriginalQ24DatasetRecoverySourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {
            row.identifier: row for row in PROOF._boundary_rows(cls.manifest)
        }

    def verify_source(self, path, source):
        original.OriginalQ24DatasetSourceClosureTests.verify_source(self, path, source)
        if path == OWNER:
            code = PROOF._strip_rust_non_code(source)
            for function, terminal in (("fn retain<", "Ok(())"), ("fn restore<", "Ok(material)")):
                start, end = original.function_span(code, function)
                body = code[start:end]
                if "return Ok(" in body or not re.search(re.escape(terminal) + r"\s*}\s*$", body):
                    raise PROOF.VerificationFailure("recovery success must follow all owner fences")

    rejects = original.OriginalQ24DatasetSourceClosureTests.rejects
    rejects_each = original.OriginalQ24DatasetSourceClosureTests.rejects_each

    def test_recovery_apis_are_closed_and_only_internal_revalidation_is_added(self):
        sources = {
            path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / path).read_text()))
            for path in (OWNER, CODEC, original.DATASET, original.STAGE)
        }
        for method in ("create", "recover", "retain", "restore"):
            row = self.boundaries[PREFIX + method]
            self.assertEqual(row.product_callers, ())
            self.assertIn(row.identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
            PROOF._verify_boundary(ROOT, row, sources, ())
            changed = dict(sources)
            changed[original.AGENT + "unregistered_recovery.rs"] = (
                f"fn bypass(owner: &OriginalCellQ24DatasetRecoveryOwnerV1) {{ owner.{method}(); }}"
            )
            with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                PROOF._verify_boundary(ROOT, row, changed, ())
        row = self.boundaries["cell_q24_original_dataset_revalidate"]
        self.assertEqual(set(row.product_callers), {original.STAGE, OWNER})
        PROOF._verify_boundary(ROOT, row, sources, ())
        self.assertEqual(self.boundaries["root_learning_original_stage_assembly"].product_callers, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_fresh_and_recovered_owner_use_original_profile_and_distinct_journal_modes(self):
        for method in ("create", "recover"):
            self.rejects_each(OWNER, f"fn {method}(", (
                "owner_binding(&profile)?",
                f"LearningOwnerJournalV1::{method}(file, witness, binding)?",
            ))
        self.rejects_each(OWNER, "fn key(", (
            "plan.objective_digest != self.profile.objective_digest",
            "plan.inclusion_policy_digest != self.profile.digest()?",
            "plan_id: plan.snapshot_id.clone()",
            "binding_digest: owner_binding(&self.profile)?",
        ))

    def test_retain_keeps_full_binding_preclaim_encoding_and_original_completed_bytes(self):
        self.rejects_each(OWNER, "fn retain<", (
            "material.profile != self.profile",
            "material.dataset.snapshot.snapshot_id != plan.snapshot_id",
            "material.dataset.snapshot.objective_digest != plan.objective_digest",
            "material.dataset.inclusion_policy_digest != plan.inclusion_policy_digest",
            "codec::encode(&codec::SavedMaterial::from_original(plan, material)?)?",
            "self.journal.commit_once(&key, || Ok(bytes.clone()))?",
            "if saved != bytes",
        ))
        marker = "OriginalCellQ24DatasetV1::revalidate(material, ledger, source, identity)?"
        for occurrence in (0, 1):
            self.rejects(OWNER, "fn retain<", marker, occurrence=occurrence)

    def test_actual_historical_prefix_replays_all_record_fields_and_exact_head(self):
        self.rejects_each(OWNER, "fn original_prefix(", (
            "ledger: &LedgerWriter", "let actual = ledger.snapshot()?",
            "LearningLedger::new()", "for record in actual.records()",
            ".append(record.event.clone())", ".map_err(ProductionLedgerError::from)?",
            "appended.disposition != AppendDisposition::Appended",
            "replay.records().last() != Some(record)", "record.chain_digest == head",
            "return Ok(replay.snapshot())",
        ))

    def test_restore_requires_original_full_plan_payload_signature_and_current_clock(self):
        self.rejects_each(OWNER, "fn restore<", (
            "current_ledger(ledger, identity, &self.profile)?",
            "let bytes = self.journal.read(&key)?", "codec::decode(&bytes)?",
            "saved.profile != self.profile || saved.plan != *plan",
            "original_prefix(ledger, saved.original_head)?",
            "dataset_freeze_signing_payload_v2(&prefix, plan)?",
            "if payload != saved.freeze_payload", "let at = now()?",
            ".verifier()", ".verify(", "LearningEvidenceRoleV1::Evaluator",
            "&saved.evidence", "&payload", "verified.principal().clone()",
            "freeze_dataset_from_ledger(", "plan.clone()",
        ))

    def test_complete_receipt_and_current_source_batch_cannot_be_digest_substituted(self):
        self.rejects_each(OWNER, "fn restore<", (
            "codec::receipt_bytes(&dataset)? != saved.receipt",
            "collect(ledger, source, identity, &self.profile, &dataset)?",
            "batch.encoded() != saved.batch",
            "OriginalCellQ24DatasetV1::revalidate(&material, ledger, source, identity)?",
            "current_ledger(ledger, identity, &self.profile)? != before",
        ))
        for marker in (
            "s.snapshot_id", "s.ledger_head_digest", "s.objective_digest",
            "s.eligible_frontier", "s.outcome_watermark", "s.source_record_digests.len() > 4096",
            "for d in &s.source_record_digests", "s.pending_outcomes", "s.censored_outcomes",
            "s.dataset_digest", "s.authority.flags().wire_mask()", "receipt.producer",
            "p.principal_id", "p.credential_chain_digest", "p.signing_key_digest", "p.scope_digest",
            "p.authority_epoch", "p.authenticated_at", "p.expires_at",
            "receipt.correction_cut_digest", "receipt.revocation_cut_digest", "receipt.inclusion_policy_digest",
        ):
            with self.subTest(field=marker):
                self.rejects(CODEC, "fn receipt_bytes(", marker)

    def test_post_source_owner_ack_cannot_be_removed_hidden_or_moved_before_readback(self):
        marker = "if self.journal.read(&key)? != bytes"
        for function in ("fn retain<", "fn restore<"):
            self.rejects(OWNER, function, marker)
            self.rejects(OWNER, function, marker, "if false { } " + marker)
            self.rejects(OWNER, function, "return Err(LearningOriginalOwnerErrorV1::CommitUncertain.into())")
        self.rejects(OWNER, "fn restore<", "let before = current_ledger", "return Ok(material); let before = current_ledger")

    def test_codec_retains_all_signature_metadata_and_three_complete_material_blobs(self):
        self.rejects_each(CODEC, "fn encode(", (
            "saved.profile.digest()?", "p.input_width.to_be_bytes()",
            "w.write_count(p.training_episodes.len())?", "row.run_snapshot_digest",
            "row.decision_support_digest", "w.write_count(p.excluded_episodes.len())?",
            "saved.plan.snapshot_id.as_str()", "saved.plan.objective_digest",
            "saved.plan.inclusion_policy_digest", "saved.original_head",
            "e.evidence_id.as_str()", "e.principal_id.as_str()",
            "e.role != LearningEvidenceRoleV1::Evaluator", "w.put(&[2])?",
            "e.trust_digest", "e.scope_digest", "e.objective_digest", "e.authority_epoch",
            "e.issued_at", "e.expires_at", "e.payload_digest", "e.signature",
            "&saved.freeze_payload", "&saved.receipt", "&saved.batch", "w.write_blob(bytes)?",
        ))

    def test_codec_checks_bounds_before_allocation_and_rejects_noncanonical_trailing_bytes(self):
        self.rejects_each(CODEC, "fn decode(", (
            "if bytes.len() > LIMIT", "r.take(MAGIC.len())? != MAGIC",
            "r.take(1)? != [2]", "signature: r.array()?",
            "!r.0.is_empty() || encode(&saved)? != bytes",
        ))
        for occurrence in (0, 1):
            self.rejects(CODEC, "fn decode(", "r.read_count(64)?", occurrence=occurrence)
        self.rejects(CODEC, "fn put(", "bytes.len() > LIMIT - self.0.len()")
        self.rejects(CODEC, "fn take(", "self.0.get(..n).ok_or_else(invalid)?")
        self.rejects(CODEC, "fn read_count(", "if n > limit")
        self.rejects(CODEC, "fn read_blob(", "if n > LIMIT")


if __name__ == "__main__":
    unittest.main()
