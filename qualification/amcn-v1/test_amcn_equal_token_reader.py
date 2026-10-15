"""Research-only exact-token original Reader and fail-closed journal contracts."""
from __future__ import annotations
import copy
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import amcn_equal_token_reader as study


def fake_plan():
    cases = []
    for family, split in study.HELDOUT:
        for index in range(study.QUESTIONS_PER_FAMILY):
            cid = f'{family}:{index}'
            prompts = {arm: f'fake original {cid} {arm}' for arm in study.ARMS}
            cases.append({'case_id': cid, 'family': family, 'split': split,
                          'question_sha256': sha256(cid.encode()).hexdigest(),
                          'matched_input_token_count': 200,
                          'requests': {arm: {
                              'source_ids': ['D1:1', 'D1:2', 'D1:3'],
                              'prompt': prompts[arm],
                              'prompt_sha256': study._sha(prompts[arm]),
                              'input_token_ids_sha256': 'a' * 64,
                              'expected_input_tokens': 200}
                              for arm in study.ARMS}})
    return {'schema': study.PROFILE,
            'source_sha256': study.SOURCE_SHA,
            'original_rank_decision_sha256': study.RANK_DECISION_SHA,
            'reader_sha256': study.WEIGHT_SHA256,
            'tokenizer_sha256': study.READER_TOKENIZER_SHA,
            'max_output_tokens': study.MAX_NEW_TOKENS,
            'final_evidence_slots': 3,
            'arms': list(study.ARMS), 'cases': cases,
            'independent_future_calendar_windows': 0,
            'gold_used_before_reader': False,
            'production_accepted': False}


class EqualInputReaderSourceTest(unittest.TestCase):
    def test_three_original_arms_and_exact_per_question_token_budget(self):
        study._fixed_plan(fake_plan())
        self.assertEqual(study.QUESTIONS_PER_FAMILY, 12)
        self.assertEqual(len(fake_plan()['cases']) * len(study.ARMS), 72)

    def test_synthetic_missing_or_foreign_case_denied(self):
        x = fake_plan()
        x['cases'].pop()
        with self.assertRaises(ValueError): study._fixed_plan(x)
        x = fake_plan()
        x['cases'][-1]['family'] = 'injected-family'
        with self.assertRaises(ValueError): study._fixed_plan(x)

    def test_duplicate_source_query_denied(self):
        x = fake_plan()
        x['cases'][-1]['case_id'] = x['cases'][0]['case_id']
        with self.assertRaises(ValueError): study._fixed_plan(x)

    def test_changed_pretrained_reader_denied(self):
        x = fake_plan()
        x['reader_sha256'] = 'b' * 64
        with self.assertRaises(ValueError): study._fixed_plan(x)

    def test_changed_prompt_bytes_denied(self):
        x = fake_plan()
        x['cases'][0]['requests']['bm25']['prompt'] += ' secretly edited'
        with self.assertRaises(ValueError): study._fixed_plan(x)

    def test_changed_case_token_budget_denied(self):
        x = fake_plan()
        x['cases'][0]['requests']['bm25']['expected_input_tokens'] += 1
        with self.assertRaises(ValueError): study._fixed_plan(x)

    def test_substituted_source_slot_denied(self):
        x = fake_plan()
        x['cases'][0]['requests']['bm25']['source_ids'] = ['D1:1'] * 3
        with self.assertRaises(ValueError): study._fixed_plan(x)

    def test_premature_model_or_publisher_authority_denied(self):
        x = fake_plan()
        x['gold_used_before_reader'] = True
        with self.assertRaises(ValueError): study._fixed_plan(x)
        x = fake_plan()
        x['independent_future_calendar_windows'] = 2
        with self.assertRaises(ValueError): study._fixed_plan(x)

    def test_no_gold_can_enter_original_source_planner(self):
        x = {'publisher_targets_not_included': False}
        with self.assertRaises(ValueError):
            study.build_plan(x, {}, {}, '/missing', source_sha=study.SOURCE_SHA,
                             rank_sha='a' * 64, predictions_sha='b' * 64)

    def test_failure_requires_independent_journal(self):
        x = fake_plan()
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                study._recount(x, root, object())

    def test_duplicate_json_members_refused(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'duplicate.jsonl'
            path.write_bytes(b'{"case_id":"a","case_id":"b"}\n')
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                study._read_journal(path)

    def test_create_only_and_seal_integrity(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'sealed.json'
            study.seal_once(path, {'production_accepted': False})
            with self.assertRaises(ValueError):
                study.seal_once(path, {'production_accepted': True})

    def test_physical_original_24_case_journal_if_explicitly_staged(self):
        path = os.environ.get('HEPTA_AMCN_EQUAL_INPUT_ROOT')
        if not path:
            self.skipTest('original private 24-question Reader journal not staged')
        root = Path(path)
        plan_path = root / 'equal24-plan.json'
        output = root / 'reader-equal24'
        plan = json.loads(plan_path.read_bytes())
        study._fixed_plan(plan)
        reader = Path(os.environ['HEPTA_AMCN_ORIGINAL_READER_DIRECTORY'])
        tokenizer = study.ArchivedByteLevelBPE(
            reader, expected_tokenizer_sha256=study.READER_TOKENIZER_SHA)
        starts, answers, complete, interrupted = study._recount(plan, output, tokenizer)
        self.assertEqual(len(complete), 72)
        self.assertEqual(len(answers), len(starts))
        self.assertEqual(len(answers), len(complete) + interrupted)
        sealed = json.loads((output / 'seal.json').read_bytes())
        self.assertEqual(sealed['successful_model_answers'], 72)
        self.assertEqual(sealed['attempt_starts_sha256'], study.file_sha(output / 'starts.jsonl'))
        self.assertEqual(sealed['attempt_answers_sha256'], study.file_sha(output / 'raw_answers.jsonl'))


    def test_actual_postseal_publisher_categories_without_conflation(self):
        root = os.environ.get('HEPTA_AMCN_EQUAL_INPUT_ROOT')
        if not root:
            self.skipTest('actual sealed Reader and original private publisher fixture required')
        base = Path(root)
        original = json.loads((base / 'equal24-plan.json').read_bytes())
        sealed = json.loads((base / 'reader-equal24/seal.json').read_bytes())
        publisher = json.loads((base / 'equal24-private-gold-after-seal.json').read_bytes())
        tokenizer = study.ArchivedByteLevelBPE(
            Path(os.environ['HEPTA_AMCN_ORIGINAL_READER_DIRECTORY']),
            expected_tokenizer_sha256=study.READER_TOKENIZER_SHA)
        verdict = study.score(original, sealed, publisher,
                              plan_sha=study.file_sha(base / 'equal24-plan.json'),
                              seal_sha=study.file_sha(base / 'reader-equal24/seal.json'),
                              tokenizer=tokenizer, run_directory=base / 'reader-equal24')
        self.assertEqual(verdict['successful_pretrained_reader_outputs'], 72)
        self.assertFalse(verdict['equal_total_compute_including_pretrained_retrieval_and_training'])
        for arm in study.ARMS:
            row = verdict['arm_totals'][arm]
            self.assertEqual(row['input_tokens'], 5744)
            self.assertEqual(row['publisher_standard_labels'], 20)
            self.assertEqual(row['publisher_adversarial_labels'], 4)
            self.assertEqual(row['weak_any_at3'], 12)
        publisher['by_case_id'][next(iter(publisher['by_case_id']))]['publisher_label_kind'] = 'invented_gold'
        with self.assertRaisesRegex(ValueError, 'answer field'):
            study.score(original, sealed, publisher,
                        plan_sha='a'*64, seal_sha='b'*64,
                        tokenizer=tokenizer, run_directory=base / 'reader-equal24')

    def test_actual_token_journal_corruption_cannot_be_resealed(self):
        root = os.environ.get('HEPTA_AMCN_EQUAL_INPUT_ROOT')
        if not root:
            self.skipTest('requires complete sealed original Reader journal')
        base = Path(root)
        plan = json.loads((base / 'equal24-plan.json').read_bytes())
        reader = Path(os.environ['HEPTA_AMCN_ORIGINAL_READER_DIRECTORY'])
        tokenizer = study.ArchivedByteLevelBPE(
            reader, expected_tokenizer_sha256=study.READER_TOKENIZER_SHA)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            (out / 'starts.jsonl').write_bytes((base / 'reader-equal24/starts.jsonl').read_bytes())
            answers = study._read_journal(base / 'reader-equal24/raw_answers.jsonl')
            answers[0]['generated_token_ids'][-1] = (answers[0]['generated_token_ids'][-1]+1)%49152
            (out / 'raw_answers.jsonl').write_bytes(b''.join(study.canonical(r) for r in answers))
            # A decoded text string is not an invertible commitment to BPE
            # token IDs (EOS and alternate merges can be text-equivalent).
            # The externally pinned original seal and full raw journal SHA,
            # not a self-hashed re-tokenization, must reject the mutation.
            original_seal = json.loads((base / 'reader-equal24/seal.json').read_bytes())
            original_publisher = json.loads(
                (base / 'equal24-private-gold-after-seal.json').read_bytes())
            with self.assertRaisesRegex(ValueError, 'journal byte identity'):
                study.score(plan, original_seal, original_publisher,
                            plan_sha=study.file_sha(base / 'equal24-plan.json'),
                            seal_sha=study.file_sha(base / 'reader-equal24/seal.json'),
                            tokenizer=tokenizer, run_directory=out)


if __name__ == '__main__':
    unittest.main()
