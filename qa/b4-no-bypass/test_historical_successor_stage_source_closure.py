"""Mutation controls for real same-slot stage admission, not native Root proof."""

from dataclasses import replace
from pathlib import Path
import tempfile
import tomllib
import unittest

import test_historical_q24_stage_source_closure as original

ROOT = original.ROOT
PROOF = original.PROOF
AGENT = original.AGENT
CONTEXT = original.CONTEXT
RUNTIME = original.RUNTIME
STAGE = original.LANE
READY = AGENT + 'circuit_q24_successor_ready.rs'
OLD_WAIT = AGENT + 'learning_iteration_successor.rs'


class HistoricalSuccessorStageSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / 'CALLERS.toml').read_text())

    rejects = original.HistoricalQ24StageSourceClosureTests.rejects

    def markers(self, path, function, markers):
        for marker in markers:
            with self.subTest(path=path, marker=marker):
                self.rejects(path, function, marker)

    def body(self, path, function):
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / path).read_text()))
        self.assertEqual(code.count(function), 1)
        start = code.index(function)
        return code[start:PROOF._rust_item_end(code, start) + 1]

    def test_pending_wait_keeps_original_admission_scope_and_real_await(self):
        self.markers(RUNTIME, 'fn wait_original_historical_successor_stage(', (
            'let Some(slot) = &self.successor',
            '!super::historical_context::original_stage_needs_successor(snapshot, stage)',
            'stage == LearningIterationStageV1::NextUse',
            'slot.original_generation_ready_hint()',
            'self.require_stage_admission(state)?',
            'slot.wait_original_generation(snapshot).await',
        ))
        for occurrence in (0, 1):
            self.rejects(RUNTIME, 'fn wait_original_historical_successor_stage(',
                         'self.require_frozen_scope(&snapshot.request)?', occurrence)
        self.markers(RUNTIME, 'fn process_original_historical(', (
            'self.wait_original_historical_successor_stage(&state, &current.snapshot, stage)',
            'OriginalHistoricalWorkV1::Stage',
        ))

    def test_original_recovery_and_generic_wait_stay_separate(self):
        self.markers(RUNTIME, 'fn process_original_historical(', (
            'current.generation_prefix.take()',
            'self.wait_original_successor_stage(&state, &prefix, next)',
            'OriginalHistoricalWorkV1::ConfirmRecovery(current.snapshot)',
        ))
        body = self.body(OLD_WAIT, 'fn wait_original_successor_stage(')
        self.assertEqual(body.count('self.require_stage_admission(state)?'), 2)
        self.assertIn('slot.wait_original_generation(snapshot).await?', body)
        self.assertNotIn('original_generation_ready_hint', body)

    def test_context_uses_exact_registered_slot_and_original_scope(self):
        self.markers(CONTEXT, 'fn from_original_bootstrap(', (
            'successor: bootstrap.successor.as_ref().map(Arc::clone)',
        ))
        self.markers(CONTEXT, 'fn require_successor_stage_in_operation(', (
            'match (&self.successor, registered)',
            '(Some(slot), Some(registered)) => (slot, registered)',
            'self.require_in_operation(read, OriginalHistoricalStageAdmissionV1::NewWork)?',
            '.upgrade()', '!Arc::ptr_eq(slot, &registered)',
            'snapshot.request != prepared.initial().request',
            'snapshot.owners != prepared.initial().owners',
            '.validate_request(&snapshot.request, &snapshot.owners)?',
            'slot.require_original_generation_ready(snapshot)',
        ))
        self.assertNotIn('dyn LearningIterationOwnerPortsV1', (ROOT / CONTEXT).read_text())

    def test_same_slot_is_rechecked_on_both_sides_of_actual_stage(self):
        for occurrence in (0, 1):
            self.rejects(STAGE, 'fn run_original_historical_stage(',
                         'context.require_successor_stage_in_operation(', occurrence)
            self.rejects(STAGE, 'fn run_original_historical_stage(',
                         'inner.successor.get()', occurrence)
        self.markers(STAGE, 'fn run_original_historical_stage(', (
            'OriginalQ24StageOperationV1::run(&mut operation, work)',
            'if result.is_ok()', 'fence.armed = false',
        ))
        body = self.body(STAGE, 'fn run_original_historical_stage(')
        before, after = body.split('OriginalQ24StageOperationV1::run(&mut operation, work)', 1)
        self.assertIn('context.require_successor_stage_in_operation(', before)
        self.assertIn('context.require_successor_stage_in_operation(', after)

    def test_ready_guard_keeps_actual_owner_prefix_and_close_on_error(self):
        self.markers(READY, 'fn require_original_generation_ready(', (
            'CloseOnDrop::new(self)', 'state.decision.as_ref()',
            'snapshot.request != original.request', 'snapshot.owners != original.owners',
            '!snapshot.receipts.starts_with(&original.receipts)',
            'state.phase != Phase::Ready', '!state.generation',
            'state.installed.is_none()', 'self.closed.is_cancelled()',
            'close.disarm()',
        ))
        for occurrence in (0, 1):
            self.rejects(READY, 'fn require_original_generation_ready(',
                         'self.require_open()', occurrence)
            self.rejects(READY, 'fn require_original_generation_ready(',
                         'remaining(snapshot.request.envelope.expiry_unix_seconds)?', occurrence)

    def test_hint_is_only_synchronous_scheduling_and_never_source_authority(self):
        self.markers(READY, 'fn original_generation_ready_hint(', (
            'self.closed.is_cancelled()', 'return false', 'self.state.lock()',
            'state.phase == Phase::Ready', 'state.generation', 'state.installed.is_some()',
        ))
        for path, function in ((READY, 'fn original_generation_ready_hint('),
                               (READY, 'fn require_original_generation_ready('),
                               (CONTEXT, 'fn require_successor_stage_in_operation(')):
            body = self.body(path, function)
            self.assertNotIn('.await', body)
            self.assertNotIn('block_on', body)
            if path == READY:
                self.assertNotRegex(body, r'\bstate\.(phase|generation|installed|decision)\s*=(?!=)')
        self.markers(CONTEXT, 'fn original_stage_needs_successor(', (
            'stage == LearningIterationStageV1::NextUse',
            '|| (stage == LearningIterationStageV1::Selection',
            '&& !snapshot.receipts.last().is_some_and(',
            'receipt.observation.stage() == LearningIterationStageV1::Proposal',
        ))

    def test_successor_field_cannot_become_mutable_external_input(self):
        source = (ROOT / CONTEXT).read_text()
        marker = '    successor: Option<Arc<crate::circuit_q24_successor::SuccessorSlot>>,'
        self.assertEqual(source.count(marker), 1)
        rows = [r for r in self.manifest['protected_file'] if r['path'] == CONTEXT]
        for visibility in ('pub ', 'pub(crate) ', 'pub(super) '):
            with self.subTest(visibility=visibility), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                path = root / CONTEXT
                path.parent.mkdir(parents=True)
                path.write_text(source)
                PROOF._verify_protected_files(root, {'protected_file': rows})
                path.write_text(source.replace(marker, marker.replace('successor:', visibility + 'successor:')))
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_protected_files(root, {'protected_file': rows})

    def test_new_methods_reject_unregistered_instance_and_associated_callers(self):
        expected = {
            'historical_successor_wait_before_real_stage': (),
            'historical_successor_stage_classification': (RUNTIME, STAGE),
            'historical_successor_current_stage_admission': (STAGE,),
            'historical_successor_ready_schedule_hint': (RUNTIME,),
            'historical_successor_exact_ready_observation': (CONTEXT,),
        }
        boundaries = {r.identifier: r for r in PROOF._boundary_rows(self.manifest)}
        paths = {CONTEXT, RUNTIME, STAGE, READY}
        index = {name: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / name).read_text()))
                 for name in paths}
        target = AGENT + 'cell_q24_task_observation_control.rs'
        original_target = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / target).read_text()))
        index[target] = original_target
        for identifier, callers in expected.items():
            row = boundaries[identifier]
            self.assertEqual(row.product_callers, callers)
            self.assertIn(identifier, self.manifest['privileged_inventory']['required_boundary_ids'])
            PROOF._verify_boundary(ROOT, row, index, ())
            if callers:
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_boundary(ROOT, replace(row, product_callers=()), index, ())
            method = row.symbol.rsplit('::', 1)[-1]
            for call in ('owner.' + method + '();', row.symbol + '();', '<ActualAlias>::' + method + '();'):
                with self.subTest(boundary=identifier, spelling=call):
                    index[target] = original_target + '\nfn unregistered_stage_probe() { ' + call + ' }\n'
                    try:
                        with self.assertRaises(PROOF.VerificationFailure) as raised:
                            PROOF._verify_boundary(ROOT, row, index, ())
                        self.assertIn(target, str(raised.exception))
                    finally:
                        index[target] = original_target


if __name__ == '__main__':
    unittest.main()
