"""Close the private same-call panel T proof without weakening real tails.

These use the original caller verifier and mutation attacks. They do not claim
native capacity, latency, ordinary NoUpdate or daemon/Root cold qualification.
"""
import hashlib
import importlib.util
from pathlib import Path
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
            'source': (FACTORY,), 'call': (HOST,), 'begin': (HOST,),
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
            (TRANSACTION, 'fn read(', ['std::mem::replace(&mut proof.cursor, Cursor::Refused)', 'original.require_source(source.trainer, config)?', 'if slot == 0 || slot + 1 == proof.call.slots', 'OriginalCellEvaluationQualificationSourcesV1::read_trainer(source, config)\n                        .await?', 'original.authenticate(binding::now()?)?', 'Cursor::Complete', 'Cursor::Next(slot + 1)']),
        ):
            for marker in markers:
                with self.subTest(path=path, marker=marker): self.rejects(path, function, marker)

    def test_call_identity_counter_and_immutable_signature_cannot_be_substituted(self):
        for function, markers in (
            ('fn call(', ['.checked_mul(8)', 'identity: Arc::new(())', 'admitted: AtomicBool::new(false)']),
            ('fn begin(', ['.compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)', 'call: self', 'cursor: Cursor::Next(0)']),
            ('fn finish(', ['!Arc::ptr_eq(&proof.call.identity, &expected.identity)', '!Arc::ptr_eq(original, expected_source)', '!matches!(proof.cursor, Cursor::Complete)', 'original.authenticate(current)']),
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

    def test_original_effect_owner_and_transport_budgets_are_unchanged(self):
        self.assertEqual(hashlib.sha256((ROOT / RECEIPT).read_bytes()).hexdigest(), 'b69a53d8048deba5ef0f36bdb92f0d85362ff5e783ba9301ee74e6f35d5be4c7')
        self.assertEqual(hashlib.sha256((ROOT / SERVICE).read_bytes()).hexdigest(), '806f44f2e3da47d09a307893b1daca5c0fa5c24217b6a5bb3a62adeb1a575c29')
        self.verifies(SERVICE, (ROOT / SERVICE).read_text())
        self.rejects(HOST, 'fn completion(', 'self.fenced = true')
        for function, marker in (
            ('fn prepare(', '&mut OriginalPanelTrainingReadV1::Individual'),
        ): self.rejects(SOURCE, function, marker)
        self.rejects(READ, 'fn finish_readback(', '&mut OriginalPanelTrainingReadV1::Individual')
        self.rejects(PANEL, 'fn read_current_with_clock(', '&mut OriginalPanelTrainingReadV1::Individual')
        self.rejects(HOST, 'fn read_panel_with_training(', 'return self.read_panel().await')


if __name__ == '__main__':
    unittest.main()
