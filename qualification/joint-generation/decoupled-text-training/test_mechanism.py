"""Literal tests for the prospective independently supervised text branch."""
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
        for mode in ('joint','decoupled'):
            for got,want in zip(SplitPolicy(base,mode).forward(x),base.forward(x)):
                np.testing.assert_array_equal(got,want)

    def test_text_learns_but_is_exact_across_image_objectives(self):
        base,x,y,r=self.fixture(); before=base.digest()
        models=[SplitPolicy(base,'decoupled') for _ in range(2)]
        oldp=base.forward(x)[0]
        for model,objective in zip(models,('additive','ndu')):
            for _ in range(5): model.step(x,y,r,objective,1.5,.2,.003)
            model.verify_frozen()
        p0,q0=models[0].forward(x); p1,q1=models[1].forward(x)
        np.testing.assert_array_equal(p0,p1)
        self.assertFalse(np.array_equal(p0,oldp)); self.assertFalse(np.array_equal(q0,q1))
        self.assertLess(-np.log(p0[np.arange(2),y]).mean(),-np.log(oldp[np.arange(2),y]).mean())
        self.assertEqual(base.digest(),before)

    def test_joint_control_exact(self):
        base,x,y,r=self.fixture()
        for objective in ('additive','ndu'):
            model=SplitPolicy(base,'joint'); ref=base.clone()
            p,q=ref.forward(x); dp,dq=p.copy(),q.copy()
            dp[np.arange(2),y]-=1;dq[np.arange(2),y]-=1
            _,gp,gq=joint_value_and_grad(p,q,r,0 if objective=='additive' else 1.5)
            ref.train_step(x,.2*dp/4+gp,.2*dq/4+gq,.003)
            model.step(x,y,r,objective,1.5,.2,.003)
            self.assertEqual(ref.digest(),model.adapted.digest())

    def test_decoupled_one_step_two_exact_reference_pullbacks(self):
        base,x,y,r=self.fixture()
        for objective in ('additive','ndu'):
            model=SplitPolicy(base,'decoupled'); tr=base.clone(); im=base.clone()
            p,q=base.forward(x); dp,dq=p.copy(),q.copy()
            dp[np.arange(2),y]-=1;dq[np.arange(2),y]-=1
            _,_,gq=joint_value_and_grad(p,q,r,0 if objective=='additive' else 1.5)
            tr.train_step(x,dp/4,np.zeros_like(q),.003)
            im.train_step(x,np.zeros_like(p),.2*dq/4+gq,.003)
            model.step(x,y,r,objective,1.5,.2,.003)
            self.assertEqual(model.text.digest(),tr.digest())
            self.assertEqual(model.adapted.digest(),im.digest())

    def test_reject_and_decoder_guard(self):
        base,x,y,r=self.fixture()
        with self.assertRaises(ValueError):SplitPolicy(base,'protected')
        model=SplitPolicy(base,'decoupled')
        with self.assertRaises(ValueError):model.step(x,y,r,'unknown',1.5,.2,.003)
        model.text.params['decoder'][0,0]+=.1
        with self.assertRaises(ValueError):model.verify_frozen()

if __name__=='__main__':unittest.main()
