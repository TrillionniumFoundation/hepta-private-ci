"""Independent derivative, convex-reference, lineage and executable fit tests."""
import unittest
import numpy as np
import torch
from problem import *
from reference import build,evaluate,solve
from solve import fit

torch.set_num_threads(1)
class Tests(unittest.TestCase):
    def setUp(self):
        self.p=make_problem();self.s=initial();self.t=torch.tensor(initial_weights(11))
    def test_full_population_adjoint(self):
        for f in ('nonlinear','matrix','scalar'):
            t=torch.tensor(initial_weights(23,f));v,g=adjoint(t,self.p,self.s,f)
            auto=torch.func.grad(lambda z:objective(z,self.p,self.s,f))(t)
            np.testing.assert_allclose(g,auto,atol=2e-13,rtol=2e-12)
    def test_adjoint_finite_difference(self):
        v,g=adjoint(self.t,self.p,self.s)
        for i in (0,23,47,48,64,68,77):
            d=torch.zeros_like(self.t);d[i]=1e-5
            fd=(objective(self.t+d,self.p,self.s)-objective(self.t-d,self.p,self.s))/2e-5
            self.assertAlmostEqual(float(fd),float(g[i]),places=8)
    def test_adjoint_hessian(self):
        H=torch.func.jacfwd(lambda z:adjoint(z,self.p,self.s)[1])(self.t)
        ad=torch.func.hessian(lambda z:objective(z,self.p,self.s))(self.t)
        np.testing.assert_allclose(H,ad,atol=2e-12,rtol=2e-11)
    def test_all_parameter_groups_active(self):
        _,g=adjoint(self.t,self.p,self.s)
        for a,b in ((0,48),(48,64),(64,68),(68,76),(76,78)):
            self.assertGreater(float(g[a:b].abs().sum()),1e-7)
    def test_policy_is_actually_nonlinear_and_bounded(self):
        w=self.p.tensors();sx=torch.tensor(self.s);m=torch.zeros(len(sx),dtype=torch.long)
        a,_=control(self.t,sx,m,0,self.p,'nonlinear');b,_=control(self.t,2*sx,m,0,self.p,'nonlinear')
        self.assertGreater(float((b-2*a).abs().max()),1e-5)
        self.assertLess(float(b.abs().max()),self.p.bound)
    def test_identical_family_initialization(self):
        for seed in (11,23,47):np.testing.assert_array_equal(initial_weights(seed),initial_weights(seed))
    def test_tree_probability_mass(self):
        v,L,w,end,_=rollout(self.t,self.p,self.s)
        np.testing.assert_allclose(end['mass'].reshape(32,-1).sum(1),np.ones(32),atol=1e-15)
        self.assertEqual(len(end['h']),256)
    def test_risk_tilts_not_physical_probabilities(self):
        _,L,w,_,_=rollout(self.t,self.p,self.s)
        self.assertGreater(float((w[0]-self.p.tensors()['branch'][L[0]['mode']]).abs().max()),1e-4)
    def test_zero_risk_reduces_tilts_to_physical(self):
        p=make_problem('risk');_,L,w,_,_=rollout(self.t,p,self.s)
        for a,b in zip(L,w):np.testing.assert_array_equal(b,p.tensors()['branch'][a['mode']])
    def test_numpy_tree_matches_policy_cost(self):
        v,L,_,_,_=rollout(self.t,self.p,self.s[:1]);u=[]
        for a in L:u.extend(a['u'].reshape(2,-1,2)[0].detach().numpy())
        actual=evaluate(np.asarray(u).reshape(-1),self.p,build(self.p,self.s[0],0))[0]
        self.assertAlmostEqual(actual,float(v[0]),places=12)
    def test_independent_reference_derivatives(self):
        tree=build(self.p,self.s[0],0);u=np.random.default_rng(3).normal(0,.1,14)
        f,g,H=evaluate(u,self.p,tree)
        for i in (0,3,13):
            e=np.zeros(14);e[i]=1e-5
            fp,gp,_=evaluate(u+e,self.p,tree);fm,gm,_=evaluate(u-e,self.p,tree)
            self.assertAlmostEqual((fp-fm)/2e-5,g[i],places=7)
            np.testing.assert_allclose((gp-gm)/2e-5,H[:,i],atol=1e-7,rtol=1e-7)
    def test_reference_convex_support_at_nonoptimum(self):
        tree=build(self.p,self.s[0],0);u=np.zeros(14);f,g,H=evaluate(u,self.p,tree)
        self.assertGreater(np.linalg.eigvalsh(H).min(),0)
        for seed in range(4):
            v=np.random.default_rng(seed).uniform(-1,1,14);fv=evaluate(v,self.p,tree)[0]
            self.assertGreaterEqual(fv+1e-12,f+g@(v-u))
    def test_reference_bound_and_feasibility(self):
        r=solve(self.p,self.s[0],0)
        self.assertLessEqual(r['lower'],r['upper']+1e-14)
        self.assertLess(r['gap_bound'],1e-5)
        self.assertLessEqual(np.max(np.abs(r['actions'])),self.p.bound)
        self.assertGreater(r['hessian_min'],0)
    def test_convex_bound_contains_other_feasible_policies(self):
        r=solve(self.p,self.s[0],0);v=rollout(self.t,self.p,self.s[:1])[0][0]
        self.assertGreaterEqual(float(v),r['lower']-1e-12)
    def test_actual_adjoint_solve_uses_no_reference(self):
        from unittest.mock import patch
        before=float(objective(self.t,self.p,self.s))
        with patch('reference.solve',side_effect=AssertionError('reference in fit')):
            x,r=fit(self.p,self.s,'nonlinear','adjoint',11,1.5)
        self.assertLess(float(objective(torch.tensor(x),self.p,self.s)),before)
        self.assertGreater(r['counts']['hessians'],0)
    def test_new_states_not_training(self):
        train={a.tobytes() for a in initial()};test={a.tobytes() for a in initial('new')}
        self.assertFalse(train&test)
    def test_single_intervention(self):
        for name,field in (('risk','eta'),('quartic','quartic'),('dynamics','A'),('noise','noise'),('horizon','horizon')):
            p=make_problem(name)
            for key in self.p.__dataclass_fields__:
                self.assertEqual(np.array_equal(getattr(p,key),getattr(self.p,key)),key!=field)
    def test_nonquadratic_readout_has_nonconstant_hessian(self):
        tree=build(self.p,self.s[0],0)
        h1=evaluate(np.zeros(14),self.p,tree)[2];h2=evaluate(np.ones(14)*.2,self.p,tree)[2]
        self.assertGreater(np.max(np.abs(h1-h2)),.01)

if __name__=='__main__':unittest.main(verbosity=2)
