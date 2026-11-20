"""Exact owner/effect scope mutation controls; no native Root-fault claim."""

from pathlib import Path
import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as reference

ROOT = reference.ROOT
PROOF = reference.PROOF
AGENT = reference.AGENT


class OriginalHistoricalOperationScopesSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / 'CALLERS.toml').read_text())

    reject_removal = reference.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = reference.HistoricalLedgerReadonlySourceTests.check_markers

    def body(self, path, function):
        text = (ROOT / AGENT / path).read_text()
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(text))
        self.assertEqual(code.count(function), 1)
        start = code.index(function)
        return code[start:PROOF._rust_item_end(code, start) + 1]

    def test_successor_proof_binds_actual_aggregate_and_full_decision(self):
        self.check_markers(AGENT + 'cell_q24_publication_successor.rs',
                           'fn require_original_publication_owners(', (
            '!std::ptr::eq(owners, self.context.owners().as_ref())', 'decision != &self.decision'))
        self.check_markers(AGENT + 'cell_q24_publication_successor.rs',
                           'fn require_current_bindings(', (
            'current.require_original_root_successor(', 'self.context.session()',
            'self.context.initial()', 'self.context.scope()',
            'current.require_original_root_selection(&self.decision, &self.operation, self.selection)'))

    def test_successor_effect_starts_only_after_same_lane_purpose_check(self):
        path = AGENT + 'cell_q24_publication_material.rs'
        for occurrence in (0, 1):
            self.reject_removal(path, 'fn with_original_root_publication<T>(',
                                '.require_original_successor_operation(read)', occurrence)
            self.reject_removal(path, 'fn with_original_root_publication<T>(',
                                'operation.read_publication_material(&snapshot)? != manifest', occurrence)
        self.check_markers(path, 'fn with_original_root_publication<T>(', (
            'inner.cancelled.load(Ordering::Acquire)', 'effect_started.store(true, Ordering::Release)',
            'let value = work()', 'operation.finish_original_b_read()?',
            'started.load(Ordering::Acquire)', 'OriginalCellQ24PublicationErrorV1::CommitUncertain'))

    def test_retained_scope_keeps_its_original_checks(self):
        self.check_markers(AGENT + 'cell_q24_publication_material.rs',
                           'fn with_original_successor_publication<T>(', (
            'successor.require_original_publication_owners(self, &snapshot)?',
            '!successor.has_original_historical_source()', '!self.inner.has_original_root_evaluation()?',
            'successor.require_current_successor_publication().await?',
            '.with_original_publication(snapshot, manifest, work)', 'prepared_uncertain',
            'return result', 'adopts != changed || adopts != manifest.is_some()'))
        self.check_markers(AGENT + 'circuit_q24_successor_worker.rs', 'fn prepare_original_worker(', (
            'if !self.context.has_original_historical_source()',
            'self.context.require_current_successor_context().await?'))

    def test_actual_channel_open_stays_inside_live_source_effect(self):
        path = AGENT + 'circuit_q24_successor_worker.rs'
        self.check_markers(path, 'fn finish_original_worker(', (
            'tokio::time::timeout(', 'OriginalSuccessorGrant::Provided(signed)',
            '.with_current_successor_publication(move || {',
            'execution.open_original_successor_channel(', 'Ok(opened?)'))
        for occurrence in (0, 1):
            self.reject_removal(path, 'fn finish_original_worker(',
                                'slot.require_installation_open()', occurrence)
        path = AGENT + 'cell_q24_publication_successor.rs'
        for occurrence in (0, 1):
            self.reject_removal(path, 'fn with_current_successor_publication<T>(',
                                'proof.require_current_bindings()?', occurrence)
        self.check_markers(path, 'fn with_current_successor_publication<T>(', (
            'effect_started.store(true, Ordering::Release)', 'let value = work()',
            'started.load(Ordering::Acquire)', 'Error::CommitUncertain'))

    def test_original_connect_and_independent_selection_are_within_real_operation(self):
        self.check_markers(AGENT + 'cell_q24_publication_root_stage.rs', 'fn connect_current_until(', (
            '.with_original_publication(snapshot, manifest, move || {',
            'runtime.block_on(crate::RootGenerationPublicationHandoffV1::connect_until(',
            'current.require_original_root_selection('))
        self.check_markers(AGENT + 'cell_q24_publication_root_stage.rs',
                           'fn accept_original_result_selection(', (
            'decision.require_root_publication()?', 'decision.adopts()', 'manifest: None',
            '.with_original_publication(snapshot, None, move || {',
            'original.load_selected(&authorities, input, None)?'))
        self.check_markers(AGENT + 'production_post_a_artifacts.rs', 'fn publish_and_select_original(', (
            '(None, Some((owners, snapshot, authority.clone())), None)',
            'self.selection.wait_original_value(cancelled).await?',
            'selection.require_unchanged()?',
            'OriginalCellQ24RetainedArtifactForRootV1::accept_original_result_selection('))

    def test_c_receipt_open_install_postread_precede_outer_notification(self):
        self.check_markers(AGENT + 'cell_q24_learning_generation_operation.rs',
                           'fn install_original_feature_generation_in_operation(', (
            'self.inner.require_snapshot(&snapshot)?', '.in_original_prepared_lane(',
            'owners.root_evaluation.is_none() || owners.generation.is_some()', 'original.open(',
            'OriginalGenerationLearningRoleV1::Selection', 'OriginalGenerationLearningRoleV1::NextUse',
            '.block_on(selection.observe_original_selection(&snapshot))',
            'operation.authenticate_receipt(&snapshot, receipt)?', 'operation.finish_original_b_read()?'))
        self.assertNotIn('notify_original_successor_generation',
                         self.body('cell_q24_learning_generation_operation.rs',
                                   'fn install_original_feature_generation_in_operation('))
        self.check_markers(AGENT + 'cell_q24_learning_stage_owners.rs',
                           'fn install_original_feature_generation(', (
            'self.install_original_feature_generation_in_operation(snapshot.clone(), original)',
            '.await?', 'self.notify_original_successor_generation(&snapshot)'))

    def test_file_admission_finishes_physical_operation_before_witness_phase(self):
        path = AGENT + 'production_post_a_q24.rs'
        self.check_markers(path, 'fn assemble_original_post_a_q24(', (
            'OriginalPreparedReadV1::original_stage_authorities(',
            'owners::StageFilesData::prepare_original_inputs_in_operation(',
            'Ok((generation, artifacts, task, delivery, inputs))',
            '.assemble_original_historical_q24_learning(config, inputs, Arc::clone(&receipt))'))
        # The first double-result propagation must occur between original file
        # admission and the separate constructor which obtains a fresh read.
        self.reject_removal(path, 'fn assemble_original_post_a_q24(', '.map_err(refused)??;', 0)
        body = self.body('production_post_a_q24_owners.rs', 'fn prepare_original_inputs_in_operation(')
        self.assertNotIn('open_witness', body)
        self.assertNotIn('.await', body)
        for occurrence in (0, 1):
            self.reject_removal(AGENT + 'production_post_a_q24_owners.rs',
                                'fn prepare_original_inputs_in_operation(',
                                'OriginalPreparedReadV1::require_prepared(read, &prepared)', occurrence)

    def test_witnesses_and_all_owners_use_fresh_exact_receipt_scope(self):
        path = AGENT + 'config_root_learning.rs'
        for occurrence in (0, 1):
            self.reject_removal(path, 'fn with_original_historical_q24_learning_owners(',
                                '.require_historical_source_in_operation(&receipt, read)', occurrence)
        self.check_markers(path, 'fn with_original_historical_q24_learning_owners(', (
            'prepared.with_original_prepared_operation(|read|',
            'inputs.require_prepared_q24_in_operation(&prepared, read)?',
            'OriginalHistoricalStageInputs::open_in_original_operation(',
            'prepared.initial().owners.evidence_trust_digest != original.verifier.trust_digest()',
            '!(1..=64).contains(&original.queue_capacity)',
            'OriginalCellQ24LearningStageOwnersV1::from_original_owners_in_operation(',
            'inputs.into_q24_learning_runtime_in_operation('))
        for occurrence in (0, 1):
            self.reject_removal(AGENT + 'cell_q24_learning_stage_owners.rs',
                                'fn from_original_owners_in_operation(',
                                '.block_on(factory.require_current())', occurrence)

    def test_root_scope_comparison_keeps_prepared_helper_private(self):
        self.check_markers(AGENT + 'root_production_learning_inputs.rs',
                           'fn require_prepared_q24_in_operation(', (
            'OriginalPreparedReadV1::require_prepared(read, prepared)',
            '&self.initial != prepared.initial() || scope != prepared.scope()'))
        text = (ROOT / AGENT / 'cell_q24_prepared_learning.rs').read_text()
        for visibility in ('pub ', 'pub(crate) ', 'pub(super) '):
            self.assertNotIn(visibility + 'fn require_initial_in_operation(', text)

    def test_claim_is_real_one_shot_and_has_no_borrowed_root_authority(self):
        path = AGENT + 'learning_owner_journal_historical_delivery.rs'
        self.check_markers(path, 'fn prepare_original_historical_delivery(', (
            'self.require_current()?', 'self.journal.claim(key)',
            'ProductEvaluationExecutionStateV1::Pending', 'return Err(Error::Pending)',
            'self.anchor_append(before)?', 'owner: self', 'key: key.clone()'))
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / path).read_text()))
        self.assertNotIn('OriginalPreparedReadV1', code)
        self.assertNotIn('OriginalHistoricalOperationV1', code)
        self.assertNotIn('impl Clone', code)
        self.check_markers(AGENT + 'learning_iteration_historical_source.rs', 'fn run_delivery(', (
            'handle.reserve()', 'self.journal.read(&self.key)',
            '.prepare_original_historical_delivery(&self.key)',
            'Ok((reservation, existing, claim))', '.map_err(refused)??;',
            'OriginalHistoricalDeliveryPreparationV1::Claimed(claim)',
            'OriginalHistoricalDeliveryPreparationV1::Completed(_)',
            'timeout_at(source.end.into(), reservation.submit(source.request().clone()))'))

    def test_exact_completion_and_physical_postread_precede_terminal_accept(self):
        self.check_markers(AGENT + 'learning_owner_journal_historical_delivery.rs',
                           'fn complete_original_historical_delivery(', (
            'owner.require_current()?', 'owner.journal.complete(&self.key, bytes).is_err()',
            'owner.anchor_append(before)?', 'owner.read(&self.key)?', 'saved != bytes'))
        path = AGENT + 'learning_iteration_historical_source.rs'
        self.check_markers(path, 'fn run_delivery(', (
            '.complete_original_historical_delivery(result.head_digest.as_array())?',
            'Ok::<_, JournalError>(result)', '.accept_original_terminal(&snapshot, &state)'))
        for occurrence in (0, 1):
            self.reject_removal(path, 'fn run_delivery(',
                                'source.require_original_stage_operation(state.identity(), read)?', occurrence)
            self.reject_removal(path, 'fn run_delivery(',
                                '.require_original_stage_operation(state.identity(), read)', occurrence + 2)
        # Both result layers are propagated after the completion closure. If
        # physical Root after rejects, actual Completed remains and no Accept
        # executes. This is source proof, not a native injected Root failure.
        body = self.body('learning_iteration_historical_source.rs', 'fn run_delivery(')
        completion = body.index('Ok::<_, JournalError>(result)')
        terminal = body.index('.accept_original_terminal(&snapshot, &state)')
        self.assertLess(completion, terminal)
        self.assertEqual(body[completion:terminal].count('.map_err(refused)?'), 2)
        self.assertNotIn('prepare_original_historical_delivery', body[completion:terminal])

    def test_old_pending_and_completed_paths_never_gain_new_dispatch(self):
        path = AGENT + 'learning_iteration_historical_source.rs'
        for occurrence in (0, 1):
            self.reject_removal(path, 'fn run_delivery(',
                                'self.readback(reservation, &cancellation).await?', occurrence)
        self.check_markers(path, 'fn run_delivery(', (
            'saved.as_slice() != snapshot.head_digest.as_array()',
            'OriginalHistoricalDeliveryPreparationV1::Completed(_)', 'refused(JournalError::Pending)'))
        rows = {row['id']: row for row in self.manifest['boundary']}
        self.assertEqual(rows['q24_historical_delivery_async_claim']['product_callers'], [])
        self.assertEqual(rows['post_a_original_stage_files']['product_callers'], [])
        self.assertEqual(rows['post_a_original_stage_authorities']['product_callers'], [])

    def test_new_effect_boundaries_reject_unlisted_actual_product_caller(self):
        identifiers = (
            'q24_original_successor_publication_scope', 'q24_original_successor_owner_binding',
            'q24_original_successor_purpose_operation', 'q24_original_successor_channel_operation',
            'q24_original_feature_generation_install', 'q24_original_feature_generation_operation',
            'q24_original_feature_generation_open', 'q24_original_retained_result_selection',
            'q24_original_role_selection_operation', 'q24_original_dataset_roles_operation',
            'q24_original_prepared_roles_operation', 'q24_original_historical_stage_files',
            'q24_original_historical_stage_witnesses', 'q24_original_historical_config_assembly',
            'q24_original_historical_launch_assembly', 'q24_original_historical_owner_assembly',
            'q24_original_historical_owner_initialization', 'q24_original_historical_root_scope',
            'q24_original_historical_runtime_assembly', 'q24_original_delivery_claim_operation',
            'q24_original_delivery_complete_operation',
        )
        rows = {row.identifier: row for row in PROOF._boundary_rows(self.manifest)}
        ignored = PROOF._string_tuple(self.manifest, 'ignored_path_fragments')
        index = {path.relative_to(ROOT).as_posix():
                 PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(path.read_text()))
                 for path in PROOF._source_files(ROOT, PROOF._string_tuple(self.manifest, 'source_roots'))}
        target = AGENT + 'cell_q24_task_observation_control.rs'
        self.assertIn(target, index)
        original = index[target]
        fields = {}
        for identifier in identifiers:
            with self.subTest(boundary=identifier):
                boundary = rows[identifier]
                self.assertIn(identifier, self.manifest['privileged_inventory']['required_boundary_ids'])
                PROOF._verify_boundary(ROOT, boundary, index, ignored, fields_by_receiver_type=fields)
                spellings = [('associated', boundary.symbol + '();')]
                if identifier == 'q24_original_delivery_complete_operation':
                    method = 'complete_original_historical_delivery'
                    # These are lexical source mutants, not executed programs
                    # or claims of a native Root post-read fault. The opaque
                    # claim remains private; no type is exported for this scan.
                    spellings.extend([
                        ('instance', 'claim.' + method + '(&[]);'),
                        ('bracketed-alias', '<PrivateClaim>::' + method + '(claim, &[]);'),
                        ('bracketed-generic', "<OriginalHistoricalDeliveryClaimV1<'_, FileAnchorWitnessStore>>::" + method + '(claim, &[]);'),
                    ])
                for spelling, call in spellings:
                    with self.subTest(spelling=spelling):
                        index[target] = original + '\nfn unowned_effect_probe() { let _ = ' + call + ' }\n'
                        try:
                            with self.assertRaises(PROOF.VerificationFailure) as raised:
                                PROOF._verify_boundary(ROOT, boundary, index, ignored, fields_by_receiver_type=fields)
                            self.assertIn(target, str(raised.exception))
                        finally:
                            index[target] = original


if __name__ == '__main__':
    unittest.main()
