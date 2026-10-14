"""Source partition, outcome-vs-model targets and nonanticipative controls."""
import math
import unittest
from four_gate_common import digest
from fbsde_outcome_data import generate, operation, reward
from fbsde_outcome_audit import source_pair
from fbsde_outcome_policy import select, execute
from fbsde_depth_data import numeric_inputs, construct


class OutcomeTests(unittest.TestCase):
    def test_renderer_and_separate_regex_agree(self):
        pairs=((0,1),(0,2),(1,2))
        for r in generate():
            for t in r['events']:self.assertEqual(source_pair(t,r['names']),pairs.index(operation(t,r['names'])))

    def test_all_raw_texts_disjoint_and_cases_unfiltered(self):
        rows=generate();self.assertEqual(len(rows),636)
        texts={s:{t for r in rows if r['split']==s for t in r['events']} for s in ('train','selection','test','retention')}
        for a in texts:
            for b in texts:
                if a!=b:self.assertFalse(texts[a]&texts[b])
        self.assertEqual(rows,generate())

    def test_wrong_answer_can_make_positive_model_gain_a_negative_outcome(self):
        a={'holder':0,'checks':[]};b={'holder':1,'checks':[{},{}]}
        self.assertAlmostEqual(reward(b,0)-reward(a,0),-2.04)
        rows=[{'source_id':'selection:0','model_gain':.4,'outcome_gain':-2.04}]
        self.assertEqual(select(rows,[.8],'model')['selected'],0.)
        self.assertEqual(select(rows,[.8],'outcome')['selected'],1.01)

    def test_threshold_search_includes_reject_all_and_all_breakpoints(self):
        rows=[{'source_id':'selection:0','outcome_gain':1.},{'source_id':'selection:1','outcome_gain':-2.}]
        r=select(rows,[.51,.50],'outcome');self.assertEqual(r['selected'],.51)

    def test_heldout_and_nonfinite_selection_reject(self):
        with self.assertRaises(ValueError):select([{'source_id':'test:0','outcome_gain':1.}],[.3],'outcome')
        for value in (float('nan'),float('inf')):
            with self.assertRaises(ValueError):select([{'source_id':'selection:0','outcome_gain':value}],[.3],'outcome')
        with self.assertRaises(ValueError):select([{'source_id':'selection:0','outcome_gain':1.}],[True],'outcome')

    def test_no_checks_never_reveals_a_future_operation(self):
        p=construct(numeric_inputs(617,1,'contract')[0],'m','c')
        def forbidden(_):raise AssertionError('future truth read')
        row=execute(p,'no_checks',forbidden)
        self.assertEqual(row['checks'],[]);self.assertFalse(row['depth2_requested'])

    def test_only_chosen_events_are_revealed_once(self):
        for src in numeric_inputs(631,16,'contract'):
            p=construct(src,'m','c');seen=[]
            def reveal(event):
                self.assertNotIn(event,seen);seen.append(event)
                return next(i for i,v in enumerate(p.outcome_law(event)) if v>0)
            r=execute(p,'two_step',reveal)
            self.assertEqual(seen,[v['event'] for v in r['checks']]);self.assertLessEqual(len(seen),2)

    def test_router_binding_and_unknown_arms_reject(self):
        p=construct(numeric_inputs(631,1,'contract')[0],'m','c')
        with self.assertRaises(ValueError):execute(p,'invented',lambda _:0)
        with self.assertRaisesRegex(ValueError,'bound frozen'):
            execute(p,'confidence_outcome',lambda _:0,{'binding':digest('wrong'),'threshold':.5})

if __name__=='__main__':unittest.main()
