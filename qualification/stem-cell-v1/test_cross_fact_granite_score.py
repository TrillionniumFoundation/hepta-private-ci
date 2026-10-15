"""Model-free end-to-end independent sealed-to-scored phase and negative controls."""
from dataclasses import dataclass
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from cross_fact_granite_campaign import ARMS, SEEDS, _write_once
from cross_fact_granite_score import (
    ROLES, check_campaign_gates, check_global_seals, check_sealed_panel, score_sealed,
)
from cross_fact_granite_review import independent_training_score, read


@dataclass(frozen=True)
class Case:
    case_id: str
    paragraph_id: str
    candidate: str
    label: int


def mock_cases(role):
    return tuple(Case(f'{role}/{group}/world-{world}/{candidate}',
                      f'{role}/{group}/world-{world}', f'candidate-{candidate}',
                      int(candidate == world))
                 for group in range(32) for world in range(2) for candidate in range(2))


def fake_store(root):
    root = Path(root)
    summary = {str(seed): {arm: dict(status='train_gate_passed', train_gate_passed=True,
         completed_steps=250, actual_training_exposures=4000,
         optimizer_tensor_bytes=800, parameter_count=8192,
         model_file_sha256='a'*64, schedule_sha256='b'*64)
         for arm in ARMS} for seed in SEEDS}
    _write_once(root/'plan.json', dict(seeds=list(SEEDS), arms=list(ARMS), production_authorized=False))
    _write_once(root/'fit-summary.json', summary)
    _write_once(root/'opening-decision.json', dict(matched_fresh_gate_passed=True,
         all_model_fit_gates_passed=True, all_actual_training_budgets_equal=True))
    _write_once(root/'terminal.json', dict(status='all_frozen_predictions_sealed_pending_independent_scoring',
         fresh_prediction_seals_complete=True, fresh_scoring_authorized=False))
    _write_once(root/'all-models-frozen.json', {str(seed): {arm: 'a'*64 for arm in ARMS} for seed in SEEDS})
    for role in ROLES:
        ids = [c.case_id for c in mock_cases(role)]
        for seed in SEEDS:
            for arm in ARMS:
                _write_once(root/f'sealed-{role}-{seed}-{arm}.json', dict(
                     case_ids=ids, weights_sha256='a'*64, labels_entered_model=False,
                     scoring_started=False, probabilities=[.9 if c.label else .1 for c in mock_cases(role)],
                     batches=[dict(case_ids=ids[offset:offset+16], steps=3, proposal_steps=48,
                                   cpu_ns=1, wall_ns=1) for offset in range(0,128,16)]))
    return summary


class SeparateScoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.summary = fake_store(self.root)
        self.ids = {role: [c.case_id for c in mock_cases(role)] for role in ROLES}

    def test_exact_twelve_frozen_seals_admit_without_outcome(self):
        self.assertEqual(len(check_global_seals(self.root, self.ids)), 12)
        self.assertEqual(check_campaign_gates(self.root)['41']['local'], 'a'*64)

    def test_missing_bad_batch_or_stale_weight_blocks_all_scores(self):
        victim = self.root/'sealed-fresh_combinations-41-local.json'
        obj = read(victim)
        obj['batches'][7]['case_ids'][0] = 'wrong-source'
        victim.write_text(json.dumps(obj))
        with self.assertRaisesRegex(ValueError, 'batch identities'):
            check_global_seals(self.root, self.ids)
        self.assertFalse(list(self.root.glob('score-*.json')))
        obj['batches'][7]['case_ids'] = self.ids['fresh_combinations'][112:128]
        obj['weights_sha256'] = 'b'*64
        victim.write_text(json.dumps(obj))
        with self.assertRaisesRegex(ValueError, 'weight identity'):
            check_global_seals(self.root, self.ids)

    def test_unmatched_actual_training_cost_denies_scoring(self):
        self.summary['47']['local']['optimizer_tensor_bytes'] += 1
        (self.root/'fit-summary.json').write_text(json.dumps(self.summary))
        with self.assertRaisesRegex(ValueError, 'equal-investment'):
            check_campaign_gates(self.root)

    def test_separate_python_phase_writes_full_twelve_scores_from_fixed_seals(self):
        module = types.ModuleType('binding_protocol')
        module.build_binding_protocol = lambda seed: {role: mock_cases(role) for role in ROLES}
        module.score_binding_probabilities = independent_training_score
        with patch.dict(sys.modules, {'binding_protocol': module}):
            self.assertEqual(score_sealed(self.root), 12)
        manifest = read(self.root/'scoring-completion.json')
        self.assertEqual(manifest['scored_count'],12)
        self.assertEqual(len(manifest['score_files']),12)
        self.assertFalse(manifest['production_authorized'])
        self.assertEqual(len(list(self.root.glob('score-*.json'))),12)
        with patch.dict(sys.modules, {'binding_protocol': module}):
            with self.assertRaisesRegex(ValueError, 'duplicate fresh'):
                score_sealed(self.root)

    def test_no_fresh_labels_import_before_training_gate(self):
        self.summary['53']['local']['train_gate_passed'] = False
        (self.root/'fit-summary.json').write_text(json.dumps(self.summary))
        with patch.dict(sys.modules, {'binding_protocol': None}):
            with self.assertRaisesRegex(ValueError, 'equal-investment'):
                score_sealed(self.root)


if __name__ == '__main__':
    unittest.main()
