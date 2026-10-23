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
        'calibration_world_ids': [f'calibration-{i}' for i in range(100)],
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
                           'public_input_digest': identity,
                           'protected_task': idx % 4 == 0,
                           'outcomes': arms})
    return {'schema': 'hepta-mgp-paired-v1', 'protocol': p, 'worlds': worlds}


class PairedEvidenceTests(unittest.TestCase):
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

    def test_protected_loss_regression_rejected_despite_global_tail_gain(self):
        d = study_fixture()
        for dr in d['worlds'][0]['outcomes']['ndu']['decoded_draw_scores']:
            dr['loss'] = 0.60
        rec = evaluate(d)
        self.assertTrue(rec['comparison']['free_controller']['gates']['cvar90_incremental_superiority'])
        self.assertFalse(rec['comparison']['free_controller']['gates']['protected_task_no_regression'])

    def test_protected_inconsistency_regression_is_not_hidden_by_global_mean(self):
        d = study_fixture()
        for dr in d['worlds'][0]['outcomes']['ndu']['decoded_draw_scores']:
            dr['inconsistency'] = 0.08
        rec = evaluate(d)
        self.assertFalse(rec['comparison']['free_controller']['gates']['protected_task_no_regression'])

    def test_each_seed_requires_protected_coverage(self):
        d = study_fixture()
        for row in d['worlds']:
            if row['seed'] == 211:
                row['protected_task'] = False
        with self.assertRaisesRegex(EvidenceGap, 'protected-task coverage'):
            evaluate(d)

    def test_proxy_mac_not_accepted_as_measured_total_cost(self):
        d = study_fixture()
        d['protocol']['cost_units'] = 'synthetic_mac_proxy'
        with self.assertRaisesRegex(EvidenceGap, 'physical cost unit'):
            evaluate(d)

    def test_nonhex_identity_digest_rejected(self):
        d = study_fixture()
        d['protocol']['selection_lock_digest'] = 'G'*64
        with self.assertRaisesRegex(EvidenceGap, 'selection lock'):
            evaluate(d)

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
        self.assertIn('does not execute', rec['limitations'][2])
        self.assertEqual(len(rec['input_sha256']), 64)


if __name__ == '__main__':
    unittest.main()
