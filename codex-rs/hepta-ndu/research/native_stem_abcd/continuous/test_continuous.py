"""R6 weighted math and mechanism tests. Not efficacy evidence."""
import tempfile
import unittest
from pathlib import Path
import numpy as np
import torch
from domain import Policy, adjoint, rule, probe, check_law, evaluate, make_problem, SCALE
from solver import fit
from run_continuous import dump, panels, specs, name_for, gradient_at


class ContinuousTests(unittest.TestCase):
    def setUp(self):
        self.p=make_problem();self.pol=Policy('nonlinear',11)
        self.z=torch.tensor(self.pol.initial);self.s,self.w=rule('cc3')

    def test_rule_mass_and_nonnegative(self):
        for r in ('corners','cc3','cc5','cc9','cc17','gl9'):
            s,w=rule(r);check_law(s,w);self.assertTrue((w>0).all())
            self.assertTrue((np.abs(s)<=SCALE+1e-15).all())

    def test_rule_constant_and_linear(self):
        for r in ('cc3','cc5','cc9','cc17','gl9'):
            s,w=rule(r);self.assertAlmostEqual(w.sum(),1,14)
            np.testing.assert_allclose(w@s,0,atol=2e-16)

    def test_rule_uniform_second_and_mixed_moments(self):
        for r in ('cc3','cc5','cc9','cc17','gl9'):
            s,w=rule(r);np.testing.assert_allclose(w@(s*s),SCALE**2/3,atol=3e-15)
            self.assertAlmostEqual(float(w@(s[:,0]**2*s[:,2]**2)),SCALE[0]**2*SCALE[2]**2/9,14)

    def test_quartic_moment_and_corner_bias(self):
        for r in ('cc5','cc9','cc17','gl9'):
            s,w=rule(r);np.testing.assert_allclose(w@(s**4),SCALE**4/5,atol=3e-15)
        s,w=rule('corners');self.assertGreater(abs(float(w@(s[:,2]**2))-SCALE[2]**2/3),.3)

    def test_nested_node_sets(self):
        for a,b in [('cc3','cc5'),('cc5','cc9'),('cc9','cc17')]:
            s,_=rule(a);ss,_=rule(b)
            for j in range(4):
                for x in np.unique(s[:,j]):self.assertLess(np.min(np.abs(ss[:,j]-x)),2e-15)

    def test_invalid_rule_and_law(self):
        for r in ('cc7','test','gl17'):
            with self.assertRaises(ValueError):rule(r)
        for w in (np.ones(81),np.full(81,np.nan),np.r_[-1.,np.full(80,.025)]):
            with self.assertRaises(ValueError):check_law(self.s,w)

    def test_same_parent_probes_not_training_nodes(self):
        a=probe(0);b=probe(1);np.testing.assert_array_equal(a,probe(0))
        self.assertFalse(np.array_equal(a,b));self.assertTrue((np.abs(a)<SCALE).all())
        for row in a:self.assertFalse(any(np.array_equal(row,s) for s in self.s))

    def test_nonuniform_weighted_adjoint_vs_ad(self):
        w=np.arange(1,82,dtype=float)**2;w/=w.sum()
        val,g=adjoint(self.z,self.p,self.s,w)
        ad=torch.func.grad(lambda z:self.pol.value(z,self.p,self.s,w))(self.z)
        np.testing.assert_allclose(g,ad,rtol=1e-12,atol=1e-14)
        self.assertAlmostEqual(float(val),float(self.pol.value(self.z,self.p,self.s,w)),14)

    def test_uniform_gradient_is_not_weighted_gradient(self):
        _,g=adjoint(self.z,self.p,self.s,self.w)
        _,wrong=adjoint(self.z,self.p,self.s,np.ones(81)/81)
        self.assertGreater(float((g-wrong).abs().max()),1e-3)

    def test_weighted_gradient_finite_difference(self):
        _,g=adjoint(self.z,self.p,self.s,self.w)
        for k in (0,20,52,77):
            e=torch.zeros_like(self.z);e[k]=1e-5
            d=(self.pol.value(self.z+e,self.p,self.s,self.w)-self.pol.value(self.z-e,self.p,self.s,self.w))/2e-5
            self.assertAlmostEqual(float(g[k]),float(d),8)

    def test_weighted_hessian_vs_ad(self):
        H=torch.func.jacfwd(lambda z:adjoint(z,self.p,self.s,self.w)[1])(self.z)
        G=torch.func.hessian(lambda z:self.pol.value(z,self.p,self.s,self.w))(self.z)
        np.testing.assert_allclose(H,G,rtol=1e-11,atol=2e-13)
        np.testing.assert_allclose(H,H.T,atol=2e-13)

    def test_ridge_objective_and_gradient_separate(self):
        v,g=adjoint(self.z,self.p,self.s,self.w,ridge=.001)
        v0,g0=adjoint(self.z,self.p,self.s,self.w)
        self.assertAlmostEqual(float(v-v0),.0005*float(self.z.square().mean()),14)
        np.testing.assert_allclose(g-g0,.001*self.z/self.z.numel(),atol=1e-14)

    def test_matrix_scalar_weighted_adjoint(self):
        for family in ('matrix','scalar'):
            pol=Policy(family,23);z=torch.tensor(pol.initial)
            g=adjoint(z,self.p,self.s,self.w,family)[1]
            G=torch.func.grad(lambda x:pol.value(x,self.p,self.s,self.w))(z)
            np.testing.assert_allclose(g,G,atol=1e-13)

    def test_attention_really_trains_from_weight_vector(self):
        pol=Policy('attention',11);z=torch.tensor(pol.initial)
        g=torch.func.grad(lambda x:pol.value(x,self.p,self.s[:2],np.ones(2)/2))(z)
        self.assertGreater(float(g.abs().sum()),.01);self.assertEqual(len(z),666)

    def test_chunked_evaluation_matches_full(self):
        a=evaluate(self.pol,self.z,self.p,self.s,chunk=13)
        b=evaluate(self.pol,self.z,self.p,self.s,chunk=1000)
        np.testing.assert_allclose(a,b,atol=2e-15)

    def test_chunked_gradient_matches_full(self):
        s,w=rule('cc5');g=gradient_at(self.pol,self.z,self.p,'cc5')
        ad=torch.func.grad(lambda z:self.pol.value(z,self.p,s,w))(self.z)
        np.testing.assert_allclose(g,ad,atol=2e-13)

    def test_budget_without_trial_keeps_initial(self):
        z,r=fit(self.pol,self.p,self.s,self.w,'adjoint',1e-12)
        np.testing.assert_array_equal(z,self.pol.initial)
        self.assertEqual(r['counts']['updates'],0)

    def test_actual_adam_and_adjoint_training(self):
        before=float(self.pol.value(self.z,self.p,self.s,self.w))
        for method in ('adam','adjoint'):
            z,r=fit(self.pol,self.p,self.s,self.w,method,1.5)
            self.assertGreater(r['counts']['updates'],0)
            self.assertLess(float(self.pol.value(torch.tensor(z),self.p,self.s,self.w)),before)

    def test_nochange_control_replays(self):
        z,r=fit(self.pol,self.p,self.s,self.w,'none')
        np.testing.assert_array_equal(z,self.pol.initial)
        self.assertEqual(r['status'],'untrained')

    def test_exclusive_evidence_write(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'p.json';dump(p,{'value':1})
            with self.assertRaises(FileExistsError):dump(p,{'value':2})
            self.assertIn('1',p.read_text())

    def test_frozen_census_pairing(self):
        runs=specs();self.assertEqual(len(runs),43);self.assertEqual(len({name_for(s) for s in runs}),43)
        for s in runs:
            if s['family']=='nonlinear' and s['method']=='adjoint':
                other=dict(s,method='adam');self.assertIn(other,runs)
                np.testing.assert_array_equal(Policy('nonlinear',s['seed']).initial,Policy('nonlinear',other['seed']).initial)

    def test_scope_labels_and_same_parent_points(self):
        pp=list(panels());self.assertEqual(len(pp),12)
        self.assertEqual(sum(p[-1]=='changed_problem' for p in pp),3)
        for name,s,w,p,scope in pp:
            check_law(s,w)
            if scope!='changed_problem':np.testing.assert_array_equal(p.A,self.p.A)

if __name__=='__main__':unittest.main(verbosity=2)
