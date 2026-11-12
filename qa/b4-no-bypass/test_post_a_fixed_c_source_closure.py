"""Fresh C uses only the eight original files fixed by the same Root route."""
import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as component

ROOT, A = component.ROOT, component.AGENT
PLAN, FILES = A + 'production_post_a_c_task.rs', A + 'production_post_a_c_files.rs'


class PostAFixedCSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / 'CALLERS.toml').read_text())

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers

    def test_late_source_target_and_ingress_are_the_fixed_root_descriptors(self):
        self.check_markers(PLAN, 'fn open_original_new_task(', (
            '!matches!(self.mode, OpenMode::Create)', 'route.with_original_data(|fixed|',
            '(&self.source, &fixed.successor.source_configuration)',
            '(&self.target, &fixed.successor.target_configuration)',
            '(&self.ingress, &fixed.successor.signed_ingress)',
            'OriginalLateInput::require_original_pin(', '&expected.path,',
            'expected.device,', 'expected.inode,', 'expected.uid,', 'expected.gid,', 'expected.mode,'))
        self.check_markers(A + 'production_post_a_late_input.rs', 'fn require_original_pin(', (
            'Self::require_original(self)?', 'self.path != path || self.identity != expected',
            'Self::require_original(self)'))

    def test_all_execution_paths_and_resource_bounds_match_original_root_data(self):
        self.check_markers(FILES, 'fn require_original_paths(', (
            'source.source_journal != original.source_journal.path',
            'source.source_witness != original.source_witness.path',
            'data.cell_journal != original.cell_journal.path',
            'data.cell_witness != original.cell_witness.path',
            'data.inference_control != original.inference_control.path',
            'data.cell_witness_scope != original.cell_witness_scope',
            'data.cell_witness_objective != original.cell_witness_objective',
            'data.cell_witness_generation != original.cell_witness_generation',
            'data.cell_witness_records != original.cell_witness_records',
            'data.maximum_cell_records != original.maximum_cell_records',
            'data.inference_capacity != original.inference_capacity',
            'data.worker_generation != original.worker_generation'))

    def test_exact_kernel_identities_precede_any_new_witness_or_control_owner(self):
        self.check_markers(FILES, 'fn open_original_new_files(', (
            'require_original_paths(prepared, source, data)?', '!matches!(fixed.mode, Mode::Reserve)',
            '(&source_journal, &prepared.successor.source_journal)',
            '(&source_witness, &prepared.successor.source_witness)',
            '(&cell_journal, &prepared.successor.cell_journal)',
            '(&cell_witness, &prepared.successor.cell_witness)',
            '(&inference_file, &prepared.successor.inference_control)',
            'physical.dev()', 'physical.ino()', 'physical.uid()', 'physical.gid()', 'physical.mode()',
            'expected.device,', 'expected.inode,', 'expected.uid,', 'expected.gid,', 'expected.mode,',
            'physical.nlink() != 1', 'new.metadata()?.len() != 0',
            'previous_witness.current().map_err(refused)?.is_none()',
            'next_witness.current().map_err(refused)?.is_some()',
            'source_witness.current().map_err(refused)?.is_some()',
            'cell_witness.current().map_err(refused)?.is_some()'))

    def test_model_is_the_actual_original_training_outcome_or_same_baseline(self):
        self.check_markers(PLAN, 'fn actual_model(', (
            'if !decision.adopts()', 'baseline.components() != &decision.bundle.components',
            'LearningIterationCoordinatorV1::from_snapshot(owners.prepared().initial().clone())',
            '.record(receipt.clone(), receipt.observed_unix_seconds)',
            '.read_original_training_material(training.snapshot())',
            'material.into_completion().outcome', 'candidate.bundle == decision.bundle',
            'Ok(Arc::new(candidate.model))'))

    def test_source_clock_full_manifest_and_historical_a_remain_required(self):
        self.check_markers(PLAN, 'fn open_original_new_task(', (
            'OriginalSingleQ24SourceConfigurationV1::from_original_deployment_bytes(',
            '&target_data.generation.manifest != selected', 'validate_manifest(&decision.bundle, selected)',
            'PublishedCircuitFeatureCompletionV1::read_original_historical_completion(',
            'custody.require_original()?'))
        for occurrence in (0, 1):
            self.reject_removal(PLAN, 'fn open_original_new_task(',
                                'require_source_deadline(&original.source)?', occurrence)
        self.reject_removal(FILES, 'fn open_original_new_files(',
                            'clock: Arc::new(super::super::super::initial_q24::clock::sample)')


if __name__ == '__main__':
    unittest.main()
