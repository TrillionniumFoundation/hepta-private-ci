"""Strong-control equal-information paired-score comparisons (synthetic fixtures only)."""
import copy
import unittest
from hashlib import sha256

from paired_superiority import ARMS, COST_PARTS, EvidenceGap, cvar90, evaluate


H = lambda x: sha256(x.encode()).hexdigest()


def study_fixture(*, strong_ndu=True, bootstrap_replicates=120):
    seeds = [101, 211, 307]
    ids = {str(s): [f'heldout-{s}-{i}' for i in range(32)] for s in seeds}
    p = {
        'seeds': seeds, 'heldout_world_ids': ids,
        'heldout_source_group_ids': {str(s): [f'src-{s}-{i//2}' for i in range(32)]
                                     for s in seeds},
        'calibration_world_ids': [f'calibration-{i}' for i in range(100)],
        'calibration_source_group_ids': [f'calibration-src-{i}' for i in range(100)],
        'training_world_ids': [f'training-{i}' for i in range(128)],
        'training_source_group_ids': [f'training-src-{i//2}' for i in range(128)],
        'validation_world_ids': [f'validation-{i}' for i in range(32)],
        'validation_source_group_ids': [f'validation-src-{i//2}' for i in range(32)],
        'arms': list(ARMS), 'validation_selected_best': 'free_controller',
        'selection_lock_digest': H('frozen-validation-selection'),
        'model_digest': H('shared-encoder-flow'),
        'decoder_digest': H('same-raw-decoder'),
        'objective_digest': H('independent-external-objective'),
        'actuator_digest': H('same-cell-actuators'),
        'minimum_cvar_improvement': 0.02,
        'max_quality_drop': 0.02, 'max_ambiguity_increase': 0.,
        'max_inconsistency_increase': 0., 'max_total_cost_ratio': 1.05,
        'bootstrap_replicates': bootstrap_replicates,
        'bootstrap_seed': 3001, 'familywise_alpha': 0.05,
        'draws_per_world': 2, 'failure_loss': 2.0, 'cost_units': 'measured_cpu_seconds',
        'hard_world_cost_limit': 2.0,
    }
    worlds = []
    for seed in seeds:
        for idx, wid in enumerate(ids[str(seed)]):
            identity = H(wid + ' publicly visible')
            arms = {}
            for name in ARMS:
                rank = list(ARMS).index(name)
                # Deliberately synthetic examples to test the acceptance gate,
                # not the real Hepta training or inference model.
                good = (name == 'ndu' and strong_ndu)
                loss = (0.1 if good else .42 + .003 * rank) + .02 * (idx % 4)
                quality = 0.92 if good else 0.83
                ambiguity = .01 if good else .06
                inconsistency = .01 if good else .04
                parts = {part: 0.0 for part in COST_PARTS}
                parts['encoder'] = .3
                parts['backbone'] = .35
                parts['decoder'] = .15
                parts['verifier'] = .2
                if good:
                    parts['cell'] = .015
                    parts['controller'] = .015
                parts['training_amortized'] = .01
                arms[name] = {
                    'public_input_digest': identity,
                    **{key: p[key] for key in ('model_digest', 'decoder_digest',
                                               'objective_digest', 'actuator_digest')},
                    'decoded_draw_scores': [
                        {'loss': loss, 'quality': quality,
                         'ambiguity': ambiguity, 'inconsistency': inconsistency,
                         'status': 'completed',
                         'output_witness_sha256': H(f'{wid}-{name}-draw-{k}')}
                        for k in range(2)],
                    'measured_cost': {**parts, 'total': sum(parts.values())},
                }
            worlds.append({'seed': seed, 'world_id': wid,
                           'source_group_id': f'src-{seed}-{idx//2}',
                           'public_input_digest': identity,
                           'protected_task': idx % 4 == 0,
                           'outcomes': arms})
    return {'schema': 'hepta-mgp-paired-v1', 'protocol': p, 'worlds': worlds}


class PairedEvidenceTests(unittest.TestCase):
    def test_missing_training_source_manifest_rejected(self):
        d = study_fixture()
        del d['protocol']['training_source_group_ids']
        with self.assertRaisesRegex(EvidenceGap, 'training frozen world/source manifest'):
            evaluate(d)

    def test_missing_validation_selection_source_manifest_rejected(self):
        d = study_fixture()
        del d['protocol']['validation_world_ids']
        with self.assertRaisesRegex(EvidenceGap, 'validation frozen world/source manifest'):
            evaluate(d)

    def test_training_source_aliases_heldout_despite_distinct_world_id(self):
        d = study_fixture()
        d['protocol']['training_source_group_ids'][0] = 'src-101-0'
        with self.assertRaisesRegex(EvidenceGap, 'original-source leakage'):
            evaluate(d)

    def test_validation_source_aliases_heldout_despite_distinct_world_id(self):
        d = study_fixture()
        d['protocol']['validation_source_group_ids'][0] = 'src-307-0'
        with self.assertRaisesRegex(EvidenceGap, 'original-source leakage'):
            evaluate(d)

    def test_training_world_id_reuses_heldout_identifier(self):
        d = study_fixture()
        d['protocol']['training_world_ids'][0] = d['worlds'][0]['world_id']
        with self.assertRaisesRegex(EvidenceGap, 'cross-split world leakage'):
            evaluate(d)

    def test_training_calibration_sources_overlap(self):
        d = study_fixture()
        d['protocol']['training_source_group_ids'][0] = 'calibration-src-9'
        with self.assertRaisesRegex(EvidenceGap, 'original-source leakage'):
            evaluate(d)

    def test_validation_training_sources_overlap(self):
        d = study_fixture()
        d['protocol']['validation_source_group_ids'][1] = 'training-src-13'
        with self.assertRaisesRegex(EvidenceGap, 'original-source leakage'):
            evaluate(d)

    def test_missing_training_id_rejects_even_if_sources_present(self):
        d = study_fixture()
        d['protocol']['training_world_ids'][0] = ''
        with self.assertRaisesRegex(EvidenceGap, 'training frozen world/source manifest'):
            evaluate(d)

    def test_group_resampling_is_locked_and_visible(self):
        rec = evaluate(study_fixture())
        self.assertEqual(rec['independent_source_groups_per_seed'], [16, 16, 16])

    def test_single_source_repeated_views_cannot_count_as_32_worlds(self):
        d = study_fixture()
        seed = d['protocol']['seeds'][0]
        d['protocol']['heldout_source_group_ids'][str(seed)] = [f'src-{seed}-same'] * 32
        for row in d['worlds'][:32]:
            row['source_group_id'] = f'src-{seed}-same'
        with self.assertRaisesRegex(EvidenceGap, 'balanced independent source groups'):
            evaluate(d)

    def test_relabelled_source_group_rejected(self):
        d = study_fixture()
        d['worlds'][0]['source_group_id'] = 'fake-independent-source'
        with self.assertRaisesRegex(EvidenceGap, 'source-group identity'):
            evaluate(d)

    def test_calibration_source_overlap_rejected(self):
        d = study_fixture()
        d['protocol']['calibration_source_group_ids'].append('src-101-0')
        with self.assertRaisesRegex(EvidenceGap, 'source-group leakage'):
            evaluate(d)

    def test_unbalanced_source_groups_rejected(self):
        d = study_fixture()
        d['protocol']['heldout_source_group_ids']['101'][0] = 'src-101-1'
        d['worlds'][0]['source_group_id'] = 'src-101-1'
        with self.assertRaisesRegex(EvidenceGap, 'balanced independent source groups'):
            evaluate(d)

    def test_missing_absolute_cost_cap_is_rejected(self):
        d = study_fixture()
        del d['protocol']['hard_world_cost_limit']
        with self.assertRaisesRegex(EvidenceGap, 'absolute world cost limit'):
            evaluate(d)

    def test_relative_equal_cost_cannot_override_absolute_hard_budget(self):
        d = study_fixture(bootstrap_replicates=120)
        # Every controller is ~21s: NDU remains cheaper than the ratio limit,
        # but none is within the same registered 2s physical ceiling.
        for row in d['worlds']:
            for outcome in row['outcomes'].values():
                outcome['measured_cost']['backbone'] += 20
                outcome['measured_cost']['total'] += 20
        with self.assertRaisesRegex(EvidenceGap, 'overbudget episode must receive failure penalty'):
            evaluate(d)

    def test_valid_overrun_is_penalized_retained_and_never_qualified(self):
        d = study_fixture(bootstrap_replicates=120)
        outcome = d['worlds'][0]['outcomes']['ndu']
        outcome['measured_cost']['controller'] += 2
        outcome['measured_cost']['total'] += 2
        for score in outcome['decoded_draw_scores']:
            score.update(status='failed', loss=2.0, quality=0.0,
                         ambiguity=1.0, inconsistency=1.0)
        receipt = evaluate(d)
        self.assertEqual(receipt['worlds_per_seed'], 32)
        self.assertEqual(receipt['overbudget_episodes_by_arm']['ndu'], 1)
        self.assertEqual(receipt['registered_hard_world_cost_limit'], 2)
        self.assertEqual(receipt['status'], 'HOLD_NO_GO')
        for comparator in receipt['comparison'].values():
            self.assertFalse(comparator['gates']['absolute_world_cost_budget'])
        self.assertFalse(receipt['all_provisional_gates_pass'])

    def test_all_arms_under_hard_budget_eligible_for_budget_subgate(self):
        receipt = evaluate(study_fixture())
        self.assertTrue(all(x['gates']['absolute_world_cost_budget']
                            for x in receipt['comparison'].values()))
        self.assertEqual(sum(receipt['overbudget_episodes_by_arm'].values()), 0)

    def test_small_absolute_budget_has_no_dangerous_epsilon_floor(self):
        d = study_fixture()
        d['protocol']['hard_world_cost_limit'] = 1.035e-7
        # All physical costs scale to ~1e-7. NDU costs ~1.04e-7:
        # a 1e-9 absolute epsilon would mask this overrun.
        for row in d['worlds']:
            for outcome in row['outcomes'].values():
                for key in outcome['measured_cost']:
                    outcome['measured_cost'][key] *= 1e-7
        with self.assertRaisesRegex(EvidenceGap, 'overbudget episode must receive failure penalty'):
            evaluate(d)

    def test_nonpositive_absolute_cap_is_rejected(self):
        d = study_fixture()
        d['protocol']['hard_world_cost_limit'] = 0.0
        with self.assertRaisesRegex(EvidenceGap, 'absolute world cost limit'):
            evaluate(d)

    def test_cost_uncertainty_fails_even_when_mean_ratio_looks_safe(self):
        d = study_fixture(bootstrap_replicates=1000)
        for row in d['worlds'][:2]:
            cost = row['outcomes']['ndu']['measured_cost']
            cost['controller'] += 0.52
            cost['total'] += 0.52
        comparison = evaluate(d)['comparison']['free_controller']
        self.assertLess(comparison['observed_cost_ratio'], 1.05)
        self.assertGreater(comparison['cost_noninferiority_margin_upper'], 0)
        self.assertFalse(comparison['gates']['physical_total_cost'])

    def test_calibration_source_manifest_cannot_repeat_ids(self):
        d = study_fixture()
        d['protocol']['calibration_source_group_ids'].append('calibration-src-0')
        with self.assertRaisesRegex(EvidenceGap, 'source-group leakage'):
            evaluate(d)

    def test_same_raw_witness_with_different_score_rejected(self):
        d = study_fixture()
        row = d['worlds'][0]['outcomes']
        row['ndu']['decoded_draw_scores'][0]['output_witness_sha256'] = \
            row['no_change']['decoded_draw_scores'][0]['output_witness_sha256']
        with self.assertRaisesRegex(EvidenceGap, 'contradictory scores'):
            evaluate(d)

    def test_full_synthetic_strong_ndu_still_cannot_claim_scientific_authority(self):
        rec = evaluate(study_fixture(bootstrap_replicates=120))
        self.assertEqual(rec['status'], 'HOLD_NO_GO')
        self.assertEqual(rec['authority'], 'DENY_ALL')
        self.assertFalse(rec['scientific_superiority_proven'])
        self.assertFalse(rec['all_provisional_gates_pass'])  # fewer than 2000 bootstraps
        for item in rec['comparison'].values():
            self.assertTrue(all(item['gates'].values()), item['gates'])

    def test_strong_learned_controller_defeats_weak_ndu(self):
        rec = evaluate(study_fixture(strong_ndu=False))
        self.assertFalse(rec['comparison']['free_controller']['gates']['cvar90_incremental_superiority'])
        self.assertEqual(rec['status'], 'HOLD_NO_GO')

    def test_fractional_mass_tail(self):
        self.assertAlmostEqual(cvar90([0] * 10 + [10]), 10 / 1.1)
        self.assertAlmostEqual(cvar90([0] * 13 + [4, 10]), 8)

    def test_missing_baseline_cannot_be_hidden(self):
        d = study_fixture()
        del d['worlds'][12]['outcomes']['free_controller']
        with self.assertRaisesRegex(EvidenceGap, 'matched control'):
            evaluate(d)

    def test_partial_heldout_not_presented_as_success(self):
        d = study_fixture()
        del d['worlds'][-1]
        with self.assertRaisesRegex(EvidenceGap, 'omitted'):
            evaluate(d)

    def test_leaked_calibration_world_rejected(self):
        d = study_fixture()
        d['protocol']['calibration_world_ids'].append(d['worlds'][0]['world_id'])
        with self.assertRaisesRegex(EvidenceGap, 'leakage'):
            evaluate(d)

    def test_different_model_in_ndu_path_rejected(self):
        d = study_fixture()
        d['worlds'][0]['outcomes']['ndu']['model_digest'] = H('cheating-model')
        with self.assertRaisesRegex(EvidenceGap, 'different information'):
            evaluate(d)

    def test_unreconciled_cpu_cost_rejected(self):
        d = study_fixture()
        d['worlds'][2]['outcomes']['ndu']['measured_cost']['total'] -= .2
        with self.assertRaisesRegex(EvidenceGap, 'ledger'):
            evaluate(d)

    def test_missing_cost_stage_rejected(self):
        d = study_fixture()
        del d['worlds'][0]['outcomes']['ndu']['measured_cost']['verifier']
        with self.assertRaisesRegex(EvidenceGap, 'physical total'):
            evaluate(d)

    def test_overspending_denies_provisional_cost_pass(self):
        d = study_fixture()
        for row in d['worlds']:
            cost = row['outcomes']['ndu']['measured_cost']
            cost['controller'] += .5
            cost['total'] += .5
        rec = evaluate(d)
        self.assertFalse(rec['comparison']['free_controller']['gates']['physical_total_cost'])

    def test_protected_task_world_deterioration_is_not_averaged_away(self):
        d = study_fixture()
        dr = d['worlds'][0]['outcomes']['ndu']['decoded_draw_scores']
        for x in dr:
            x['quality'] = 0
        rec = evaluate(d)
        self.assertFalse(rec['comparison']['free_controller']['gates']['protected_task_no_regression'])

    def test_missing_protected_coverage_rejected(self):
        d = study_fixture()
        for row in d['worlds']:
            row['protected_task'] = False
        with self.assertRaisesRegex(EvidenceGap, 'no protected-task'):
            evaluate(d)

    def test_failed_draw_must_stay_in_denominator_as_penalty(self):
        d = study_fixture()
        draw = d['worlds'][0]['outcomes']['ndu']['decoded_draw_scores'][0]
        draw['status'] = 'failed'
        with self.assertRaisesRegex(EvidenceGap, 'failed/overbudget'):
            evaluate(d)
        draw.update(loss=2.0, quality=0, ambiguity=1, inconsistency=1)
        rec = evaluate(d)
        self.assertEqual(rec['worlds_per_seed'], 32)
        self.assertEqual(rec['status'], 'HOLD_NO_GO')

    def test_unwitnessed_decoded_output_rejected(self):
        d = study_fixture()
        del d['worlds'][0]['outcomes']['ndu']['decoded_draw_scores'][0]['output_witness_sha256']
        with self.assertRaisesRegex(EvidenceGap, 'metrics/witness'):
            evaluate(d)

    def test_no_real_decoder_outputs_claimed(self):
        rec = evaluate(study_fixture())
        self.assertIn('untrusted caller', rec['limitations'][0])
        self.assertTrue(any('does not execute' in item for item in rec['limitations']))
        self.assertEqual(len(rec['input_sha256']), 64)


if __name__ == '__main__':
    unittest.main()
