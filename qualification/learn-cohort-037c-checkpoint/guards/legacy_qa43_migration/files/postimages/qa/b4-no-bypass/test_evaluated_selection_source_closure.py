"""Protect original evaluated S without widening the legacy command or C profile.

This is source closure only. It supplies no ordinary deployment, measurements,
independent operator custody, or daemon/Root cold-recovery qualification.
The opaque S context must preserve Readback; a future C recovery must consume
the same attenuation helper and independently reread its actual predecessors.
"""

import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "evaluated_selection_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
CONTEXT = AGENT + "circuit_evaluated_retention_context.rs"
OWNER = AGENT + "circuit_selection_receipt_owner.rs"
EVALUATED = AGENT + "circuit_evaluated_selection_receipt.rs"
COMMAND = AGENT + "circuit_selection_command.rs"
SERVICE = AGENT + "circuit_selection_command_service.rs"
NEXT_USE = AGENT + "circuit_next_use_receipt_owner.rs"
NEXT_USE_BINDING = AGENT + "circuit_next_use_receipt_binding.rs"
READONLY_HOST = AGENT + "circuit_evaluated_selection_readback_owner.rs"
SUPPORT = AGENT + "circuit_evaluated_retention_publication_support_tests.rs"
NATIVE = AGENT + "circuit_evaluated_retention_receipt_tests.rs"
BOUNDARIES = (
    "learning_original_evaluated_selection_create",
    "learning_original_evaluated_selection_recover",
    "learning_original_evaluated_selection_attest",
    "learning_original_evaluated_selection_readback",
)
CELL_CALLERS = (
    AGENT + "circuit_selection_receipt_owner.rs",
    AGENT + "circuit_model_selection_receipt_sources.rs",
    AGENT + "circuit_learning_read_service.rs",
    AGENT + "circuit_learning_completion_readiness_service.rs",
    AGENT + "circuit_retained_version_c_task.rs",
    EVALUATED,
)


class EvaluatedSelectionClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def verifies(self, path, source):
        rows = [r for r in self.manifest["protected_file"] if r["path"] == path]
        self.assertEqual(len(rows), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})

    def rejects(self, path, function, marker, replacement="", occurrence=0):
        if path == NEXT_USE and function == "fn validate_config(":
            path = NEXT_USE_BINDING
        source = (ROOT / path).read_text()
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        offset = start
        for _ in range(occurrence + 1):
            chosen = source.index(marker, offset, end + 1)
            offset = chosen + len(marker)
        self.verifies(path, source)
        with self.assertRaises(PROOF.VerificationFailure, msg=(path, function, marker)):
            self.verifies(path, source[:chosen] + replacement + source[chosen + len(marker):])

    def test_original_profiles_pass_each_complete_protected_row(self):
        for path in (CONTEXT, OWNER, EVALUATED, NEXT_USE, NEXT_USE_BINDING, COMMAND, SERVICE):
            with self.subTest(path=path):
                self.verifies(path, (ROOT / path).read_text())

    def test_profile_guards_cannot_be_hidden_in_an_uninvoked_closure(self):
        source = (ROOT / CONTEXT).read_text()
        self.verifies(CONTEXT, source)
        for first, following in (
            ("        if matches!(access, PublicationAccess::NewWork) && self.origin != Origin::Fresh",
             "        let snapshot = self.evaluation.snapshot();"),
            ("        if snapshot.receipts.len() != 4", "        let candidate = coordinator"),
            ("        if candidate\n", "        self.verify_original_predecessors(at)?;"),
            ("        if matches!(access, PublicationAccess::NewWork)\n",
             "        Ok(coordinator)"),
        ):
            with self.subTest(check=first.strip()):
                start = source.index(first)
                end = source.index(following, start)
                original = source[start:end].rstrip("\n")
                changed = (source[:start]
                           + "        let _ = || -> Result<(), Error> {\n"
                           + "\n".join("    " + line for line in original.splitlines())
                           + "\n            Ok(())\n        };\n"
                           + source[end:])
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verifies(CONTEXT, changed)

    def test_exact_entrypoints_remain_closed_and_cell_reader_has_one_new_caller(self):
        inventory = self.manifest["privileged_inventory"]["required_boundary_ids"]
        sources = {
            EVALUATED: PROOF._strip_cfg_test_items(
                PROOF._strip_rust_non_code((ROOT / EVALUATED).read_text())
            ),
            READONLY_HOST: PROOF._strip_cfg_test_items(
                PROOF._strip_rust_non_code((ROOT / READONLY_HOST).read_text())
            ),
        }
        for name in BOUNDARIES:
            with self.subTest(boundary=name):
                row = self.boundaries[name]
                self.assertIn(name, inventory)
                self.assertEqual(
                    row.product_callers,
                    (READONLY_HOST,) if name == "learning_original_evaluated_selection_readback" else (),
                )
                self.assertEqual(row.definition_path, EVALUATED)
                self.assertEqual(row.receiver_type, "OriginalCircuitSelectionReceiptOwnerV1")
                PROOF._verify_boundary(ROOT, row, sources, ())
                method = row.symbol.rsplit("::", 1)[1]
                for call in (
                    f"owner.{method}()",
                    f"OriginalCircuitSelectionReceiptOwnerV1::{method}()",
                ):
                    changed = dict(sources)
                    changed[AGENT + "unregistered_evaluated_selector.rs"] = (
                        "fn unexpected(owner: &OriginalCircuitSelectionReceiptOwnerV1) {"
                        + call + "; }"
                    )
                    with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                        PROOF._verify_boundary(ROOT, row, changed, ())
        row = self.boundaries["circuit_feature_original_selection_observation"]
        self.assertEqual(row.product_callers, CELL_CALLERS)
        sources = {
            path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / path).read_text()))
            for path in (row.definition_path, *row.product_callers)
        }
        PROOF._verify_boundary(ROOT, row, sources, ())
        sources[AGENT + "unregistered_evaluated_cell.rs"] = (
            "fn unexpected(cell: &PublishedCircuitCellOwnerV1) { cell.read_learning_selection(); }"
        )
        with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
            PROOF._verify_boundary(ROOT, row, sources, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_recovered_context_and_opaque_selection_never_regain_fresh_authority(self):
        for path, function, marker in (
            (CONTEXT, "fn into_original_receipt_readback(", "mut self"),
            (CONTEXT, "fn into_original_receipt_readback(", "self.origin = Origin::Readback"),
            (CONTEXT, "fn clone_for_original_receipt(", "origin: self.origin"),
            (CONTEXT, "fn require_new_original_receipt(", "self.authenticate(at, PublicationAccess::NewWork)"),
            (EVALUATED, "fn from_evaluated_custody(", "config.context.require_new_original_receipt(current)?"),
            (EVALUATED, "fn from_evaluated_custody(", "CommandOrigin::Recovered => config.context.into_original_receipt_readback()"),
            (EVALUATED, "fn clone(", "context: self.context.clone_for_original_receipt()"),
            (EVALUATED, "fn original_context(", "&self.context"),
            (EVALUATED, "fn completed_evaluated_selection(", "context: context.clone_for_original_receipt()"),
        ):
            self.rejects(path, function, marker)
        self.rejects(CONTEXT, "fn into_original_receipt_readback(", "Origin::Readback", "Origin::Fresh")
        self.rejects(CONTEXT, "fn clone_for_original_receipt(", "origin: self.origin", "origin: Origin::Fresh")
        self.rejects(
            EVALUATED, "fn from_evaluated_custody(",
            "config.context.into_original_receipt_readback()", "config.context",
        )
        self.rejects(EVALUATED, "fn require_new(", ".require_new_original_receipt(current)")
        self.rejects(OWNER, "fn require_new_attestation(", "profile.require_new(current)?")

    def test_recovery_cannot_claim_missing_or_pending_selection_or_create_a_replacement_store(self):
        for function, marker in (
            ("fn create_evaluated(", "CommandOrigin::FreshCreate"),
            ("fn recover_evaluated(", "CommandOrigin::Recovered"),
            ("fn from_evaluated_custody(", "CommandOrigin::FreshCreate => {"),
            ("fn from_evaluated_custody(", "LearningOwnerJournalV1::create(file, witness, saved.binding_digest)?"),
            ("fn from_evaluated_custody(", "CommandOrigin::Recovered => {"),
            ("fn from_evaluated_custody(", "LearningOwnerJournalV1::recover(file, witness, saved.binding_digest)?"),
            ("fn attest_original_evaluated_selection(", "CommandOrigin::Recovered => self.readback_source(source).await?"),
            ("fn readback_evaluated_selection(", "self.readback_source(source).await?"),
        ):
            self.rejects(EVALUATED, function, marker)
        self.rejects(
            EVALUATED, "fn attest_original_evaluated_selection(",
            "CommandOrigin::Recovered => self.readback_source(source).await?",
            "CommandOrigin::Recovered => self.attest_source(source).await?",
        )
        for marker in (
            "ProductEvaluationExecutionStoreErrorV1::Missing", "Err(error) => return Err(error.into())",
            "self.journal.commit_once(&self.saved, ||", "let issued_at = now()?;",
            "require_new_attestation(config, profile, started_at, issued_at)?",
        ):
            self.rejects(OWNER, "fn attest_source(", marker)

    def test_original_t_b_and_actual_cell_capabilities_are_required(self):
        for path, function, marker in (
            (EVALUATED, "fn evaluated_owners(", "Some((self.trainer, self.evaluator))"),
            (EVALUATED, "fn location(", "ObservationLocation::EvaluatedOwner"),
            (EVALUATED, "fn observe(", "LearningIterationCoordinatorV1::from_snapshot(config.decision.clone())?"),
            (EVALUATED, "fn observe(", "self.cell.read_learning_selection(&coordinator)?"),
            (OWNER, "fn prepare(", "matches!(&self.profile, Profile::Evaluated(_)) != source.evaluated_owners().is_some()"),
            (OWNER, "fn training_evidence(", "source.evaluated_owners().ok_or("),
            (OWNER, "fn training_evidence(", ".require_original_receipt_owners(trainer, evaluator)"),
            (CONTEXT, "fn require_original_receipt_owners(", "self.require_current(trainer, evaluator, PublicationAccess::Readback)"),
        ):
            self.rejects(path, function, marker)
        marker = "matches!(&self.profile, Profile::Evaluated(_)) != source.evaluated_owners().is_some()"
        self.rejects(OWNER, "fn prepare(", marker, marker.replace(" != ", " == "))
        for marker in (
            "OriginalCellQ24TrainingCommandClientV1::readback(trainer).await?",
            "if training != self.training",
            "OriginalCellEvaluationCommandClientV1::readback(evaluator).await?",
            "if evaluation != self.evaluation",
        ):
            self.rejects(CONTEXT, "fn require_current(", marker)
        self.rejects(EVALUATED, "fn location(", "ObservationLocation::EvaluatedOwner", "ObservationLocation::RemoteOwner")

    def test_final_cell_check_follows_last_t_b_await_and_precedes_journal_read(self):
        for marker in (
            "ObservationLocation::RemoteOwner | ObservationLocation::EvaluatedOwner",
            "let before = self.training_evidence(&source).await?;",
            "authenticate_training(&self.config, &self.profile, &before, now()?)?;",
        ):
            self.rejects(OWNER, "fn readback_source(", marker)
        for marker in (
            "ObservationLocation::LocalOwner | ObservationLocation::EvaluatedOwner => {",
            "let evidence = self.training_evidence(source).await?;",
            "if self.prepare(source).await? != *observed",
            "if self.journal.read(&self.saved)? != bytes",
        ):
            self.rejects(OWNER, "fn finish_original_readback(", marker)
        self.rejects(
            OWNER, "fn finish_original_readback(",
            "ObservationLocation::LocalOwner | ObservationLocation::EvaluatedOwner => {",
            "ObservationLocation::LocalOwner => {",
        )
        source = (ROOT / OWNER).read_text()
        self.verifies(OWNER, source)
        first = "let evidence = self.training_evidence(source).await?;"
        second = "if self.prepare(source).await? != *observed {\n                    return Err(OwnerError::CommitUncertain.into());\n                }"
        start = source.index("fn finish_original_readback(")
        a = source.index(first, start)
        b = source.index(second, a + len(first))
        changed = (source[:a] + second + source[a + len(first):b]
                   + first + source[b + len(second):])
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(OWNER, changed)

    def test_t_b_and_s_all_keep_original_signatures_independent_roles_and_clocks(self):
        for marker in (
            "receipt.observed_unix_seconds > signature.issued_at", "signature.issued_at > at",
            "&receipt.actor_id != actor", "self.verifier.verify(",
            "&learning_iteration_receipt_signing_bytes_v1(receipt)?",
            "&evidence.principal().principal_id != actor",
            "verify_signed_actor_separation(&verified[0], &verified[1], at)?",
        ):
            self.rejects(CONTEXT, "fn verify_original_predecessors(", marker)
        for marker in (
            "evidence != &config.training_evidence", "context.snapshot() != &config.decision",
            "config.verifier.require_signer_binding(", "LearningEvidenceRoleV1::Selector",
            "context.original_receipt_predecessors(current)?", "for original in &predecessors",
            "verify_independent_roles(original.principal(), &config.signer.principal, current)",
            "original.controller_id() == &config.signer.controller_id",
        ):
            self.rejects(EVALUATED, "fn authenticate_evaluated_training(", marker)
        self.rejects(
            EVALUATED, "fn authenticate_evaluated_training(",
            "original.controller_id() == &config.signer.controller_id",
            "original.controller_id() != &config.signer.controller_id",
        )
        self.rejects(EVALUATED, "fn require_signed_separation(", "context.original_receipt_predecessors(current)?")
        self.rejects(EVALUATED, "fn require_signed_separation(", "verify_signed_actor_separation(&predecessor, signed, current)?")
        self.rejects(OWNER, "fn attest_source(", ".require_signed_separation(&verified, issued_at)")
        self.rejects(OWNER, "fn authenticate_completed(", "self.profile.require_signed_separation(&verified, current)?")

    def test_journal_binding_includes_b_full_signature_and_old_tnu_profile_stays_distinct(self):
        for marker in (
            "self.snapshot().head_digest.as_array()", "self.scope.binding().as_array()",
            "self.verifier.trust_digest().as_array()", "self.verifier.scope_digest().as_array()",
            "self.verifier.objective_digest().as_array()",
            "&self.training.attestation().signing_bytes()", "&self.training.attestation().signature",
            "&self.evaluation.attestation().signing_bytes()", "&self.evaluation.attestation().signature",
        ):
            self.rejects(CONTEXT, "fn receipt_context_binding(", marker)
        for marker in (
            "context.receipt_context_binding().as_array()",
            "&config.signer.verifying_key",
            "&config.maximum_signature_lifetime_seconds.to_be_bytes()",
        ):
            self.rejects(EVALUATED, "fn from_evaluated_custody(", marker)
        for function in ("fn create(", "fn recover("):
            self.rejects(OWNER, function, "profile: Profile::TrainingNoUpdate")
        self.rejects(OWNER, "fn validate_config(", "&Profile::TrainingNoUpdate")
        self.rejects(OWNER, "fn training_receipt(", "LearningIterationObservationV1::TrainingNoUpdateV2(_)")
        self.rejects(OWNER, "fn receipt(", "profile.evidence_domain()")
        source = (ROOT / EVALUATED).read_text()
        for domain in (
            r"hepta.agentd.original-circuit-selection-evidence.v1\0",
            r"hepta.agentd.original-circuit-evaluated-selection-evidence.v1\0",
            r"hepta.agentd.original-circuit-evaluated-selection-receipt.v1\0",
        ):
            self.assertEqual(source.count(domain), 1)
            with self.assertRaises(PROOF.VerificationFailure):
                self.verifies(EVALUATED, source.replace(domain, "rewritten-profile", 1))

    def test_old_command_adapter_still_refuses_the_new_evaluated_four_cut(self):
        for function, marker in (
            ("fn authenticate(", "self.training.receipts.len() != 3"),
            ("fn authenticate(", "LearningIterationObservationV1::TrainingNoUpdateV2(_)"),
            ("fn from_checkpoint(", "context.authenticate(now()?)?"),
        ):
            self.rejects(COMMAND, function, marker)
        self.rejects(
            COMMAND, "fn authenticate(", "self.training.receipts.len() != 3",
            "self.training.receipts.len() == 3",
        )
        self.rejects(SERVICE, "fn from_original_receipt_owner(", "OriginalCircuitSelectionCommandContextV1::from_checkpoint(")

    def test_legacy_c_refuses_evaluated_five_cut_before_touching_original_journal(self):
        for marker in (
            "if config.selection.receipts.len() == 5",
            "&& coordinator.candidate().is_some()", ".get(3)",
            "disposition: LearningEvaluationDispositionV1::NoUpdate",
            "Some(LearningIterationObservationV1::Selection { .. })",
            'OwnerError::Binding("evaluated retention requires original T/B/S readbacks")',
        ):
            self.rejects(NEXT_USE, "fn validate_config(", marker)
        for before, after in (
            ("receipts.len() == 5", "receipts.len() != 5"),
            ("receipts.len() == 5", "receipts.len() == 4"),
            ("coordinator.candidate().is_some()", "coordinator.candidate().is_none()"),
            ("&& coordinator.candidate().is_some()", "|| coordinator.candidate().is_some()"),
            ("LearningEvaluationDispositionV1::NoUpdate", "LearningEvaluationDispositionV1::Qualified"),
        ):
            self.rejects(NEXT_USE, "fn validate_config(", before, after)
        for occurrence in (0, 1):
            self.rejects(NEXT_USE, "fn validate_config(", "&& matches!(", "|| matches!(", occurrence)
        for function in ("fn create(", "fn recover("):
            self.rejects(NEXT_USE, function, "validate_config(&config, &key)?")

    def test_opaque_receipt_has_no_additional_public_capability_or_mutable_owner_getter(self):
        source = (ROOT / EVALUATED).read_text()
        self.verifies(EVALUATED, source)
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        self.assertEqual(sorted(re.findall(r"\bpub\s+(?:async\s+)?fn\s+(\w+)", code)), sorted((
            "snapshot", "receipt", "attestation", "create_evaluated", "recover_evaluated",
            "attest_original_evaluated_selection", "readback_evaluated_selection",
            "into_evaluated_readback_owner", "into_evaluated_command_owner",
        )))
        for marker in (
            "pub fn from_snapshot(", "SigningKey::generate(", "LearningEvidenceVerifierV1::new(",
            "RootResidentLearningEffectGateV3", "pub fn original_context(",
        ):
            with self.assertRaises(PROOF.VerificationFailure):
                self.verifies(EVALUATED, source + "\n" + marker + "\n")
        original = "pub struct OriginalCircuitEvaluatedSelectionReceiptV1 {\n    context:"
        self.assertEqual(source.count(original), 1)
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(EVALUATED, source.replace(original, original.replace("    context:", "    pub context:")))

    def test_original_fixture_tests_are_mounted_and_public_exports_stay_linux_only(self):
        mount = '#[path = "circuit_evaluated_retention_receipt_tests.rs"]\nmod receipt_tests;'
        support = (ROOT / SUPPORT).read_text()
        self.assertEqual(support.count(mount), 1)
        native = (ROOT / NATIVE).read_text()
        self.assertIn("context: f.context()?", native)
        self.assertIn("require_new_original_receipt", native)
        source = (ROOT / AGENT / "lib.rs").read_text()
        for name in (
            "OriginalCircuitEvaluatedSelectionReceiptConfigV1",
            "OriginalCircuitEvaluatedSelectionReceiptSourcesV1",
            "OriginalCircuitEvaluatedSelectionReceiptV1",
        ):
            export = f'#[cfg(target_os = "linux")]\npub use circuit_selection_receipt_owner::{name};'
            self.assertEqual(source.count(export), 1)


if __name__ == "__main__":
    unittest.main()
