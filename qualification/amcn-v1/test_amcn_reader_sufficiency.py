"""Contract tests of genuine original Reader sufficiency, no model mocks as efficacy."""
from __future__ import annotations

from copy import deepcopy
import json
import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import amcn_reader_sufficiency as s
from amcn_original_text_reader import ArchivedByteLevelBPE

ROOT = Path(os.getenv('HEPTA_READER_SUFF_ORIGINAL_ROOT', '/mnt/data/amcn_e3_work'))
LOCAL = Path(os.getenv('HEPTA_READER_SUFF_PRIVATE_WORK', str(Path(__file__).resolve().parent)))


class FrozenReaderCapacityContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not all((ROOT / f).exists() for f in ('reader/tokenizer.json', 'public-original.json', 'original-withheld.json', 'original-all-1986-ranks.json', 'original/locomo.json')):
            raise unittest.SkipTest('real original LoCoMo/Reader material is required; never fabricate it')
        if not (LOCAL/'reader-plan.json').is_file() or not (LOCAL/'verbatim-plan.json').is_file():
            raise unittest.SkipTest('original externally frozen source-only plans required')
        cls.reader = ArchivedByteLevelBPE(ROOT / 'reader', expected_tokenizer_sha256=s.TOKENIZER_SHA)
        cls.public = s.pinned(ROOT / 'public-original.json', s.PUBLIC_SHA)
        cls.rank_sha = s.file_sha(ROOT / 'original-all-1986-ranks.json')
        cls.rank = s.pinned(ROOT / 'original-all-1986-ranks.json', cls.rank_sha)
        cls.gold_sha = s.file_sha(ROOT / 'original-withheld.json')
        cls.gold = s.pinned(ROOT / 'original-withheld.json', cls.gold_sha)
        cls.original = json.loads((ROOT / 'original/locomo.json').read_bytes())
        cls.original12 = s.pinned(LOCAL/'reader-plan.json', s.file_sha(LOCAL/'reader-plan.json'))
        cls.literal8 = s.pinned(LOCAL/'verbatim-plan.json', s.file_sha(LOCAL/'verbatim-plan.json'))

    def test_source_only_plan_exact_original_12_by_four_families(self):
        self.assertEqual(s.validate_plan(self.original12,self.reader),48)
        self.assertEqual(s.sha(self.original12),'7b410e2e05b66767d8c5a67c97eee354f294b1ce8e4c8954e87cdb4ee7db4cb7')
        self.assertFalse(self.original12['publisher_answer_text_ever_seen_during_prepare'])

    def test_blind_annotation_cohort_rebuilds_byte_exact(self):
        new=s.make_plan(self.public,s.PUBLIC_SHA,self.rank,self.rank_sha,self.gold,self.gold_sha,self.reader)
        self.assertEqual(s.sha(new),s.sha(self.original12))

    def test_publisher_source_is_only_added_to_the_oracle_proxy(self):
        for row in self.original12['cases']:
            support=row['publisher_weak_source_id'];req=row['requests']
            self.assertEqual(req['no_evidence']['sources'],[])
            self.assertNotIn(support,req['original_bm25_top3']['sources'])
            self.assertEqual(req['publisher_annotated_witness']['sources'][0],support)
            self.assertNotIn(support,req['publisher_witness_lesion']['sources'])
            self.assertEqual(req['publisher_annotated_witness']['sources'][1:],req['publisher_witness_lesion']['sources'][:2])

    def test_four_archived_reader_prompts_not_truncated(self):
        for plan in (self.original12,self.literal8):
            for case in plan['cases']:
                for arm in s.ARMS:
                    req=case['requests'][arm]
                    self.assertEqual(req['input_tokens'],len(self.reader.encode(req['prompt'])))
                    self.assertLessEqual(req['input_tokens']+s.MAX_NEW,s.MAX_CONTEXT)

    def test_noevidence_only_question_unadulterated(self):
        for row in self.original12['cases']:
            empty=row['requests']['no_evidence']
            self.assertFalse('[E1]' in empty['prompt'].split('user\n',1)[1])
            self.assertIn('Question: ',empty['prompt'])

    def test_changed_original_reader_identity_denied(self):
        plan=deepcopy(self.original12)
        plan['reader_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'model/issuer'):
            s.validate_plan(plan,self.reader)

    def test_fake_independence_claim_denied(self):
        plan=deepcopy(self.original12)
        plan['publisher_support_not_independent_human_review']=False
        with self.assertRaisesRegex(ValueError,'model/issuer'):
            s.validate_plan(plan,self.reader)

    def test_future_window_unauthenticated_denied(self):
        plan=deepcopy(self.original12)
        plan['independent_future_windows']=2
        with self.assertRaisesRegex(ValueError,'model/issuer'):
            s.validate_plan(plan,self.reader)

    def test_premise_lesion_that_retains_publisher_source_denied(self):
        plan=deepcopy(self.original12)
        row=plan['cases'][0]
        row['requests']['publisher_witness_lesion']['sources'][0]=row['publisher_weak_source_id']
        with self.assertRaisesRegex(ValueError,'support manipulation'):
            s.validate_plan(plan,self.reader)

    def test_publisher_answer_selected_stress_cohort_has_gold_flag(self):
        self.assertEqual(s.validate_plan(self.literal8,self.reader),32)
        self.assertTrue(self.literal8['publisher_answer_used_for_stress_cohort_selection'])
        self.assertTrue(self.literal8['publisher_answer_text_ever_seen_during_prepare'])
        self.assertEqual(s.sha(self.literal8),'8810ac2a88190fb27aded5f25920c8e0ea48ad08c1369ae67b5aed4723087b41')

    def test_verbatim_selected_cases_rebuild_and_have_literal_witness(self):
        whitelist=s.original_verbatim_ids(self.public,self.gold,self.original,
                                         expected_original_sha256=s.DATA_SHA)
        new=s.make_plan(self.public,s.PUBLIC_SHA,self.rank,self.rank_sha,
                        self.gold,self.gold_sha,self.reader,candidate_whitelist=whitelist)
        self.assertEqual(s.sha(new),s.sha(self.literal8))
        self.assertEqual(len(new['cases']),8)
        self.assertTrue(all(r['case_id'] in whitelist for r in new['cases']))

    def test_publishers_gold_not_passed_to_model_process(self):
        self.assertNotIn('adversarial_answer',json.dumps(self.original12))
        self.assertNotIn('adversarial_answer',json.dumps(self.literal8))
        self.assertNotIn('"answer"',json.dumps(self.literal8))

    def test_missing_planned_query_count_denied(self):
        plan=deepcopy(self.original12)
        plan['cases'].pop()
        with self.assertRaisesRegex(ValueError,'missing original'):
            s.validate_plan(plan,self.reader)

    def test_missing_original_source_refused_during_prepare(self):
        pub=deepcopy(self.public)
        pub['sources']['conv-49']=[]
        with self.assertRaises(ValueError):
            s.make_plan(pub,s.PUBLIC_SHA,self.rank,self.rank_sha,self.gold,self.gold_sha,self.reader)

    def test_false_original_label_census_denied(self):
        weak=deepcopy(self.gold)
        weak['public_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'segregated'):
            s.make_plan(self.public,s.PUBLIC_SHA,self.rank,self.rank_sha,weak,self.gold_sha,self.reader)

    def test_original_48_attempts_independently_recounted(self):
        folder=LOCAL/'original-48-reader-attempts'
        if not (folder/'seal.json').exists(): self.skipTest('local original not mounted')
        pin=s.file_sha(folder/'seal.json')
        answers=s.recount(self.original12,folder,self.reader,s.sha(self.original12),pin)
        self.assertEqual(len(answers),48)
        self.assertEqual({a['index'] for a in answers.values()},set(range(48)))

    def test_create_only_original_journal(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'test.json'
            pin=s.create_once(path,{'schema':'denial','production_accepted':False})
            self.assertEqual(s.pinned(path,pin)['production_accepted'],False)
            with self.assertRaisesRegex(ValueError,'create-only'):
                s.create_once(path,{'schema':'fake success'})

    def test_strict_rollback_of_independently_pinned_answer(self):
        folder=LOCAL/'original-48-reader-attempts'
        if not (folder/'seal.json').exists(): self.skipTest('local original not mounted')
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)
            for name in ('starts.jsonl','statuses.jsonl','raw_answers.jsonl','seal.json'):
                (target/name).write_bytes((folder/name).read_bytes())
            with (target/'raw_answers.jsonl').open('ab') as out:out.write(b'{}\n')
            with self.assertRaisesRegex(ValueError,'journals modified'):
                s.recount(self.original12,target,self.reader,s.sha(self.original12),s.file_sha(folder/'seal.json'))

    def test_postseal_original_12_dataset_outputs_are_not_task_success(self):
        path=LOCAL/'original-48-postseal-score.json'
        if not path.exists():self.skipTest('postseal result absent')
        verdict=json.loads(path.read_bytes())
        self.assertEqual(verdict['cohort_questions'],12)
        self.assertFalse(verdict['experimental_decisions']['reader_sufficiency_human_verified'])
        self.assertIsNone(verdict['experimental_decisions']['independent_semantic_correctness'])
        self.assertEqual(verdict['observed_arm_aggregates']['publisher_annotated_witness']['weak_support_hit'],12)
        self.assertFalse(verdict['experimental_decisions']['production_accepted'])


if __name__=='__main__':unittest.main()
