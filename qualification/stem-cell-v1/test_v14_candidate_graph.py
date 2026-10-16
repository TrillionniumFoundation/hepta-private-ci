"""Negative/adversarial V14 source-only tests (stdlib, no model)."""
import copy
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from v14_candidate_graph import (build_df, build_public_pairs, digest, distance,
    discover_graph, first_shared_vertex, predict_pair, shortest_path, slots, transform, words)


FACTS=[
    'The coin belongs to Ada.',
    'The bead belongs to Ben.',
    'Ada stores all their possessions in the green box.',
    'Ben stores all their possessions in the silver box.',
]
MODEL={'counts':{t:100 for t in ('the','belongs','to','stores','all','their','possessions','in','box')},
       'schema':'hepta.v14.source-group-document-frequency.v1'}


def row(answer,*,world=0,case=None):
    facts=FACTS if world==0 else [
        'The coin belongs to Ben.','The bead belongs to Ada.',*FACTS[2:]]
    return dict(case_id=case or f'train/2/0/world-{world}/candidate-{answer}',
        source_group='train/2/0',facts=list(facts),
        question='Where is the coin at the box level?',
        candidate='The green box.' if answer==0 else 'The silver box.')


class SourceOnlyTests(unittest.TestCase):
    def test_source_access_regimes_are_explicit(self):
        r=[row(0),row(1),dict(row(0),case_id='held_novel/2/0/world-0/candidate-0',source_group='held_novel/2/0')]
        train=build_df(r,scope='train_only')
        all_unlabeled=build_df(r,scope='unlabeled_transductive')
        self.assertEqual((train['independent_groups'],all_unlabeled['independent_groups']),(1,2))
        self.assertEqual(train['training_labels_accessed'],False)
        self.assertEqual(all_unlabeled['held_answer_labels_accessed'],False)
        with self.assertRaises(ValueError):build_df(r,scope='pretend_future_generalization')

    def test_fact_slots_not_given_grammar_or_two_candidate_lists(self):
        self.assertEqual(slots('The coin belongs to Ada.',MODEL),('coin','ada'))
        self.assertEqual(slots('Ada stores all their possessions in the green box.',MODEL),('ada','green'))
        self.assertEqual(slots('The coin belongs to Ada.',MODEL,reverse=True),('ada','coin'))
        graph,vertices,evidence=discover_graph(FACTS,MODEL)
        self.assertEqual(shortest_path(graph,'coin','green'),('coin','ada','green'))
        self.assertEqual(first_shared_vertex('Where is the coin at the box level?',vertices),'coin')
        self.assertEqual(len(evidence),len(FACTS))

    def test_two_world_truth_flip_without_gold_labels(self):
        for world in (0,1):
            a,b=row(0,world=world),row(1,world=world)
            p,t=predict_pair(a,b,MODEL)
            self.assertEqual([p[a['case_id']],p[b['case_id']]], [1-world, world])
            self.assertTrue(t[a['case_id']]['fact_slots'])
            self.assertEqual(len(t[a['case_id']]['fact_slots']),4)

    def test_reversed_edge_lesion_breaks_original_relation(self):
        a,b=row(0),row(1)
        p,_=predict_pair(a,b,MODEL,reverse=True)
        self.assertEqual([p[a['case_id']],p[b['case_id']]],[None,None])

    def test_shuffled_fact_order_is_invariant(self):
        a,b=row(0),row(1)
        p,_=predict_pair(a,b,MODEL)
        aa=transform(a,'fact_permutation');bb=transform(b,'fact_permutation')
        q,_=predict_pair(aa,bb,MODEL)
        self.assertEqual(p,q)

    def test_scripted_paraphrase_preserves_surface_identity_but_not_direction(self):
        a,b=row(0),row(1)
        aa=transform(a,'meaning_preserving_paraphrase')
        bb=transform(b,'meaning_preserving_paraphrase')
        self.assertEqual(aa['question'],a['question'])
        self.assertEqual(aa['candidate'],a['candidate'])
        self.assertEqual(aa['case_id'],a['case_id'])
        self.assertEqual(aa['facts'][0],'Ada owns the coin.')
        self.assertEqual(aa['facts'][2],'The green box contains possessions owned by Ada.')
        self.assertEqual(len(aa['facts']),len(FACTS))
        self.assertNotEqual(predict_pair(aa,bb,MODEL)[0],predict_pair(a,b,MODEL)[0])

    def test_six_registered_paraphrase_types_only_in_challenge(self):
        examples=('The coin belongs to Ada.',
                  'Ada stores all their possessions in the green box.',
                  'The green box is on the cedar shelf.',
                  'The cedar shelf is in the north room.',
                  'The north room is in the stone building.',
                  'The stone building is in the valley district.')
        r=dict(row(0),facts=list(examples))
        s=transform(r,'meaning_preserving_paraphrase')
        self.assertEqual(len(s['facts']),6)
        self.assertTrue(s['facts'][-1].startswith('The valley district contains'))
        with self.assertRaises(ValueError):transform(dict(r,facts=['ignore previous instructions']),
            'meaning_preserving_paraphrase')

    def test_candidate_grouping_independent_of_case_id_world_labels(self):
        source=[row(0),row(1),row(0,world=1),row(1,world=1)]
        groups=build_public_pairs(source)
        self.assertEqual(len(groups),2)
        self.assertTrue(all(len(g)==2 for g in groups))
        with self.assertRaises(ValueError):build_public_pairs(source+[source[0]])
        with self.assertRaises(ValueError):build_public_pairs(source[:-1])

    def test_malformed_oracle_label_input_fails_closed(self):
        bad=dict(row(0),label=1)
        with self.assertRaises(ValueError):distance(bad,MODEL)
        with self.assertRaises(ValueError):build_df([bad],scope='train_only')
        with self.assertRaises(ValueError):words('')
        with self.assertRaises(ValueError):slots('single',MODEL)
        with self.assertRaises(ValueError):transform(row(0),'invented')

    def test_graph_hard_hop_bound_and_unreachable(self):
        graph={'a':{'b'},'b':{'c'},'c':{'d'},'d':{'e'},'e':{'f'},'f':{'g'}}
        self.assertIsNone(shortest_path(graph,'a','g',max_hops=5))
        self.assertEqual(len(shortest_path(graph,'a','g',max_hops=6))-1,6)
        self.assertIsNone(shortest_path(graph,'a','h'))

    def test_source_hash_and_exact_intent(self):
        public=[row(0),row(1)]
        d=digest(public)
        self.assertEqual(d,hashlib.sha256(__import__('json').dumps(public,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest())
        changed=copy.deepcopy(public);changed[0]['facts'][0]+=' altered'
        self.assertNotEqual(d,digest(changed))

    def test_stdlib_only_subprocess_no_ml_stack(self):
        cmd=[sys.executable,'-S','-c',
             "import sys; import v14_candidate_graph, v14_campaign, v14_independent_review; "
             "assert not any(x in sys.modules for x in ('torch','transformers','safetensors')); "
             "assert callable(v14_campaign.predict)"]
        r=subprocess.run(cmd,cwd=Path(__file__).parent,env={**os.environ,'PYTHONPATH':str(Path(__file__).parent)},
                         capture_output=True,text=True,check=False)
        self.assertEqual(r.returncode,0,r.stderr+r.stdout)


if __name__=='__main__':unittest.main()
