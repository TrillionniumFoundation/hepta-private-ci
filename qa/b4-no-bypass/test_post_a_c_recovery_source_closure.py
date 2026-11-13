"""Explicit ordinary C recovery keeps original data, receipt and owner cuts.

These deletion/injection controls prove source closure, not native execution or
daemon plus Root cold restart. The latter still requires its actual processes.
"""

from pathlib import Path
import tempfile
import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as component

ROOT, A, PROOF = component.ROOT, component.AGENT, component.PROOF
COLD = A + 'production_post_a_c_recovery.rs'
CONT = A + 'production_post_a_continuation.rs'
GEN = A + 'production_post_a_generation.rs'


class PostACRecoverySourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / 'CALLERS.toml').read_text())

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers

    def test_c_recovery_phase_is_explicit_and_matches_the_same_root_mode(self):
        path = A + 'production_post_a_c_task.rs'
        self.check_markers(path, 'fn open_original(', (
            'matches!(self.mode, OpenMode::Recover) != self.recovery.is_some()',
            'recovery: self.recovery,'))
        self.check_markers(path, 'fn require_original_mode(', (
            'let recovering = matches!(self.mode, OpenMode::Recover)',
            'route.with_original_data(|fixed|', 'Mode::Recover',
            'self.recovery.is_some() != recovering', 'Ok(recovering)'))

    def test_recovery_uses_all_three_original_late_descriptors_and_full_model(self):
        self.check_markers(COLD, 'fn open_original_existing_task(', (
            'OriginalCTaskPlan::require_original_mode(&self, route)?',
            '(&self.source, &fixed.successor.source_configuration)',
            '(&self.target, &fixed.successor.target_configuration)',
            '(&self.ingress, &fixed.successor.signed_ingress)',
            'OriginalLateInput::require_original_pin(',
            'expected.device,', 'expected.inode,', 'expected.uid,', 'expected.gid,', 'expected.mode,',
            '&target_data.generation.manifest != selected',
            'validate_manifest(&decision.bundle, selected)',
            'actual_model(owners, decision, baseline).await?',
            'files::require_original_paths(fixed, &original, &self.execution)?',
            'fixed.inputs.previous.generation.manifest.clone()',
            'custody.require_original()?', 'OriginalPreparedPublicationRoute::require_current(route)?'))

    def test_same_existing_fds_are_locked_and_nonempty_before_witness_open(self):
        for path, function, markers in (
            (COLD, 'fn open_existing_target(', (
                'Mode::Recover', 'files.write(&fixed.inputs.target_journal)?',
                'files.write(&fixed.inputs.target_witness)?', 'journal.try_lock()',
                'witness.try_lock()', 'journal.metadata()?.len() == 0 || witness.metadata()?.len() == 0',
                'FileAnchorWitnessStore::open(', 'witness.current().map_err(refused)?.is_none()')),
            (A + 'production_post_a_q24_owners.rs', 'fn open_witness(', (
                'if matches!(self.mode, OpenMode::Recover)', 'self.journal.try_lock()',
                'self.witness.try_lock()',
                'self.journal.metadata()?.len() == 0 || self.witness.metadata()?.len() == 0',
                'FileAnchorWitnessStore::open(')),
        ):
            self.check_markers(path, function, markers)

    def test_actual_root_intent_and_original_a_precede_completed_c_observation(self):
        self.check_markers(CONT, 'fn run(', (
            'OriginalCellQ24RootPublicationDriverV1::read_original_recovery_intent(',
            '&driver, &receipt,', 'OriginalExistingCTask::into_original_recovery(',
            'Arc::clone(&receipt)', 'OriginalCellQ24RootPublicationDriverV1::recover_feature_from_historical_a(',
            'PublishedCircuitFeatureTaskV1::recover_original_completed_successor(',
            '&recovered, original_a, mode,',
            'OriginalGenerationFiles::into_original_historical_handoff(',
            'OriginalCellQ24LearningStageOwnersV1::install_historical_circuit_feature_generation('))
        self.check_markers(COLD, 'fn into_original_recovery(', (
            'self.custody.require_original()?', 'intent_digest.is_zero()',
            'previous_manifest: self.previous_manifest,', 'original_a,', 'intent_digest,', 'self.mode,'))

    def test_historical_generation_has_no_create_mode_or_missing_to_sign_fallback(self):
        self.check_markers(GEN, 'fn require_original_lifecycle(', (
            'for mode in [self.selection_mode, self.next_use_mode]',
            'matches!(mode, OpenMode::Recover) != recovering', 'return Err('))
        self.check_markers(GEN, 'fn into_original_historical_handoff(', (
            'self.require_original_lifecycle(true)?', 'OriginalHistoricalCircuitFeatureLearningHandoffV1 {',
            'self.selection.into_original_input()?', 'self.next_use.into_original_input()?',
            'verifier: self.verifier,'))
        self.check_markers(GEN, 'fn open_original(', (
            '&authorities.selector,', '&authorities.next_use_observer,',
            'self.selection_mode,', 'self.next_use_mode,'))

    def test_continuation_cannot_rebind_the_actual_source_aggregate_or_identity(self):
        self.check_markers(CONT, 'fn require_original_delivery(', (
            '!Arc::ptr_eq(source, &self.original.source)',
            '!Arc::ptr_eq(owners, &self.original.owners)', 'identity != &self.original.identity',
            'OriginalHistoricalLearningTrustV1::require_original_receipt(',
            'OriginalPreparedPublicationRoute::require_current(&self.original.publication)?',
            'post_a_remaining(self.original.end)?'))
        self.check_markers(CONT, 'fn from_original_inputs(', (
            'OriginalCTaskPlan::require_original_mode(',
            'OriginalGenerationFiles::require_original_lifecycle(&original.generation, recovering)?'))

    def test_delivery_retains_and_joins_both_futures_after_either_error(self):
        path = A + 'learning_iteration_historical_source.rs'
        self.check_markers(path, 'fn with_original_post_a_continuation(', (
            'self.require_identity(identity)?', 'delivery.continuation.is_some()',
            'OriginalPostAContinuationV1::require_original_delivery(',
            'delivery.continuation = Some(continuation)'))
        self.check_markers(path, 'fn run(', (
            'cancellation.child_token()', 'OriginalPostAContinuationV1::run(',
            'tokio::join!(', 'let result = delivery.await', 'delivery_cancelled.cancel()',
            'let result = continuation.await', 'continuation_cancelled.cancel()', 'delivery?'))

    def test_new_c_keeps_real_grant_single_ingress_and_original_end(self):
        self.check_markers(CONT, 'fn run(', (
            'original_end != end', 'OriginalCellQ24RootPublicationDriverV1::prepare_original_successor(',
            'require_continuation(&state, &identity, &cancelled, end)?',
            'OriginalQ24PreparedSuccessorV1::publish_from_original_root(prepared)',
            'OriginalQ24InstalledSuccessorV1::original_installed_successor_ingress(',
            'OriginalCircuitFeatureIngressV1::submit_until(',
            'OriginalGenerationFiles::into_original_handoff(',
            'OriginalCellQ24LearningStageOwnersV1::install_circuit_feature_generation('))

    def test_recovery_and_supervision_reject_replay_repair_or_detached_work(self):
        for path, injected in ((COLD, 'fn bypass() { owner.request_grant(); }'),
                               (COLD, 'fn bypass() { file.set_len(0); }'),
                               (GEN, 'fn bypass() { owner.commit_once(); }'),
                               (CONT, 'fn bypass() { tokio::spawn(work); }')):
            rows = [row for row in self.manifest['protected_file'] if row['path'] == path]
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / path
                target.parent.mkdir(parents=True)
                source = (ROOT / path).read_text()
                target.write_text(source)
                PROOF._verify_protected_files(root, {'protected_file': rows})
                target.write_text(source + '\n' + injected)
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_protected_files(root, {'protected_file': rows})


if __name__ == '__main__':
    unittest.main()
