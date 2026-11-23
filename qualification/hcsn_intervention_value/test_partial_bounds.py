"""Known-answer 24-query tests. No corpus files are required."""
import unittest
import numpy as np
from . import partial_bounds as b


class TestPartialBounds(unittest.TestCase):
    def test_enumerated_support(self):
        f=b.entry_states('read','chosen',None,0,{})
        nr=b.entry_states('noread','chosen',None,0,{})
        self.assertAlmostEqual(min(x[3] for x in f),b.L)
        self.assertAlmostEqual(max(x[3] for x in f),1.)
        self.assertEqual(b.paired_missing(f,f,'identical'),[0.,0.])
        self.assertEqual(b.paired_missing(f,f,None),[b.L-1,1-b.L])
        self.assertAlmostEqual(b.paired_missing(f,nr,None)[1],1-b.utility(5,0,0))
        self.assertEqual(b.paired_missing([(0,0,0,0.)],[(0,1,1,.7),(0,0,0,0.)],'same_immediate'),[0.,0.])
        pure={'exit_prefix':0,'terminal_action':1,'hit':1,'utility':.7}
        self.assertEqual(b.entry_states('read','immediate_paid',pure,0,{(0,1):1}),[(0,1,1,.7)])
        with self.assertRaises(ValueError): b.entry_states('read','chosen',pure,0,{})
        waited=b.entry_states('read','chosen',{'waited_prefixes':5},5,{})
        self.assertEqual({x[0] for x in waited},{5})

    def test_partial_vision_and_dev_alias(self):
        name='read-fixed-keep-181391'; record={'exit_prefix':0,'terminal_action':1,'hit':1,'utility':.7}; q='synthetic-first'
        known={'observed_prefixes':{q:0},'always_paid':{q:record},'partial':{q:{name:{'immediate_paid':record,'dev_immediate':record}}},
               'partial_frontend':{q:{'free_probability':[],'paid_probability':[[.1,.9]]*6,'target':1}}}
        canonical=b.normalize_known(known,{name:{'immediate_choice':'immediate_paid'}})
        hits=b.known_hits(canonical,{q},{name})[q]; self.assertEqual(hits,{(t,1):1 for t in range(6)})
        self.assertEqual(set(canonical['partial'][q][name]),{'immediate_paid'}); self.assertIn('dev_immediate',known['partial'][q][name])
        low=min(x[3] for x in b.entry_states('read','chosen',None,0,hits)); self.assertAlmostEqual(low,b.utility(5,0,0))
        self.assertEqual(b.entry_states('read','immediate_paid',record,0,hits),[(0,1,1,.7)])

    def test_weights_sign_and_classification(self):
        groups={f'g{i}-w{j}':f'g{i}' for i in range(6) for j in range(4)}
        rows={q:[1.,1.] for q in groups};rows['g0-w1']=[b.L,1.];rows['g2-w0']=[b.L,1.]
        m=b.source_mean(rows,groups);self.assertAlmostEqual(m['macro'][0],(22+2*b.L)/24)
        self.assertAlmostEqual(m['per_source']['g0'][0],(3+b.L)/4)
        self.assertEqual(b.gate(m['macro'],.60),b.PASS)
        self.assertEqual(b.gate([-.2,0.],0.,True),b.FAIL)
        self.assertEqual(b.gate([0.,1.],0.,True),b.UNKNOWN)
        d=b.sign_support({i:[1.,1.] if i<4 else [-.2,.2] for i in range(6)})
        self.assertEqual(d['positive_sources'],[4,6]);self.assertAlmostEqual(d['sign_p'][0],1/64)
        self.assertEqual(d['p_at_most_025'],b.UNKNOWN)

    def test_optional_exact_prefix_and_original_denom(self):
        groups={f'g{i}-w{j}':f'g{i}' for i in range(6) for j in range(4)};bad=['g0-w0','g1-w3'];ids=[q for q in groups if q not in bad]
        def trace(t,a,h):
            return dict(exit_prefix=[t]*22,terminal_action=[a]*22,episode_hit=[h]*22,episode_utility=[b.utility(t,a,h)]*22)
        outcomes={};fits={}
        for m,o in b.ARMS:
            for seed in b.SEEDS:
                for av in ('read','noread'):
                    name=f'{av}-{m}-{o}-{seed}';obs=trace(0,0,1)
                    outcomes[name]=dict(query_id=ids,group=[groups[q] for q in ids],chosen=obs,keep=obs,disable_read=obs,
                                    immediate_controls={'immediate_free':obs},immediate_choice='immediate_free')
                    fits[name]=dict(head=[1],keep_head=[1],theta=[0],keep_theta=[0],immediate_choice='immediate_free')
        basic=b.calculate(groups,outcomes,fits,{})
        name='read-fixed-keep-'+str(b.SEEDS[0]); arm=basic['read_arms'][name];self.assertEqual(arm['paired']['matched_keep']['worst'],[0.,0.])
        self.assertAlmostEqual(arm['absolute']['r1']['macro'][0],22/24)
        early={'partial':{bad[1]:{name:{'chosen':{'exit_prefix':2,'terminal_action':1,'hit':1,'utility':b.utility(2,1,1)}}}},'observed_prefixes':{bad[0]:0,bad[1]:5}}
        enhanced=b.calculate(groups,outcomes,fits,early)['read_arms'][name]
        self.assertAlmostEqual(enhanced['absolute']['r1']['macro'][0],23/24)
        self.assertAlmostEqual(enhanced['absolute']['utility']['macro'][0],(22+b.utility(2,1,1)+b.L)/24)
        self.assertEqual(enhanced['absolute']['reads'],[1,2]); self.assertEqual(enhanced['absolute']['waiting_queries'],[1,2]); self.assertEqual(enhanced['paired']['matched_keep']['worst'],[0,0]);self.assertEqual(enhanced['gates']['absolute'],b.PASS)
        self.assertEqual(basic['read_arms'][name]['absolute']['reads'],[0,2])


if __name__=='__main__':unittest.main()
