"""Completed facts retain original Root time without restoring an owner."""

from dataclasses import replace
from pathlib import Path
import tempfile
import tomllib
import unittest

import test_historical_task_read_source_closure as route


ROOT = Path(__file__).resolve().parents[2]
A = "codex-rs/hepta-agentd/src/"
PROOF = route.PROOF
BOUNDARIES = (
    "root_completed_refusal_fresh", "root_completed_refusal_accept",
    "root_completed_refusal_read", "root_completed_record_accept",
    "root_completed_record_read", "root_completed_files_open",
    "root_completed_files_empty", "root_completed_files_read",
    "root_completed_journal_open", "root_completed_journal_read",
    "root_completed_freeze_pair", "root_completed_checkpoint_read",
    "root_completed_signature_verify", "root_completed_current_signer",
    "root_completed_freeze_signer", "root_completed_original_task_data",
    "root_completed_b_fact", "root_completed_b_read", "root_completed_b_observe",
    "root_completed_b_files", "root_completed_b_protocol",
)


class CompletedLearningAcceptanceSourceClosure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def reject(self, name, before, after=""):
        path = A + name + ".rs"
        source = (ROOT / path).read_text()
        self.assertIn(before, source)
        rules = {"protected_file": [
            row for row in self.manifest["protected_file"] if row["path"] == path
        ]}
        self.assertTrue(rules["protected_file"])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, rules)
            target.write_text(source.replace(before, after, 1))
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, rules)

    def test_first_fact_follows_all_root_and_physical_postchecks(self):
        for marker in (
            "RootCompletedLearningRefusalV1::accept_registered(original, ||",
            "let (accepted, value) = action()?;",
            "accepted.require_original(initial, target)?;",
            "HostAuthorityFrontierStore::initialize(root, owner.clone(), accepted.clone())",
            "store.load(&owner).map_err(io::Error::other)? != accepted",
        ):
            with self.subTest(marker=marker):
                self.reject("authority_host_completed_record", marker)

    def test_cold_missing_fact_cannot_initialize_or_skip_postchecks(self):
        self.reject("authority_host_completed_record",
                    "RootCompletedLearningRefusalV1::read_original(")
        self.reject("authority_host_completed_record",
                    "OriginalControlRecord::open(root_path, &owner)?")
        self.reject("authority_host_completed_record", "let value = action(&accepted);",
                    "let value = action(&accepted)?; return Ok((accepted.data_digest()?, value));")
        self.reject("authority_host_completed_checkpoint", "let value = action(&checkpoint, digest);",
                    "let value = action(&checkpoint, digest)?; return Ok(value);")
        self.reject("authority_host_completed_checkpoint", "OriginalControlRecord::open(&path, OWNER)?")

    def test_all_original_signatures_and_full_physical_cuts_are_required(self):
        for marker in (
            "let local_decision_records = usize::from(context.terminal().local_decision_v2().is_some());",
            "let expected_signatures = 6 + local_decision_records;",
            "3 => 2,",
            "4 => local_decision_records,",
            "_ => 1,",
            "journal.records.len() != expected_records",
            "fact.journals != cuts || fact.independent_b != independent_b.acceptance.to_string()",
            "context.require_current_freeze_signer(&freeze)?;",
            "saved == payload",
            "let [(digest, signed)] = matches.as_slice()",
            "context.require_current_signer(&signed)?;",
            "signatures.len() != expected_signatures\n        || context.terminal().training_no_update_v2().is_some()",
            "vec![independent_b.plan_attestation]",
            "let hashes = match context.terminal().local_decision_v2()",
            "Some(_) => CompletedSignatureDigests::Seven(",
            "None => CompletedSignatureDigests::Six(",
            "fact.signatures != hashes",
            "OriginalReceiptVerificationV1::verify(&request, signed, at)",
            "verify_signed_actor_separation(prior, &current, at)",
        ):
            with self.subTest(marker=marker):
                self.reject("authority_host_completed_signatures", marker)

    def test_signature_data_is_bounded_and_preserves_all_original_digest_checks(self):
        for before, after in (
            ("#[serde(untagged)]", ""),
            ("Six([String; 6])", "Six(Vec<String>)"),
            ("Seven([String; 7])", "Seven([String; 8])"),
            ("Seven([String; 7]),", "Seven([String; 7]), Extra([String; 9]),"),
            ("pub(super) signatures: CompletedSignatureDigests", "pub(super) signatures: Vec<String>"),
            ("pub(super) journals: [String; 7]", "pub(super) journals: [String; 6]"),
            ("Self::Six(digests) => digests", "Self::Six(_) => &[]"),
            ("Self::Seven(digests) => digests", "Self::Seven(_) => &[]"),
            (".chain(self.journals.iter())", ""),
            (".chain(self.signatures.as_slice().iter())", ""),
        ):
            with self.subTest(before=before, after=after):
                self.reject("authority_host_completed_record", before, after)

    def test_terminal_shape_cannot_be_guessed_from_a_fixed_or_unbounded_count(self):
        for before, after in (
            ("usize::from(context.terminal().local_decision_v2().is_some())", "1"),
            ("6 + local_decision_records", "7"),
            ("4 => local_decision_records", "4 => 1"),
            ("journal.records.len() != expected_records", "journal.records.len() > expected_records"),
            ("signatures.len() != expected_signatures", "signatures.len() > expected_signatures"),
            ("Some(_) => CompletedSignatureDigests::Seven(", "Some(_) => CompletedSignatureDigests::Six("),
            ("None => CompletedSignatureDigests::Six(", "None => CompletedSignatureDigests::Seven("),
        ):
            with self.subTest(before=before, after=after):
                self.reject("authority_host_completed_signatures", before, after)

    def test_observer_preserves_canonical_refusal_namespace_and_actual_signature_shape(self):
        for before in (
            "completed_learning_refusal_owner(initial.head_digest, target)?",
            "scope_digest(target.scope())?",
            "!initial.is_zero()",
            "scope.as_array()",
            "initial.as_array()",
            "receipt.observation.stage() != LearningIterationStageV1::Proposal",
            "expected_signatures == 6 + usize::from(terminal.local_decision_v2().is_some())",
            "values.len() == expected",
        ):
            with self.subTest(before=before):
                self.reject("ordinary_q24_cold_acceptance_data_tests", before)
        self.reject("ordinary_q24_cold_acceptance_data_tests",
                    '[("journals", 7), ("signatures", expected_signatures)]',
                    '[("journals", 6), ("signatures", 7)]')

    def test_fresh_time_is_sampled_now_and_cold_time_is_only_the_first_fact(self):
        for before, after in (
            ("Some(fact) => fact.root_verified_at_seconds", "Some(_) => 1"),
            ("None => context.current_unix_seconds()?", "None => 1"),
            ("let now = context.current_unix_seconds()?;", "let now = at;"),
            ("verify_at(now)?;", ""),
        ):
            with self.subTest(before=before):
                self.reject("authority_host_completed_signatures", before, after)
        self.reject("authority_host_completed_learning",
                    "signed.principal_id.as_str() != self.trust.freeze_evaluator.principal_id", "false")

    def test_original_seven_descriptors_and_separate_b_plan_remain(self):
        for name in ("freeze", "experience", "dataset", "training_receipt",
                     "local_decision", "selection", "next_use"):
            with self.subTest(name=name):
                self.reject("authority_host_completed_files", "data." + name + ",")
        self.reject("authority_host_completed_files", "file.aliases(previous)", "false")
        self.reject("authority_host_completed_files", "let result = with_rest(rest, end, observations, action);",
                    "return with_rest(rest, end, observations, action);")
        self.reject("authority_host_completed_journal", "self.maximum_records != maximum_records", "false")

    def test_b_history_cannot_restore_native_or_ignore_a_swallowed_failure(self):
        for marker in (
            "OriginalBEnrollment::completed_history_fact(enrollment, scope)?",
            "OriginalBInputs::open_completed_readonly(path)?",
            "let value = action(&read);",
            "read.used.get() && !read.refused.get()",
            "!observed || enrollment != &original || input_images(&files)? != original_inputs",
            "context.require_original_publication_context(self.service, self.end)?",
            "context.initial() != self.initial || context.frozen_scope() != self.scope",
            "Digest32::of_bytes(&bytes) != signature_digest",
            "self.enrollment.realized_training_head != Some(evaluation.predecessor.into_array())",
            "enrollment.cell_images.as_ref() != Some(&cells) || enrollment.output_images != outputs",
        ):
            with self.subTest(marker=marker):
                self.reject("authority_host_q24_evaluation_history", marker)
        self.reject("authority_host_q24_evaluation_deployment",
                    "Self::open_with_access(path, OriginalBFileAccess::ReadOnly)",
                    "Self::open_with_access(path, OriginalBFileAccess::OwnerWriter)")
        self.reject("authority_host_q24_evaluation_deployment",
                    ".activate(context.initial(), context.current_unix_seconds()?)?", ".activate(context.initial(), accepted_at)?")

    def test_actual_closed_calls_and_unregistered_calls_are_checked(self):
        rows = [row for row in PROOF._boundary_rows(self.manifest) if row.identifier in BOUNDARIES]
        self.assertEqual(len(rows), len(BOUNDARIES))
        paths = {row.definition_path for row in rows} | {p for row in rows for p in row.product_callers}
        index = {p: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / p).read_text())) for p in paths}
        for row in rows:
            with self.subTest(boundary=row.identifier):
                self.assertIn(row.identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, index, ())
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_boundary(ROOT, replace(row, product_callers=()), index, ())
                forged = dict(index)
                forged[A + "unregistered_completed_owner.rs"] = "fn bypass() { " + row.symbol + "(); }"
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_boundary(ROOT, row, forged, ())


if __name__ == "__main__":
    unittest.main()
