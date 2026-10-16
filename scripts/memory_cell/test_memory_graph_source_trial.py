"""Source-only seal, chronology, negative-control and label-isolation tests."""
import tempfile
import unittest
from pathlib import Path
from memory_graph_source_trial import (
    PUBLIC_SCHEMA, DATASET_SHA, ARMS, canonical, sha,
    save_new, strict_json, read_public, source_graph, ranked_ids, bm25_table,
    run, review, sealed_run
)


def fixture(root):
    prep, public = root / 'prepared', root / 'public'
    prep.mkdir();public.mkdir()
    groups, labels = [], {}
    for family_n in range(1, 11):
        name = f'conv-{family_n}'
        docs = [dict(id=f'D{family_n}:{i}', speaker='Alice',
                     text=f'Session {i} event note on apple {i} and procedure.',
                     session='session_1' if i <= 64 else 'session_2',
                     seq=i,kind='semantic') for i in range(1, 129)]
        questions = []
        for j in range(24):
            qid = f'{name}/q{j:04d}'
            questions.append(dict(id=qid,text=f'When was apple {j+1} mentioned?',kind='semantic'))
            labels[qid] = dict(evidence=[docs[j]['id']],unresolved_reference=False,
                               answer_available=True,category=1)
        groups.append(dict(family=name,sources=docs,questions=questions))
    public_rec=dict(schema=PUBLIC_SCHEMA,dataset_sha256=DATASET_SHA,
                    policy=dict(source_policy='all-eligible-ascii',source_max=1024,
                                question_limit=24,train_prefix=128),families=groups)
    public_sha=save_new(prep/'public.json',public_rec)
    private_sha=save_new(prep/'private.json',dict(schema=PUBLIC_SCHEMA,annotations=labels))
    meta=dict(schema=PUBLIC_SCHEMA,dataset_sha256=DATASET_SHA,
              public_sha256=public_sha,private_sha256=private_sha,
              production_accepted=False, family_count=10, question_count=240,
              source_count=1280)
    save_new(prep/'manifest.json',meta)
    (public/'public.json').write_bytes((prep/'public.json').read_bytes())
    (public/'manifest.json').write_bytes((prep/'manifest.json').read_bytes())
    return prep,public


class SourceTrialTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.prep,self.public=fixture(self.root)

    def test_unscored_public_has_complete_source_only_census(self):
        a,meta=read_public(self.public)
        self.assertEqual(sum(len(g['sources']) for g in a['families']),1280)
        self.assertNotIn('evidence',(self.public/'public.json').read_text())
        self.assertEqual(meta['question_count'],240)

    def test_source_only_four_arms_and_window_control(self):
        a,_=read_public(self.public)
        first=a['families'][0]
        graph=source_graph(first['family'],first['sources'])
        self.assertFalse(any(e.source=='D1:64' and e.target=='D1:65'
                             for e in graph.edges))
        ranks=ranked_ids(first['questions'][0]['text'],first['sources'],
                         bm25_table([d['speaker']+': '+d['text'] for d in first['sources']]),graph)
        self.assertEqual(set(ranks),set(ARMS))
        self.assertTrue(all(len(r)==8 and len(set(r))==8 for r in ranks.values()))
        self.assertEqual(len(graph.nodes),128)

    def test_run_review_full_seal_and_denominators(self):
        out=self.root/'run'
        seal=run(self.public,out)
        save_new(out/'seal.json',seal)
        self.assertEqual(seal['count'],240)
        self.assertFalse(seal['real_reader_executed'])
        _,_,j,_=sealed_run(self.public,out)
        self.assertEqual(len(j),240)
        result=review(self.prep,out,self.root/'report.json')
        self.assertEqual(result['reference_positive'],240)
        self.assertEqual(result['reference_eligible'],240)
        self.assertEqual(len(result['by_family']),10)
        for v in result['by_arm'].values():
            self.assertEqual(v['referenced'],240)
        self.assertFalse(result['causal_graph_or_parametric_advantage'])

    def test_private_or_poisoned_fields_never_reach_ranking(self):
        (self.public/'private.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'hidden labels'):
            run(self.public,self.root/'denied')
        (self.public/'private.json').unlink()
        value=strict_json((self.public/'public.json').read_bytes())
        value['families'][0]['questions'][0]['answer']='gold leak'
        (self.public/'public.json').write_bytes(canonical(value))
        with self.assertRaisesRegex(ValueError,'public corpus identity'):
            read_public(self.public)

    def test_review_cannot_accept_mutated_prediction_even_resigned(self):
        out=self.root/'run'
        seal=run(self.public,out)
        save_new(out/'seal.json',seal)
        rows=strict_json((out/'journal.json').read_bytes())
        rows[0]['predictions']['graph'][0]=rows[0]['predictions']['bm25'][1]
        rows[0]['predictions']['graph'][1]=rows[0]['predictions']['bm25'][0]
        (out/'journal.json').write_bytes(canonical(rows))
        seal['journal_sha256']=sha(canonical(rows))
        (out/'seal.json').write_bytes(canonical(seal))
        with self.assertRaisesRegex(ValueError,'drifted graph run'):
            review(self.prep,out,self.root/'tampered.json')

    def test_revocation_rebuild_and_cross_scope_fencing(self):
        a,_=read_public(self.public)
        graph=source_graph(a['families'][0]['family'],a['families'][0]['sources'])
        root=graph.nodes['D1:1'].root
        with self.assertRaises(ValueError):
            graph.recall(seed='D1:1',scope='conv-1',generation=1,revoked={root})
        with self.assertRaises(ValueError):
            graph.recall(seed='D1:1',scope='conv-2',generation=1)

    def test_private_digest_and_duplicate_json_fail_closed(self):
        out=self.root/'run';seal=run(self.public,out);save_new(out/'seal.json',seal)
        (self.prep/'private.json').write_text('{"schema":"forged"}')
        with self.assertRaisesRegex(ValueError,'private annotation SHA'):
            review(self.prep,out,self.root/'bad.json')
        with self.assertRaisesRegex(ValueError,'duplicate JSON'):
            strict_json(b'{"x":1,"x":2}')

if __name__=='__main__':unittest.main()
