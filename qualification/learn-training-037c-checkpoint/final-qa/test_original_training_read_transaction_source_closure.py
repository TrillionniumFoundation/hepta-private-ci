"""Keep Source readonly batching inside its original lane and actual I/O.

These mutate the concrete guarded reads. They do not claim native capacity,
ordinary NoUpdate, or recovery qualification; those need the real tests.
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
    'original_training_read_transaction_proof', ROOT / 'scripts/verify_hepta_callers.py'
)
assert SPEC and SPEC.loader
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = 'codex-rs/hepta-agentd/src/'
SOURCE = AGENT + 'cell_q24_training_source.rs'
OWNER = AGENT + 'cell_q24_training_source_owner.rs'
STAGE = AGENT + 'cell_q24_training_stage.rs'
MODEL = AGENT + 'cell_q24_training_model_lane.rs'
READ = AGENT + 'cell_q24_training_source_read.rs'
OWNER_READ = AGENT + 'cell_q24_training_source_owner_read.rs'
LANE = AGENT + 'cell_q24_training_source_read_lane.rs'


class OriginalTrainingReadTransactionClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / 'CALLERS.toml').read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def code(self, source):
        return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))

    def verifies(self, path, source):
        rows = [row for row in self.manifest['protected_file'] if row['path'] == path]
        self.assertTrue(rows)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {'protected_file': rows})
            # Preserve the unmodified verifier's generic-marker restriction;
            # check these exact private generic bodies in this source gate.
            code = self.code(source)
            for row in rows:
                for sequence in row.get('required_order', []):
                    marker = sequence[0]
                    if not re.fullmatch(r'fn [A-Za-z_]\w*<', marker):
                        continue
                    if code.count(marker) != 1:
                        raise PROOF.VerificationFailure('unique original generic function required')
                    start = code.index(marker)
                    end = PROOF._rust_item_end(code, start)
                    if end is None:
                        raise PROOF.VerificationFailure('complete original generic function required')
                    body = code[start:end + 1]
                    if re.search(r'\bfn\s+(?:r#)?\w+', body[len(marker):]):
                        raise PROOF.VerificationFailure('nested functions cannot supply original readonly guards')
                    PROOF._verify_required_order({'required_order': [sequence]}, body, path + ':' + marker)

    def rejects(self, path, function, marker):
        source = (ROOT / path).read_text()
        code = self.code(source)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        offset = code.index(marker, start, end + 1)
        self.verifies(path, source)
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(path, source[:offset] + source[offset + len(marker):])

    def test_only_closed_original_read_edges_can_construct_or_consume_proofs(self):
        expected = {**{'learning_original_training_read_source_' + name: (OWNER_READ,)
                       for name in ('begin', 'finish', 'authenticate')},
                    **{'learning_original_training_read_owner_' + name: (LANE,)
                       for name in ('begin', 'finish', 'authenticate')},
                    'learning_original_training_read_completion_lane': (STAGE,),
                    'learning_original_training_read_candidate_lane': (MODEL,),
                    'learning_original_candidate_material_native': (LANE,),
                    'learning_source_bound_training_admission': (AGENT + 'cell_q24_source_bound_stage.rs', LANE),
                    'cell_q24_original_training_pair_binding': (STAGE, MODEL, LANE)}
        paths = {path for identifier in expected for path in (
            self.boundaries[identifier].definition_path, *self.boundaries[identifier].product_callers)}
        index = {path: self.code((ROOT / path).read_text()) for path in paths}
        for identifier, callers in expected.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, callers)
                self.assertIn(identifier, self.manifest['privileged_inventory']['required_boundary_ids'])
                PROOF._verify_boundary(ROOT, row, index, ())
                extra = dict(index)
                extra[AGENT + 'unregistered_read_transaction.rs'] = (
                    'fn bypass(owner: &' + row.receiver_type + ') { ' + row.symbol + '(owner); }')
                with self.assertRaisesRegex(PROOF.VerificationFailure, 'unexpected'):
                    PROOF._verify_boundary(ROOT, row, extra, ())

    def test_each_transaction_has_actual_before_and_after_full_source_reads(self):
        for function, marker in (
            ('fn begin_readonly_in_lane<', 'verify_original_evidence(&self.config, started_at)?'),
            ('fn begin_readonly_in_lane<', 'self.live.read_original_evidence(&self.config).await?'),
            ('fn begin_readonly_in_lane<', 'self.live\n                .original\n                .read_current_material(&self.config, &self.live.baseline)\n                .await'),
            ('fn begin_readonly_in_lane<', 'require_same_material(&self.material, &before)?'),
            ('fn begin_readonly_in_lane<', 'capture_binding(&self.config, &before) != self.binding'),
            ('fn finish_readonly_in_lane<', 'self.live.read_original_evidence(&self.config).await?'),
            ('fn finish_readonly_in_lane<', 'self.live\n                .original\n                .read_current_material(&self.config, &self.live.baseline)\n                .await'),
            ('fn finish_readonly_in_lane<', 'require_same_material(&before.before, &after)?'),
            ('fn finish_readonly_in_lane<', 'require_same_material(&self.material, &after)?'),
            ('fn finish_readonly_in_lane<', 'capture_binding(&self.config, &after) != self.binding'),
            ('fn finish_readonly_in_lane<', 'verify_original_evidence(&self.config, current)?'),
            ('fn authenticate_readonly_tail(', 'current < after.started_at'),
            ('fn authenticate_readonly_tail(', 'verify_original_evidence(&self.config, current)'),
        ):
            with self.subTest(function=function, marker=marker):
                self.rejects(READ, function, marker)

    def test_proof_keeps_original_allocation_and_permit_without_export_or_clone(self):
        self.rejects(SOURCE, 'fn capture_live_original_source(', 'read_identity: Arc::new(())')
        for function, marker in (
            ('fn begin_readonly_in_lane<', 'Arc::clone(&self.read_identity)'),
            ('fn finish_readonly_in_lane<', '!Arc::ptr_eq(&self.read_identity, &before.original)'),
            ('fn finish_readonly_in_lane<', 'original: before.original'),
            ('fn finish_readonly_in_lane<', '_lane: before.lane'),
            ('fn authenticate_readonly_tail(', '!Arc::ptr_eq(&self.read_identity, &after.original)'),
        ):
            with self.subTest(function=function, marker=marker):
                self.rejects(READ, function, marker)
        for injected in ('impl Clone for OriginalSourceReadV1 {}', 'struct Escape { original: *const Source }',
                         'fn leak() { Box::leak(value); }', 'pub fn arbitrary_proof() {}'):
            with self.subTest(injected=injected):
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verifies(READ, (ROOT / READ).read_text() + '\n' + injected + '\n')

    def test_read_work_remains_inside_held_lane_and_original_physical_tail(self):
        for function, marker in (
            ('fn read_original_source_completion(', 'Arc::clone(&self.lane)\n            .try_acquire_owned()'),
            ('fn read_original_source_completion(', 'tokio::task::spawn_blocking(move ||'),
            ('fn read_original_source_completion(', 'owners.try_lock()'),
            ('fn read_original_source_candidate(', 'Arc::clone(&self.lane)\n            .try_acquire_owned()'),
            ('fn read_original_source_candidate(', 'self.owners.try_lock()'),
            ('fn read_original_source_candidate(', 'SourceRequirement::Required'),
            ('fn read_source_transaction<', 'CellQ24TrainingOwnerV1::begin_original_source_read(&mut self.training, permit)?'),
            ('fn read_source_transaction<', 'CellQ24TrainingOwnerV1::finish_original_source_read(&mut self.training, before)'),
            ('fn read_source_transaction<', 'let current = match &result'),
            ('fn read_source_transaction<', 'self.require_captured_tail_current()'),
            ('fn read_source_transaction<', 'CellQ24TrainingOwnerV1::authenticate_original_source_read(&mut self.training, after)'),
            ('fn read_source_transaction<', 'self.require_retained_attestation_current(&current)'),
            ('fn read_source_transaction<', 'CellQ24TrainingOwnerV1::require_original_source_capture(\n                        &mut self.training,\n                    )'),
        ):
            with self.subTest(function=function, marker=marker):
                self.rejects(LANE, function, marker)
        for injected in ('fn bypass() { trainer.fit_or_readback(); }',
                         'fn bypass() { receipts.attest_original_completion(); }',
                         'pub(super) fn read_source_transaction() {}',
                         'fn restore() { self.source_fenced = false; }'):
            with self.subTest(injected=injected):
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verifies(LANE, (ROOT / LANE).read_text() + '\n' + injected + '\n')

    def test_failures_keep_original_native_and_source_fences(self):
        for function in ('fn begin_original_source_read<', 'fn finish_original_source_read<',
                         'fn authenticate_original_source_read('):
            with self.subTest(function=function):
                self.rejects(OWNER_READ, function, 'if self.fenced')
                self.rejects(OWNER_READ, function, 'self.fenced = true')
        self.rejects(MODEL, 'fn read_candidate_material(', 'OriginalCellQ24TrainingStageV1::read_original_source_candidate(self)')
        self.rejects(STAGE, 'fn readback(', 'OriginalCellQ24TrainingStageV1::read_original_source_completion(self).await')


if __name__ == '__main__':
    unittest.main()
