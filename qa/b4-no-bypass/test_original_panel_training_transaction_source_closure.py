"""Close the private same-call panel T proof without weakening real tails.

These use the original caller verifier and mutation attacks. They do not claim
native capacity, latency, ordinary NoUpdate or daemon/Root cold qualification.
"""
import hashlib
import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('panel_training_transaction_proof', ROOT / 'scripts/verify_hepta_callers.py')
assert SPEC and SPEC.loader
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
A = 'codex-rs/hepta-agentd/src/'
SOURCE = A + 'neuron_cell_evaluation_qualification_sources.rs'
READ = A + 'neuron_cell_evaluation_qualification_readback.rs'
PANEL = A + 'neuron_cell_evaluation_panel.rs'
MEMBER = A + 'neuron_cell_evaluation_panel_member.rs'
HOST = A + 'neuron_cell_evaluation_host.rs'
FACTORY = A + 'neuron_cell_evaluation_host_training_readback.rs'
TRANSACTION = A + 'neuron_cell_evaluation_training_read_proof.rs'
SERVICE = A + 'neuron_cell_evaluation_host_service.rs'
RECEIPT = A + 'neuron_cell_evaluation_receipt_owner.rs'
MIDDLE = A + 'neuron_cell_evaluation_panel_receipt_read.rs'


class OriginalPanelTrainingTransactionClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / 'CALLERS.toml').read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def code(self, text):
        return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(text))

    def verifies(self, path, text):
        rows = [r for r in self.manifest['protected_file'] if r['path'] == path]
        self.assertTrue(rows)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(text)
            PROOF._verify_protected_files(root, {'protected_file': rows})

    def rejects(self, path, function, marker):
        text = (ROOT / path).read_text()
        self.verifies(path, text)
        code = self.code(text)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        offset = code.index(marker, start, end + 1)
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(path, text[:offset] + text[offset + len(marker):])

    def test_private_proof_edges_have_exact_callers_and_reject_unregistered_calls(self):
        expected = {
            'source': (FACTORY,), 'call': (HOST,), 'readback_call': (HOST,), 'begin': (HOST,),
            'slot': (SOURCE, READ), 'finish': (HOST,), 'actual': (TRANSACTION,),
            'prepare': (MEMBER,), 'qualification': (MEMBER,),
            'panel': (HOST,),
        }
        paths = {TRANSACTION, SOURCE, READ, PANEL, MEMBER, HOST, FACTORY}
        index = {p: self.code((ROOT / p).read_text()) for p in paths}
        for suffix, callers in expected.items():
            identifier = 'learning_original_panel_training_' + suffix
            row = self.boundaries[identifier]
            with self.subTest(boundary=identifier):
                self.assertEqual(row.product_callers, callers)
                self.assertIn(identifier, self.manifest['privileged_inventory']['required_boundary_ids'])
                PROOF._verify_boundary(ROOT, row, index, ())
                extra = dict(index)
                extra[A + 'unregistered_panel_proof.rs'] = 'fn bypass(value: &' + row.receiver_type + ') { ' + row.symbol + '(value); }'
                with self.assertRaisesRegex(PROOF.VerificationFailure, 'unexpected'):
                    PROOF._verify_boundary(ROOT, row, extra, ())

    def test_actual_factory_binds_all_members_before_minting_private_source(self):
        for marker in (
            'original.training != *actual.snapshot()',
            'original.training_evidence != *training.attestation()',
            'original.scope != receipt.scope', 'original.verifier.trust_digest()',
            'original.verifier.scope_digest()', 'original.verifier.objective_digest()',
            'OriginalCellQ24TrainingReadbackConnectionV1::bind_original_training(',
            'panel.primary.trainer = Arc::clone(&trainer)',
            'member.trainer = Arc::clone(&trainer)',
            'OriginalPanelTrainingSourceV1::from_original_training_readback(',
            '.training_source = training_source',
        ):
            with self.subTest(marker=marker):
                self.rejects(FACTORY, 'fn into_host_from_original_training_readback(', marker)
        self.rejects(HOST, 'fn from_original_receipt_owner(', 'training_source: OriginalPanelTrainingSourceV1::Individual')

    def test_first_and_last_reads_stay_in_the_original_physical_slots(self):
        for path, function, markers in (
            (SOURCE, 'fn prepare_with_training(', ['let before = self.read_original(config)?', 'OriginalPanelTrainingReadV1::read(training, self, config).await?', 'let after = self.read_original(config)?', 'binding::authenticate(config, &after, current)?']),
            (READ, 'fn finish_readback_with_training(', ['runner.qualify_and_persist(', 'drop(sink)', 'OriginalPanelTrainingReadV1::read(training, source, &self.config).await?', 'source.verify_current(&self.config, prepared)?', 'if self.completed_bytes()? != bytes', 'binding::authenticate(&self.config, prepared, current)?', 'revalidate_product_qualification_v1(']),
            (TRANSACTION, 'fn read(', ['std::mem::replace(&mut proof.cursor, Cursor::Refused)', 'original.require_source(source.trainer, config)?', 'slot == 0 || slot + 1 == proof.call.slots', 'OriginalCellEvaluationQualificationSourcesV1::read_trainer(source, config)\n                        .await?', 'original.authenticate(binding::now()?)?', 'Cursor::Complete', 'Cursor::Next(slot + 1)']),
        ):
            for marker in markers:
                with self.subTest(path=path, marker=marker): self.rejects(path, function, marker)

    def test_call_identity_counter_and_immutable_signature_cannot_be_substituted(self):
        for function, markers in (
            ('fn call(', ['.checked_mul(8)', 'identity: Arc::new(())', 'admitted: AtomicBool::new(false)']),
            ('fn begin(', ['.compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)', 'call: self', 'cursor: Cursor::Next(0)']),
            ('fn finish(', ['!Arc::ptr_eq(&proof.call.identity, &expected.identity)', 'Arc::ptr_eq(original, expected_source)', '!same_source', '!matches!(proof.cursor, Cursor::Complete)', 'original.authenticate(current)']),
            ('fn require_source(', ['!std::ptr::eq(self.trainer.as_ref(), trainer)', 'self.config.training != config.training', 'self.config.scope != config.scope', 'self.config.training_evidence != config.training_evidence', 'self.config.context.generator != config.context.generator', 'self.config.verifier.trust_digest() != config.verifier.trust_digest()', 'self.config.verifier.scope_digest() != config.verifier.scope_digest()', 'self.config.verifier.objective_digest() != config.verifier.objective_digest()']),
            ('fn authenticate(', ['self.config.verifier.verify(', 'LearningEvidenceRoleV1::Generator', 'learning_iteration_receipt_signing_bytes_v1(binding::training_receipt(&self.config)?)?', 'original.principal() != &self.config.context.generator']),
        ):
            for marker in markers:
                with self.subTest(function=function, marker=marker): self.rejects(TRANSACTION, function, marker)
        for injected in ('impl Clone for OriginalPanelTrainingProofV1 {}', 'struct Escape { source: *const Source }', 'fn leak() { Box::leak(proof); }', 'pub fn arbitrary_proof() {}', 'fn forge() { signer.sign(value); }'):
            with self.subTest(injected=injected), self.assertRaises(PROOF.VerificationFailure):
                self.verifies(TRANSACTION, (ROOT / TRANSACTION).read_text() + '\n' + injected + '\n')

    def test_cohort_cells_qualification_and_receipt_tails_remain_real(self):
        for path, function, markers in (
            (MEMBER, 'fn read_original(', ['let before = self.read_cells()?', 'OriginalCircuitEvaluationCohortReadbackV1::read_current(&mut self.cohort)?', 'OriginalCellEvaluationQualificationSourcesV1::prepare_with_training(', 'OriginalCellEvaluationQualificationOwnerV1::finish_readback_with_training(', 'drop(sources)', 'let after = self.read_cells()?', 'if before != after || cohort_before != cohort_after', 'self.authenticate(&observed, current)?']),
            (PANEL, 'fn read_original_panel(', ['let before = self.read_members(clock, training).await?', 'let after = self.read_members(clock, training).await?', 'if before != after', 'self.require_observed_panel(&after)?', 'self.primary.authenticate(&after[0], current)?', 'owner.authenticate(observed, current)?', 'self.retained = Some(result.clone())']),
            (HOST, 'fn read_original_completion(', ['OriginalPanelTrainingSourceV1::call(', 'OriginalPanelTrainingCallV1::begin(&call)?', 'let before = self.read_panel_with_training(&mut training).await?', 'OriginalCellEvaluationReceiptOwnerV1::attest_original_completion(', 'OriginalCellEvaluationReceiptOwnerV1::readback(', 'let after = self.read_panel_with_training(&mut training).await?', 'OriginalCellEvaluationReceiptOwnerV1::require_original_host_completed(', 'OriginalPanelTrainingReadV1::finish(training, &call, current)?', 'self.authenticate_panel(&after, current)?', 'config.signing.verifier.require_signer_binding(', 'contract::authenticate_receipt(']),
        ):
            for marker in markers:
                with self.subTest(path=path, marker=marker): self.rejects(path, function, marker)

    def test_readonly_member_pins_are_local_ordered_and_execute_keeps_original_path(self):
        for function, markers in (
            ('fn readback_call(', [
                'primary: &Member', 'retention: &[Member]',
                'Self::Bound(_) => {',
                'let mut call = Self::call(self, retention.len() + 1)?',
                'call.receipt = ReceiptMode::BoundReadback', 'return Ok(call)',
                'Self::Individual => {}',
                'Self::ReadbackMembers(_) => return Err(Error::CommitUncertain)',
                'if retention.is_empty()', '.checked_add(1)', '.checked_mul(8)',
                'std::iter::once(primary)', '.chain(retention)',
                'trainer: Arc::clone(&member.trainer)',
                'config: member.qualification.config.clone()',
                'source: Self::ReadbackMembers(Arc::new(members))',
                'identity: Arc::new(())', 'admitted: AtomicBool::new(false)',
            ]),
            ('fn read(', [
                'let width = members.len() * 2',
                'let original = &members[(slot % width) / 2]',
                'let member_slot = (slot / width) * 2 + slot % 2',
                'original.require_member_source(source.trainer, config)?',
                'member_slot == 0 || member_slot == 7', 'if physical',
            ]),
            ('fn require_member_source(', [
                'self.require_source(trainer, config)?',
                'self.config.plan != config.plan',
                'self.config.execution_namespace != config.execution_namespace',
                'self.config.qualification_namespace != config.qualification_namespace',
                'self.config.context.evaluator != config.context.evaluator',
                'self.config.context.retention_receipt_digests',
                'self.config.context.unlearning_receipt_digest',
                'self.config.product_evidence != config.product_evidence',
                'self.config.execution_evidence != config.execution_evidence',
            ]),
            ('fn finish(', [
                'OriginalPanelTrainingSourceV1::ReadbackMembers(expected_source)',
                'for original in members.iter()', 'original.authenticate(current)?',
            ]),
        ):
            for marker in markers:
                with self.subTest(function=function, marker=marker):
                    self.rejects(TRANSACTION, function, marker)
        for marker in (
            'wire::Action::Execute => OriginalPanelTrainingSourceV1::call(',
            'wire::Action::Readback => OriginalPanelTrainingSourceV1::readback_call(',
            '&self.panel.primary', '&self.panel.retention',
        ):
            self.rejects(HOST, 'fn read_original_completion(', marker)

    def test_original_physical_effect_path_and_transport_budgets_remain_guarded(self):
        self.assertEqual(hashlib.sha256((ROOT / RECEIPT).read_bytes()).hexdigest(), 'e43d3fca6615c74343e2478c85237ed2d63133379f1491d8262c949a9941cc6f')
        self.assertEqual(hashlib.sha256((ROOT / SERVICE).read_bytes()).hexdigest(), 'd076b90cf0cfbb8a059681aa590b7a353b1d81df2bf440aa584e71ddb81e3640')
        self.verifies(SERVICE, (ROOT / SERVICE).read_text())
        self.rejects(HOST, 'fn completion(', 'self.fenced = true')
        for function, marker in (
            ('fn prepare(', '&mut OriginalPanelTrainingReadV1::Individual'),
        ): self.rejects(SOURCE, function, marker)
        self.rejects(READ, 'fn finish_readback(', '&mut OriginalPanelTrainingReadV1::Individual')
        self.rejects(PANEL, 'fn read_current_with_clock(', '&mut OriginalPanelTrainingReadV1::Individual')
        self.rejects(HOST, 'fn read_panel_with_training(', 'return self.read_panel().await')


    def test_bound_middle_has_only_original_typed_consumers(self):
        self.assertEqual(re.findall(r'\bfn\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(',
                                    self.code((ROOT / MIDDLE).read_text())),
                         ['receipt_read', 'require_receipt_source', 'authenticate_roles', 'finish'])
        expected = {
            'learning_original_panel_training_receipt_slot': (HOST,),
            'learning_original_panel_receipt_source': (RECEIPT,),
            'learning_original_panel_receipt_roles': (RECEIPT,),
            'learning_original_panel_receipt_finish': (RECEIPT,),
            'learning_original_evaluation_receipt_panel_readback': (HOST,),
            'learning_original_evaluation_receipt_panel_roles': (MIDDLE,),
        }
        index = {p: self.code((ROOT / p).read_text()) for p in (HOST, RECEIPT, MIDDLE)}
        for identifier, callers in expected.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, callers)
                self.assertIn(identifier, self.manifest['privileged_inventory']['required_boundary_ids'])
                PROOF._verify_boundary(ROOT, row, index, ())
                extra = dict(index)
                extra[A + 'unregistered_middle_receipt.rs'] = 'fn bypass(value: &mut ' + row.receiver_type + ') { ' + row.symbol + '(value); }'
                with self.assertRaisesRegex(PROOF.VerificationFailure, 'unexpected'):
                    PROOF._verify_boundary(ROOT, row, extra, ())

    def test_bound_middle_is_single_use_full_source_bound_and_closed_by_real_tails(self):
        for path, function, markers in (
            (MIDDLE, 'fn receipt_read(', [
                'std::mem::replace(&mut proof.cursor, Cursor::Refused)',
                '!matches!(call.receipt, ReceiptMode::BoundReadback)',
                'slot != call.slots / 2', 'proof.receipt_completed',
                'original.require_member_source(trainer, config)?', 'roles_verified: false',
            ]),
            (MIDDLE, 'fn require_receipt_source(', [
                'OriginalCellEvaluationReceiptOwnerV1::original_host_profile(owner)',
                '!matches!(self.proof.cursor, Cursor::Refused)', 'self.proof.receipt_completed',
                '!std::ptr::eq(self.original.trainer.as_ref(), source.trainer)',
                'source.snapshot != &original.training',
                'source.context.generator != original.context.generator',
                'source.context.evaluator != original.context.evaluator',
                'source.context.retention_receipt_digests',
                'source.context.unlearning_receipt_digest',
                'source.evidence != &original.product_evidence',
                '!matches!(&source.timing, ProductTimingEvidenceV1::Qualification)',
                'receipt.training != original.training', 'receipt.scope != original.scope',
                'receipt.plan != original.plan', 'receipt.signing.plan != *original.plan.product_plan()',
                'receipt.signing.execution_namespace != original.execution_namespace',
                'receipt.signing.signer.principal != original.context.evaluator',
                'receipt.signing.verifier.trust_digest() != original.verifier.trust_digest()',
                'receipt.signing.verifier.scope_digest() != original.verifier.scope_digest()',
                'receipt.signing.verifier.objective_digest() != original.verifier.objective_digest()',
            ]),
            (MIDDLE, 'fn authenticate_roles(', [
                'if self.roles_verified', 'self.require_receipt_source(owner, source)?',
                'OriginalCellEvaluationReceiptOwnerV1::authenticate_original_panel_roles(',
                '&self.original.config.training_evidence', 'self.roles_verified = true',
            ]),
            (MIDDLE, 'fn finish(', [
                'if !self.roles_verified', '!matches!(self.proof.cursor, Cursor::Refused)',
                'self.proof.receipt_completed', 'self.slot != self.proof.call.slots / 2',
                '!matches!(self.proof.call.receipt, ReceiptMode::BoundReadback)',
                'self.original.authenticate(current)', 'self.proof.receipt_completed = true',
                'self.proof.cursor = Cursor::Next(self.slot)',
            ]),
            (TRANSACTION, 'fn read(', [
                'matches!(proof.call.receipt, ReceiptMode::BoundReadback)',
                'slot >= proof.call.slots / 2', '!proof.receipt_completed',
            ]),
            (TRANSACTION, 'fn finish(', [
                'matches!(proof.call.receipt, ReceiptMode::BoundReadback)', '!proof.receipt_completed',
            ]),
            (RECEIPT, 'fn readback_with_original_panel_training(', [
                'let prepared = self.prepare(&mut source)?', 'let bytes = self.journal.read(&self.saved)?',
                'self.authenticate_completed(', 'CompletionTraining::Panel(training)',
            ]),
            (RECEIPT, 'fn authenticate_original_panel_roles(', [
                'self.authenticate_roles(source, execution, training)',
            ]),
            (RECEIPT, 'fn authenticate_completed<', [
                'CompletionTraining::Physical =>',
                'OriginalBoundPanelReceiptReadV1::require_receipt_source(&proof, self, source)?',
                'if self.prepare(source)? != prepared',
                'self.authenticate_roles(source, &prepared.1, training)?',
                'OriginalBoundPanelReceiptReadV1::authenticate_roles(\n                    proof,\n                    self,\n                    source,\n                    &prepared.1,\n                )?',
                'if self.journal.read(&self.saved)? != bytes',
                'OriginalBoundPanelReceiptReadV1::finish(proof, now()?)?',
            ]),
        ):
            for marker in markers:
                with self.subTest(path=path, function=function, marker=marker):
                    self.rejects(path, function, marker)
        for injected in ('impl Clone for OriginalBoundPanelReceiptReadV1 {}',
                         'pub fn fake_current() {}', 'fn leak() { Box::leak(proof); }',
                         'fn forge() { signer.sign(bytes); }'):
            with self.subTest(injected=injected), self.assertRaises(PROOF.VerificationFailure):
                self.verifies(MIDDLE, (ROOT / MIDDLE).read_text() + '\n' + injected + '\n')


if __name__ == '__main__':
    unittest.main()
