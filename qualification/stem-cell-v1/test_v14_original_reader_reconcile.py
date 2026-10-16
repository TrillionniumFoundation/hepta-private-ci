"""Fully matched V14 source→real-request→answer→review fixtures (no real model)."""
import copy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import v14_original_reader_reconcile as full
import v14_reader_original_request_builder as producer
import v14_reader_sufficiency_gate as gate
from test_v14_reader_original_request_builder import original_source_fixture


def h(s):
    return sha256(s.encode('utf-8')).hexdigest()


def synthetic_complete_chain():
    src = original_source_fixture()
    plan, private = producer.prepare(src)
    outputs = {
        'schema': gate.SCHEMA + '.predictions',
        'plan_sha256': gate.sha_obj(plan),
        'model_output_source': 'external_original_required',
        'production_authorized': False,
        'records': [],
    }
    judge = {
        'schema': gate.SCHEMA + '.adjudication',
        'plan_sha256': gate.sha_obj(plan),
        'predictions_sha256': '',
        'reviewer_id': 'synthetic-unverified-reviewer',
        'reviewer_independence_unverified': True,
        'results': [],
    }
    for case in plan['cases']:
        for reader in gate.READERS:
            for arm in gate.ARMS:
                request = case['arms'][arm]
                answer = h('synthetic-nonmodel-answer/' + case['id'] + reader + arm)
                refs = request['evidence_ids'][:1]
                outputs['records'].append({
                    'case_id': case['id'],
                    'reader': reader,
                    'arm': arm,
                    'request_sha256': request['request_sha256'],
                    'model_sha256': plan['models'][reader]['weights_sha256'],
                    'answer_sha256': answer,
                    'cited_evidence_ids': refs,
                    'input_tokens': 24,
                    'output_tokens': 3,
                    'cpu_ms': 4,
                    'wall_ms': 3,
                    'abstained': arm == 'none',
                })
                grounded = arm == 'sufficient'
                judge['results'].append({
                    'case_id': case['id'],
                    'reader': reader,
                    'arm': arm,
                    'answer_sha256': answer,
                    'correct': grounded,
                    'citations_entailed': grounded,
                })
    judge['predictions_sha256'] = gate.sha_obj(outputs)
    return src, plan, private, outputs, judge


class FullSourceChain(unittest.TestCase):
    def setUp(self):
        self.src, self.plan, self.private, self.outputs, self.judge = synthetic_complete_chain()

    def run_gate(self):
        return full.reconcile(self.src, self.plan, self.private,
                              self.outputs, self.judge)

    def test_full_chain_stays_research_only(self):
        result = self.run_gate()
        self.assertEqual(result['case_count'], 2)
        self.assertEqual(result['source_first_original_prompts_reconstructed'], 8)
        self.assertEqual(result['two_reader_arm_outcomes_seen'], 16)
        self.assertEqual(result['decision'], 'HOLD_NO_GO')
        for key in ('stem_winner_verified','physical_pretrained_reader_calls_verified',
                    'new_prospective_source_families_verified',
                    'source_owner_authenticated','system2_verified','production_authorized'):
            self.assertFalse(result[key])

    def test_original_source_changed(self):
        self.src['cases'][0]['sources'][0]['text'] = 'malicious rewrite'
        with self.assertRaises(ValueError):
            self.run_gate()

    def test_model_request_changed(self):
        self.private['requests']['question-0']['sufficient']['raw_original_model_input'] = 'injected'
        with self.assertRaises(ValueError):
            self.run_gate()

    def test_wrong_plan_digest(self):
        self.plan['cases'][0]['arms']['lesion']['request_sha256'] = h('fake')
        with self.assertRaises(ValueError):
            self.run_gate()

    def test_foreign_output_model_identity(self):
        self.outputs['records'][0]['model_sha256'] = h('foreign model')
        with self.assertRaises(ValueError):
            self.run_gate()

    def test_original_output_census_exhaustive(self):
        self.outputs['records'].pop()
        with self.assertRaises(ValueError):
            self.run_gate()

    def test_wrong_answer_hash_in_review(self):
        self.judge['results'][0]['answer_sha256'] = h('fake answer')
        with self.assertRaises(ValueError):
            self.run_gate()

    def test_reviewer_claimed_independent_auth_is_denied(self):
        self.judge['reviewer_independence_unverified'] = False
        with self.assertRaises(ValueError):
            self.run_gate()

    def test_citation_not_delivered_denied(self):
        self.outputs['records'][0]['cited_evidence_ids'] = ['foreign-source']
        with self.assertRaises(ValueError):
            self.run_gate()

    def test_dispatched_counter_is_exact(self):
        result = self.run_gate()
        totals = result['reported_per_reader_arm']
        self.assertEqual(sum(a['cases'] for reader in totals.values() for a in reader.values()), 16)
        self.assertEqual(totals['candidate']['sufficient']['grounded_correct'], 2)
        self.assertEqual(result['grounding_and_capacity_diagnostics']['lesion_sensitive'], 2)

    def test_order_invariant_score_but_source_bound_receipts(self):
        old = self.run_gate()
        self.outputs['records'].reverse()
        self.judge['predictions_sha256'] = gate.sha_obj(self.outputs)
        self.judge['results'].reverse()
        updated = self.run_gate()
        self.assertEqual(old['reported_per_reader_arm'], updated['reported_per_reader_arm'])
        self.assertEqual(old['grounding_and_capacity_diagnostics'],
                         updated['grounding_and_capacity_diagnostics'])
        self.assertNotEqual(old['complete_chain_sha256'], updated['complete_chain_sha256'])

    def test_cli_does_not_export_private_source(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            files = []
            for name, obj in [('source',self.src),('plan',self.plan),
                              ('private',self.private),('predictions',self.outputs),
                              ('adjudication',self.judge)]:
                path = root / (name + '.json')
                path.write_text(json.dumps(obj))
                files.append((name, str(path)))
            cmd = [sys.executable, str(Path(full.__file__))]
            for name,path in files:
                cmd.extend(('--private-requests' if name=='private' else '--'+name, path))
            out = subprocess.run(cmd, capture_output=True, text=True, check=True)
            report = json.loads(out.stdout)
            self.assertEqual(report['decision'], 'HOLD_NO_GO')
            self.assertNotIn(self.src['cases'][0]['sources'][0]['text'], out.stdout)


if __name__ == '__main__':
    unittest.main()
