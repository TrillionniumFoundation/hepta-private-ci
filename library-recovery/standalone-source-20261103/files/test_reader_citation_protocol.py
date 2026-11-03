"""Contract tests only. No original model weights or publisher labels in fixtures."""
from pathlib import Path
import copy
import tempfile
import unittest

import associative_graph_causal as graph
import reader_citation_protocol as study
import reader_premise_format as premise
import test_reader_premise_format as fixture


class FakeTokenizer:
    def render(self,messages):
        return '\n'.join(v['content'] for v in messages)

    def encode(self,body):
        return [3,5,8] if 'Question:' in body else [3,5,7]

    def decode(self,tokens):
        return 'the answer [E1]'


class FakeReader:
    tokenizer=FakeTokenizer()

    def generate(self,tokens,maximum):
        if maximum!=study.MAX_TOKENS:
            raise ValueError('unexpected generation cap')
        return list(tokens)


class OriginalCitationControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.PublishedPlanContract.setUpClass()
        cls.base=fixture.PublishedPlanContract.plan
        cls.plan=study.make_plan(cls.base)
        cls.tmp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.tmp.name)
        cls.plan_dir=cls.root/'plan'
        cls.plan_dir.mkdir()
        graph.create_only(cls.plan_dir/'plan.json',cls.plan)
        graph.create_only(cls.plan_dir/'seal.json', {
            'schema':study.SCHEMA,'sha256':graph.digest(graph.canonical(cls.plan)),
            'planned':study.COUNT,'production_accepted':False})

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        fixture.PublishedPlanContract.tearDownClass()

    def test_four_frozen_conditions_ten_dialogue_groups(self):
        self.assertEqual(len(self.plan['rows']),40)
        self.assertEqual({r['arm'] for r in self.plan['rows']},set(study.ARMS))
        self.assertEqual(len({r['question_id'] for r in self.plan['rows']}),10)
        self.assertNotIn('private gold must not appear in plan',graph.canonical(self.plan).decode())

    def test_source_set_unchanged_across_citation_format(self):
        for i in range(0,40,4):
            self.assertEqual({graph.digest(graph.canonical(r['evidence']))
                              for r in self.plan['rows'][i:i+4]},
                             {graph.digest(graph.canonical(self.plan['rows'][i]['evidence']))})
            self.assertEqual(len({study._user_text(x) for x in self.plan['rows'][i:i+4]}),4)

    def test_baseline_equals_original_annotated_lines(self):
        before={r['question_id']:r for r in self.base['entries'] if r['arm']=='annotated_lines'}
        for row in self.plan['rows']:
            if row['arm']=='legacy_lines':
                self.assertEqual(study._user_text(row), premise._prompt(before[row['question_id']]))

    def test_run_cannot_open_hidden_reference(self):
        self.assertEqual(study._read_plan(self.plan_dir)[0],self.plan)
        (self.plan_dir/'private.json').write_text('{}')
        try:
            with self.assertRaisesRegex(ValueError,'restricted'):
                study._read_plan(self.plan_dir)
        finally:
            (self.plan_dir/'private.json').unlink()

    def test_source_changed_even_with_hash_reseal_is_detectable(self):
        altered=copy.deepcopy(self.plan)
        for r in altered['rows'][:4]:
            r['evidence'][0]['text']='fabricated source text'
        study.validate(altered)
        self.assertNotEqual(study.make_plan(self.base),altered)

    def test_reject_cross_arm_source_content_drift(self):
        altered=copy.deepcopy(self.plan)
        altered['rows'][1]['evidence'][0]['text']='different evidence'
        with self.assertRaisesRegex(ValueError,'candidate evidence differs'):
            study.validate(altered)

    def test_reject_duplicate_or_retargeted_label(self):
        altered=copy.deepcopy(self.plan)
        altered['rows'][1]['evidence'][0]['label']='E2'
        with self.assertRaises(ValueError):study.validate(altered)
        altered=copy.deepcopy(self.plan)
        altered['rows'][1]['arm']='legacy_lines'
        with self.assertRaises(ValueError):study.validate(altered)

    def test_actual_budget_and_unmodified_answer_in_fake_reader(self):
        model=FakeReader()
        for row in self.plan['rows'][:4]:
            result=study.generate(model,row)
            self.assertEqual(result['status'],'succeeded')
            self.assertFalse(result['answer_postprocessed'])
            self.assertEqual(result['generated_tokens'],3)
            self.assertEqual(result['answer'],'the answer [E1]')

    def test_no_reseal_can_change_journal_question_or_prompt(self):
        root=self.root/'journal'
        root.mkdir()
        entries=[]
        for row in self.plan['rows']:
            entries.append({'question_id':row['question_id'],'arm':row['arm'],
                'family':row['family'],
                'source_ids':[x['source_id'] for x in row['evidence']],
                'prompt_sha256':graph.digest(study._user_text(row).encode()),
                'result':study.generate(FakeReader(),row)})
        digest=graph.create_only(root/'journal.json',entries)
        sealed={'schema':study.SCHEMA,'plan_sha256':graph.digest(graph.canonical(self.plan)),
            'journal_sha256':digest,
            'reader_identity':'afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c',
            'reader_parity_certified':False,'planned':study.COUNT,
            'max_generated_tokens':study.MAX_TOKENS,'answers_in_worker':False,
            'production_accepted':False}
        graph.create_only(root/'seal.json',sealed)
        self.assertEqual(len(study._read_journal(self.plan,sealed|{'sha256':sealed['plan_sha256']},root)[0]),40)
        forged=copy.deepcopy(entries)
        forged[0]['prompt_sha256']='a'*64
        (root/'journal.json').write_bytes(graph.canonical(forged))
        sealed['journal_sha256']=graph.digest(graph.canonical(forged))
        (root/'seal.json').write_bytes(graph.canonical(sealed))
        with self.assertRaisesRegex(ValueError,'prompt or source lineage'):
            study._read_journal(self.plan,{'sha256':sealed['plan_sha256']},root)

    def test_citations_may_be_structurally_valid_without_semantic_truth(self):
        matches=[f'E{x}' for x in study.CITATIONS.findall('Answer [E1] [E2]')]
        self.assertEqual(matches,['E1','E2'])
        self.assertNotIn('E2',{'E1'})
        self.assertFalse(self.plan['production_accepted'])


if __name__=='__main__':
    unittest.main()
