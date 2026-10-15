"""True producer/consumer receipt replay with synthetic *files* and symbolic labels.

Tests the real independent-review and scoring entrypoints, without mocking the
reviewer. None of these fake model files are trained weights or pretrained runs.
"""
import hashlib
import json
import sys
from types import SimpleNamespace
from collections import Counter
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from cross_fact_granite_campaign import ARMS, SEEDS, _digest, _write_once
from cross_fact_granite_review import review, read
from cross_fact_granite_score import score_sealed
from test_cross_fact_granite_score import ROLES, fake_store, mock_cases
from cross_fact_granite_review import independent_training_score
from cross_fact_granite_receipt_oracle import derive_schedule, _hash


def train_cases():
    # Add original ReaderCase answer_id without changing the independent fresh
    # scoring fixtures used elsewhere.
    return tuple(SimpleNamespace(**vars(c), answer_id=c.candidate[-1])
                 for c in mock_cases('train'))


def _caseroster_digest(cases):
    return hashlib.sha256(json.dumps([c.case_id for c in cases],
        separators=(',', ':')).encode()).hexdigest()


def populate_receipts(root):
    summary = fake_store(root)
    plan = read(root/'plan.json')
    plan.update(steps=8000, hidden_width=32, extra_parameters_per_arm=4096,
                external_result_was_used_for_selection=False,
                new_code_sha256={name:_digest(Path(__file__).parent/name)
                     for name in ('cross_fact_bridge.py','cross_fact_granite_campaign.py',
                             'cross_fact_granite_receipt_oracle.py')},
                train_case_ids_sha256=_caseroster_digest(train_cases()))
    (root/'plan.json').write_text(json.dumps(plan))
    train = train_cases()
    probs = [.95 if c.label else .05 for c in train]
    accuracy = independent_training_score(train, probs)
    assert accuracy['accuracy'] == accuracy['both_worlds_correct'] == 1
    assert accuracy['probability_CE'] < .1
    for seed in SEEDS:
        schedule = derive_schedule(train, seed, steps=8000, batch_size=16)
        sampled = schedule[:250]
        sample_cases = [[train[index].case_id for index in batch] for batch in sampled]
        exposures = dict(Counter(case_id for batch in sample_cases for case_id in batch))
        updates = [dict(step=step, indices=list(indices), case_ids=list(case_ids),
                 sample_sha256=_hash(case_ids), exposures=16, depth=3, pair_weight=.5,
                 finite_gradients=True, inference_feature_arguments=6,
                 cpu_ns=1, wall_ns=1) for step,(indices,case_ids) in
                 enumerate(zip(sampled,sample_cases),1)]
        sub = root/f'seed-{seed}'
        sub.mkdir()
        for arm in ARMS:
            row = summary[str(seed)][arm]
            # These are arbitrary synthetic file bytes for tamper tests, never
            # valid Tensor weights or source of a claimed actual training run.
            binary = sub/f'{arm}.pt'
            binary.write_bytes(f'DENY_ALL_fake_not_model:{seed}:{arm}'.encode())
            row.update(model_file_sha256=_digest(binary),
                       schedule_sha256=_hash(schedule),
                       original_parameter_digest='2'*64,
                       trained_parameter_digest='3'*64,
                       training_cpu_ns=300, training_wall_ns=300,
                       natural_internal_tune={'f1_a':.25},
                       old_task_internal_not_selection=True)
            for role in ROLES:
                sealed_path=root/f'sealed-{role}-{seed}-{arm}.json'
                sealed=read(sealed_path)
                sealed['weights_sha256']=row['model_file_sha256']
                sealed_path.write_text(json.dumps(sealed))
            code_model_digest='4'*64
            internal=sub/f'{arm}-natural-internal.json'
            _write_once(internal, dict(scope='old_training_source_internal_tune_not_fresh',
                threshold_selected=False, metrics=row['natural_internal_tune'],
                model_execution_parameter_sha256=code_model_digest))
            row['natural_internal_file_sha256'] = _digest(internal)
            receipt=sub/f'{arm}-training.json'
            _write_once(receipt, dict(seed=seed, requested_steps=8000,
                initial_model_sha256='2'*64, model_sha256='3'*64,
                parameter_count=row['parameter_count'],
                schedule_sha256=row['schedule_sha256'],
                completed_steps=250, actual_training_exposures=4000,
                cpu_ns=300, wall_ns=300, optimizer_tensor_bytes=800,
                updates=updates, case_exposures=exposures,
                case_ids=[case.case_id for case in train], train_gate_passed=True,
                status='train_gate_passed', diagnostics=[dict(optimizer_step=250,
                     binding=dict(probabilities=probs, accuracy=1.,
                     both_worlds_correct=1., binary_cross_entropy=accuracy['probability_CE']))]))
            manifest=sub/f'{arm}-model.json'
            _write_once(manifest,dict(file=f'{arm}.pt',
                file_sha256=row['model_file_sha256'],
                training_receipt_file=f'{arm}-training.json',
                training_receipt_sha256=_digest(receipt),
                execution_parameter_sha256=code_model_digest))
    (root/'fit-summary.json').write_text(json.dumps(summary))
    (root/'all-models-frozen.json').write_text(json.dumps(
        {str(seed):{arm:summary[str(seed)][arm]['model_file_sha256'] for arm in ARMS}
         for seed in SEEDS}))
    return summary


def protocol_patch():
    token = types.ModuleType('token_protocol')
    token.build_binding_cases=lambda role,groups,seed: train_cases()
    binding = types.ModuleType('binding_protocol')
    binding.build_binding_protocol=lambda seed: {r:mock_cases(r) for r in ROLES}
    binding.score_binding_probabilities=independent_training_score
    return patch.dict(sys.modules,{'token_protocol':token,'binding_protocol':binding})


class ReceiptCustodyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        populate_receipts(self.root)

    def test_full_replay_of_all_six_receipts_and_twelve_scores(self):
        with protocol_patch():
            before=review(self.root)
            self.assertTrue(before['receipt_consistency_passed'])
            self.assertTrue(before['all_training_gates_passed'])
            self.assertFalse(before['separate_scoring_completed'])
            self.assertEqual(score_sealed(self.root),12)
            after=review(self.root)
        self.assertTrue(after['separate_scoring_completed'])
        self.assertEqual(len(after['fresh_source_disjoint_scores']),12)
        self.assertTrue(all(row['accuracy']==1 for row in
                            after['fresh_source_disjoint_scores'].values()))

    def test_changing_one_actual_fake_weight_with_flags_untouched_denies_before_score(self):
        victim=self.root/'seed-47'/'local.pt'
        victim.write_bytes(victim.read_bytes()+b'altered')
        with protocol_patch():
            with self.assertRaisesRegex(ValueError,'model file digest'):
                score_sealed(self.root)
        self.assertFalse(list(self.root.glob('score-*.json')))

    def test_receipt_tampering_with_intact_summary_denies(self):
        victim=self.root/'seed-53'/'cross_fact-training.json'
        record=read(victim)
        record['completed_steps'] += 1
        victim.write_text(json.dumps(record))
        with protocol_patch():
            with self.assertRaisesRegex(ValueError,'training receipt digest'):
                score_sealed(self.root)
        self.assertFalse(list(self.root.glob('score-*.json')))

    def test_mutating_old_task_retention_stops_future_score(self):
        victim=self.root/'seed-41'/'cross_fact-natural-internal.json'
        victim.write_text(json.dumps(dict(source='different')))
        with protocol_patch():
            with self.assertRaisesRegex(ValueError,'internal-tune receipt'):
                score_sealed(self.root)
        self.assertFalse(list(self.root.glob('score-*.json')))


if __name__=='__main__':
    unittest.main()
