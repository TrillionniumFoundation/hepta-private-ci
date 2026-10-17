"""Source-only builder tests. Synthetic snippets are NOT original task evidence."""
import copy
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

import v14_reader_original_request_builder as b
import v14_reader_sufficiency_gate as gate


def digest(raw):
    return sha256(raw.encode('utf-8')).hexdigest()


def original_source_fixture():
    cases = []
    for i in range(2):
        cases.append({
            'id': 'question-' + str(i),
            'family': 'family-' + str(i),
            'window': 'historical',
            'question': 'Which verified fact answers question ' + str(i) + '?',
            'sources': [
                {'id': 'e1', 'text': 'The blue object was placed first.'},
                {'id': 'e2', 'text': 'A second independently cited source agrees.'},
                {'id': 'e3', 'text': 'An irrelevant red object was visible.'},
                {'id': 'e4', 'text': 'Context only; the answer is not here.'},
            ],
            'arms': {
                'none': [],
                'retrieved': ['e3', 'e4'],
                'sufficient': ['e1', 'e2'],
                'lesion': ['e2'],
            },
        })
    return {
        'schema': b.SCHEMA_INPUT,
        'source_only': True,
        'gold_available_before_predictions': False,
        'production_authorized': False,
        'objective_sha256': digest('frozen objective'),
        'max_output_tokens': 24,
        'models': {
            reader: {
                'weights_sha256': digest(reader + '-weights'),
                'tokenizer_sha256': digest(reader + '-tokenizer'),
                'runtime_sha256': digest(reader + '-runtime'),
            } for reader in gate.READERS
        },
        'cases': cases,
    }


class OriginalRequestContracts(unittest.TestCase):
    def setUp(self):
        self.src = original_source_fixture()

    def expected_rejection(self, mutate):
        mutate(self.src)
        with self.assertRaises((ValueError, KeyError)):
            b.prepare(self.src)

    def test_source_only_materializes_all_four_original_inputs(self):
        plan, private = b.prepare(self.src)
        gate.check_plan(plan)
        self.assertEqual(len(plan['cases']), 2)
        self.assertEqual(sum(len(v) for v in private['requests'].values()), 8)
        self.assertEqual(private['source_input_sha256'], gate.sha_obj(self.src))
        self.assertFalse(private['model_executed'])
        self.assertFalse(private['publisher_gold_available'])
        self.assertFalse(plan['production_authorized'])
        for case in plan['cases']:
            for arm in gate.ARMS:
                row = private['requests'][case['id']][arm]
                self.assertEqual(
                    sha256(row['raw_original_model_input'].encode()).hexdigest(),
                    case['arms'][arm]['request_sha256'])
                self.assertNotIn('ARM=', row['raw_original_model_input'])
                self.assertNotIn('gold', row)
        self.assertTrue(b.verify_source_packet(self.src, plan, private)['source_replay_equal'])

    def test_input_diff_is_material_not_relabeling(self):
        plan, packet = b.prepare(self.src)
        fingerprints = [plan['cases'][0]['arms'][arm]['request_sha256'] for arm in gate.ARMS]
        self.assertEqual(len(set(fingerprints)), 4)
        self.assertNotIn('retrieved', packet['requests']['question-0']['retrieved']['raw_original_model_input'])
        self.assertEqual(packet['requests']['question-0']['none']['delivered_evidence'], [])

    def test_raw_question_and_source_change_rebuilds_sha(self):
        plan, packet = b.prepare(self.src)
        self.src['cases'][0]['sources'][0]['text'] += ' Additional new fact.'
        with self.assertRaises(ValueError):
            b.verify_source_packet(self.src, plan, packet)

    def test_private_request_substitution_denied(self):
        plan, packet = b.prepare(self.src)
        packet['requests']['question-0']['sufficient']['raw_original_model_input'] = 'fake'
        with self.assertRaises(ValueError):
            b.verify_source_packet(self.src, plan, packet)

    def test_wrong_request_sha_denied(self):
        plan, packet = b.prepare(self.src)
        plan['cases'][0]['arms']['retrieved']['request_sha256'] = digest('fabricated')
        with self.assertRaises(ValueError):
            b.verify_source_packet(self.src, plan, packet)

    def test_different_evidence_ids_require_actual_different_input(self):
        self.expected_rejection(lambda s:s['cases'][0]['arms'].__setitem__('retrieved', ['e2']))

    def test_unknown_source_reference_rejected(self):
        self.expected_rejection(lambda s:s['cases'][0]['arms']['retrieved'].append('other'))

    def test_duplicate_source_ids_rejected(self):
        self.expected_rejection(lambda s:s['cases'][0]['sources'].append(
            {'id':'e1','text':'different source'}))

    def test_gold_answer_field_is_forbidden(self):
        self.expected_rejection(lambda s:s['cases'][0].update(publisher_answer='secret'))

    def test_gold_exposure_is_forbidden(self):
        self.expected_rejection(lambda s:s.update(gold_available_before_predictions=True))

    def test_modified_objective_with_fake_authority_rejected(self):
        self.expected_rejection(lambda s:s.update(production_authorized=True))

    def test_bad_model_identity_rejected(self):
        self.expected_rejection(lambda s:s['models']['reference'].update(
            weights_sha256=s['models']['candidate']['weights_sha256']))

    def test_duplicate_case_id_rejected(self):
        self.expected_rejection(lambda s:s['cases'][1].update(id='question-0'))

    def test_unregistered_text_control_rejected(self):
        self.expected_rejection(lambda s:s['cases'][0]['sources'][0].update(
            text='  leading whitespace'))

    def test_empty_or_huge_source_rejected(self):
        self.expected_rejection(lambda s:s['cases'][0]['sources'][0].update(text=''))
        self.src = original_source_fixture()
        self.expected_rejection(lambda s:s['cases'][0]['sources'][0].update(text='x' * 8193))

    def test_create_only_private_file_is_mode_0600(self):
        _, packet = b.prepare(self.src)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'private.json'
            b.write_private_once(path, packet)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                b.write_private_once(path, packet)

    def test_symlink_output_is_rejected(self):
        _, packet = b.prepare(self.src)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = root/'actual'
            a.write_text('do not modify')
            link = root/'symlink'
            link.symlink_to(a)
            with self.assertRaises(FileExistsError):
                b.write_private_once(link, packet)
            self.assertEqual(a.read_text(), 'do not modify')

    def test_cli_emits_source_free_receipt_without_model_execution(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root/'source.json'
            source.write_text(json.dumps(self.src), encoding='utf-8')
            plan = root/'plan.json'
            private = root/'private.json'
            proc = subprocess.run([
                sys.executable, str(Path(b.__file__)), '--source', str(source),
                '--plan', str(plan), '--private-requests', str(private)
            ], capture_output=True, text=True, check=True)
            receipt = json.loads(proc.stdout)
            self.assertEqual(receipt['original_reader_requests'], 16)
            self.assertFalse(receipt['real_pretrained_reader_executed'])
            self.assertFalse(receipt['production_authorized'])
            self.assertEqual(json.loads(private.read_text())['plan_sha256'],
                             gate.sha_obj(json.loads(plan.read_text())))

    def test_ordered_evidence_cannot_be_silently_swapped(self):
        plan, private = b.prepare(self.src)
        self.src['cases'][0]['arms']['sufficient'].reverse()
        updated, _ = b.prepare(self.src)
        self.assertNotEqual(updated['cases'][0]['arms']['sufficient']['request_sha256'],
                            plan['cases'][0]['arms']['sufficient']['request_sha256'])
        with self.assertRaises(ValueError):
            b.verify_source_packet(self.src, plan, private)


if __name__ == '__main__':
    unittest.main()
