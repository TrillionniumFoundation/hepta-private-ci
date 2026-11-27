"""Literal controls and finite-difference pullbacks for independent encoders."""
import pathlib
import sys
import unittest
ROOT=pathlib.Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT),str(ROOT.parent)]
import numpy as np
from model import JointModel
from mechanism import SplitPolicy
from utility import joint_value_and_grad


class MechanismTests(unittest.TestCase):
    def fixture(self):
        return (JointModel(3,2,4,hidden=4,seed=17),np.array([[.2,.4,.6],[.7,.1,.3]]),
                np.array([0,1]),np.array([[[1.,-.3],[-.3,.1]],[[.1,-.3],[-.3,1.]]]))

    def test_zero_identity(self):
        base,x,_,_=self.fixture()
        for mode in ('joint','isolated'):
            for got,want in zip(SplitPolicy(base,mode).forward(x),base.forward(x)):
                np.testing.assert_array_equal(got,want)

    def test_both_learn_without_mutating_base_or_decoder(self):
        base,x,y,r=self.fixture(); before=base.digest(); initial=base.forward(x)
        for objective in ('additive','ndu'):
            m=SplitPolicy(base,'isolated')
            for _ in range(3):m.step(x,y,r,objective,1.5,.2,.003)
            p,q=m.forward(x); m.verify_frozen()
            self.assertFalse(np.array_equal(p,initial[0]));self.assertFalse(np.array_equal(q,initial[1]))
            self.assertEqual(before,base.digest())

    def test_exact_control_and_separate_reference_updates(self):
        base,x,y,r=self.fixture()
        for objective in ('additive','ndu'):
            p,q=base.forward(x);dp,dq=p.copy(),q.copy()
            dp[np.arange(2),y]-=1;dq[np.arange(2),y]-=1
            _,gp,gq=joint_value_and_grad(p,q,r,0 if objective=='additive' else 1.5)
            dt,di=.2*dp/4+gp,.2*dq/4+gq
            for mode in ('joint','isolated'):
                m=SplitPolicy(base,mode);tr=base.clone();im=base.clone()
                if mode=='joint':im.train_step(x,dt,di,.003)
                else:
                    tr.train_step(x,dt,np.zeros_like(q),.003)
                    im.train_step(x,np.zeros_like(p),di,.003)
                m.step(x,y,r,objective,1.5,.2,.003)
                self.assertEqual(m.text.digest(),tr.digest());self.assertEqual(m.adapted.digest(),im.digest())

    def test_finite_difference_both_encoders_original_objective(self):
        base,x,y,r=self.fixture();m=SplitPolicy(base,'isolated');p,q=m.forward(x)
        dp,dq=p.copy(),q.copy();dp[np.arange(2),y]-=1;dq[np.arange(2),y]-=1
        _,gp,gq=joint_value_and_grad(p,q,r,1.5)
        grads=[m.text.gradients(x,.2*dp/4+gp,np.zeros_like(q)),m.adapted.gradients(x,np.zeros_like(p),.2*dq/4+gq)]
        def loss():
            pp,qq=m.forward(x);v=joint_value_and_grad(pp,qq,r,1.5)[0]
            ce=-np.mean(np.log(pp[np.arange(2),y])+np.log(qq[np.arange(2),y]))/2
            return -v.mean()+.2*ce
        for branch,g in zip((m.text,m.adapted),grads):
            value=branch.params['encoder'][0,1];eps=1e-6
            branch.params['encoder'][0,1]=value+eps;plus=loss()
            branch.params['encoder'][0,1]=value-eps;minus=loss()
            branch.params['encoder'][0,1]=value
            self.assertAlmostEqual((plus-minus)/(2*eps),g['encoder'][0,1],places=8)

    def test_reject_and_decoder_guard(self):
        base,x,y,r=self.fixture()
        with self.assertRaises(ValueError):SplitPolicy(base,'decoupled')
        m=SplitPolicy(base,'isolated')
        with self.assertRaises(ValueError):m.step(x,y,r,'unknown',1.5,.2,.003)
        m.text.params['decoder'][0,0]+=.1
        with self.assertRaises(ValueError):m.verify_frozen()

if __name__=='__main__':unittest.main()
