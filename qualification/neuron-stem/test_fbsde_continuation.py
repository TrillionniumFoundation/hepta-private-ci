"""Original-equation/tangent invariants; no semantic, timing or promotion assertions."""
import copy
from dataclasses import asdict, FrozenInstanceError, replace
import math
import unittest

from four_gate_common import digest
from fbsde_coupled import CoupledProfile
from fbsde_riccati import solve_newton
from fbsde_continuation import TARGET, compile_bank, load_bank, tangent
from fbsde_workspace import choose_candidate
from fbsde_workspace_audit import check_result


class ContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = CoupledProfile(steps=3)
        cls.ctx = dict(scope='test',generation=1,objective=digest(TARGET))
        cls.bank = compile_bank(cls.p,[-1.,0.,1.],**cls.ctx)

    def candidates(self):
        return [{'id':'a','x0':.21,'cost':.8},{'id':'b','x0':.46,'cost':1.1},
                {'id':'c','x0':-.1,'cost':.55}]

    def test_saved_bank_roundtrip_and_no_caller_alias(self):
        artifact = {**self.bank.payload(),'sha256':self.bank.identity}
        loaded = load_bank(artifact,**self.ctx)
        artifact['anchors'][0]['y'][0] += 4
        self.assertEqual(loaded,self.bank)
        with self.assertRaises(FrozenInstanceError): loaded.generation = 2

    def test_tangent_matches_independent_central_difference(self):
        h = 1e-5; x = .2
        y = solve_newton(self.p,x,tolerance=1e-12)['y']; d = tangent(self.p,x,y)
        plus = solve_newton(self.p,x+h,tolerance=1e-12)['y']
        minus = solve_newton(self.p,x-h,tolerance=1e-12)['y']
        self.assertLess(max(abs(a-(b-c)/(2*h)) for a,b,c in zip(d,plus,minus)),1e-7)

    def test_predictor_not_marked_original_solution(self):
        r = self.bank.predict(self.p,.2,**self.ctx)
        self.assertFalse(r['original_equation_verified'])
        self.assertGreater(max(abs(a-b) for a,b in zip(r['y'],solve_newton(self.p,.2)['y'])),1e-4)

    def test_rehashed_bad_anchor_is_rejected(self):
        body = self.bank.payload(); body['anchors'][1]['y'][0] += .01
        with self.assertRaisesRegex(ValueError,'anchor equation'):
            load_bank({**body,'sha256':digest(body)},**self.ctx)

    def test_rehashed_bad_derivative_is_rejected(self):
        body = self.bank.payload(); body['anchors'][1]['dy_dx0'][0] += .01
        with self.assertRaisesRegex(ValueError,'tangent equation'):
            load_bank({**body,'sha256':digest(body)},**self.ctx)

    def test_no_reuse_across_scope_generation_objective_or_dynamics(self):
        for key,value in [('scope','other'),('generation',2),('objective',digest('other'))]:
            ctx = {**self.ctx,key:value}
            with self.assertRaisesRegex(ValueError,'cross-scope'):
                self.bank.predict(self.p,.2,**ctx)
        with self.assertRaisesRegex(ValueError,'cross-scope'):
            self.bank.predict(replace(self.p,sigma=.31),.2,**self.ctx)

    def test_no_extrapolation_or_nan(self):
        for x in (1.1,float('nan'),float('inf'),True):
            with self.assertRaises(ValueError): self.bank.predict(self.p,x,**self.ctx)
        with self.assertRaises(ValueError): self.bank.predict(self.p,.2,**{**self.ctx,'generation':True})

    def test_duplicate_and_oversized_anchor_grids_fail(self):
        for xs in ([0.,0.], [0.,-.2], list(range(18))):
            with self.assertRaises(ValueError): compile_bank(self.p,xs,**self.ctx)

    def test_decision_checked_against_all_precise_control(self):
        cs = self.candidates()
        actual = choose_candidate(self.p,cs,self.bank,**self.ctx)
        control = choose_candidate(self.p,cs,self.bank,mode='cold_all',**self.ctx)
        self.assertEqual(actual['selected'],control['selected'])
        check_result(asdict(self.p),cs,actual,1e-8)
        self.assertFalse(actual['semantic_correctness_claimed'])

    def test_exhaustion_has_no_answer_or_silent_fallback(self):
        r = choose_candidate(self.p,self.candidates(),self.bank,max_refinements=0,**self.ctx)
        self.assertEqual((r['status'],r['selected'],r['text']),('unresolved',None,None))
        self.assertFalse(r['production_promotion_permitted'])

    def test_zero_budget_can_accept_an_already_verified_clear_choice(self):
        cs = [{'id':'a','x0':1.,'cost':0.},{'id':'b','x0':-1.,'cost':1.}]
        r = choose_candidate(self.p,cs,self.bank,max_refinements=0,**self.ctx)
        self.assertEqual((r['status'],r['selected'],r['refinements']),('resolved','a',0))

    def test_extra_label_channel_and_duplicate_id_fail(self):
        for mutation in ('label','id','cost'):
            cs = self.candidates()
            if mutation == 'label': cs[0]['gold'] = 'a'
            elif mutation == 'id': cs[1]['id'] = cs[0]['id']
            else: cs[1]['cost'] = float('nan')
            with self.assertRaises(ValueError): choose_candidate(self.p,cs,self.bank,**self.ctx)

    def test_modified_terminal_score_or_decode_rejected(self):
        cs = self.candidates(); result = choose_candidate(self.p,cs,self.bank,**self.ctx)
        for field in ('score','text','gap','trajectory'):
            row = copy.deepcopy(result)
            if field == 'score': row['rows'][0]['score'] += 1
            elif field == 'text': row['text'] = 'Everything proved.'
            elif field == 'gap': row['gap_bound'] += 1
            else: row['rows'][0]['y'].pop()
            with self.assertRaises(ValueError): check_result(asdict(self.p),cs,row,1e-8)

    def test_identical_candidates_have_consistent_tie(self):
        cs = [{'id':'first','x0':.2,'cost':.4},{'id':'second','x0':.2,'cost':.4}]
        r = choose_candidate(self.p,cs,self.bank,**self.ctx)
        self.assertEqual(r['selected'],'first')
        self.assertLessEqual(r['gap_bound'],1e-8)
