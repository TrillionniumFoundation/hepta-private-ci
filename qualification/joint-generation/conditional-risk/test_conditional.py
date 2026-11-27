import unittest
import numpy as np
from model import softmax
from utility import joint_value_and_grad, certainty_equivalent
from aligned import all_terms, push_policies
from conditional import conditional_value_and_grad as value_grad


def fixture():
    z=np.array([[.2,-.4,.9],[-.1,.5,.7]])
    w=np.array([[.6,.1,-.8],[.2,-.7,.3]])
    r=np.array([[[.8,.1,-.5],[.2,.7,.4],[-.3,.5,.9]],[[.4,-.2,.9],[.8,.1,-.4],[.2,.5,.3]]])
    return z,w,r


class ConditionalTests(unittest.TestCase):
    def test_centered_logit_derivatives_both_directions_and_small_rho(self):
        z,w,r=fixture()
        for mode in ('text-neutral','image-neutral'):
            for rho in (0,1e-7,1.5):
                _,gp,gq=value_grad(softmax(z),softmax(w),r,rho,mode)
                for a,g,side in ((z,gp,0),(w,gq,1)):
                    for i in np.ndindex(a.shape):
                        up,down=a.copy(),a.copy();up[i]+=1e-5;down[i]-=1e-5
                        args1=(up,w) if side==0 else (z,up)
                        args2=(down,w) if side==0 else (z,down)
                        loss=lambda args:-value_grad(softmax(args[0]),softmax(args[1]),r,rho,mode)[0].mean()
                        self.assertAlmostEqual((loss(args1)-loss(args2))/2e-5,g[i],places=8)

    def test_zero_risk_exact_additive_parity(self):
        z,w,r=fixture();p,q=softmax(z),softmax(w)
        for mode in ('text-neutral','image-neutral'):
            for a,b in zip(value_grad(p,q,r,0,mode),joint_value_and_grad(p,q,r,0)):
                np.testing.assert_array_equal(a,b)

    def test_direction_swap_exact_parity(self):
        z,w,r=fixture();p,q=softmax(z),softmax(w)
        v,a,b=value_grad(p,q,r,1.5,'image-neutral')
        vv,bb,aa=value_grad(q,p,r.transpose(0,2,1),1.5,'text-neutral')
        for x,y in ((v,vv),(a,aa),(b,bb)):np.testing.assert_array_equal(x,y)

    def test_joint_lower_and_additive_upper_bound_not_joint_equivalence(self):
        z,w,r=fixture();p,q=softmax(z),softmax(w)
        joint=joint_value_and_grad(p,q,r,1.5)[0];add=joint_value_and_grad(p,q,r,0)[0]
        for mode in ('text-neutral','image-neutral'):
            value=value_grad(p,q,r,1.5,mode)[0]
            self.assertTrue(np.all(joint<value));self.assertTrue(np.all(value<add))
        expected=np.sum(p*certainty_equivalent(r,np.broadcast_to(q[:,None,:],r.shape),1.5,axis=2),axis=1)
        np.testing.assert_array_equal(value_grad(p,q,r,1.5,'text-neutral')[0],expected)

    def test_deterministic_outer_equals_joint_and_zero_outer_gradient(self):
        z,w,r=fixture();p=np.array([[0.,1.,0.],[1.,0.,0.]]);q=softmax(w)
        actual=value_grad(p,q,r,1.5,'text-neutral');expected=joint_value_and_grad(p,q,r,1.5)
        for a,b in zip(actual,expected):np.testing.assert_allclose(a,b,rtol=0,atol=2e-15)

    def test_constant_reward_and_zero_probability_support(self):
        p=np.array([[0.,1.,0.]]);q=np.array([[.5,0.,.5]])
        for mode in ('text-neutral','image-neutral'):
            v,gp,gq=value_grad(p,q,np.full((1,3,3),.7),1.5,mode)
            np.testing.assert_allclose(v,.7,atol=1e-15)
            np.testing.assert_allclose(gp,0,atol=1e-15);np.testing.assert_allclose(gq,0,atol=1e-15)

    def test_transport_pullback_and_complete_anchor_gradient(self):
        n=2;k=12;z=np.linspace(-.6,.8,n*k).reshape(n,k);w=-.7*z
        ft=np.tile(np.repeat(np.arange(6),2),(n,1));fi=np.tile(np.arange(12)%6,(n,1))
        y=np.array([2,4]);sem=np.arange(12);i,j=np.indices((k,k))
        r=np.stack([.3*(i==yy)+.3*(j==yy)+.3*((i==yy)&(j==yy))-.35*(i!=j) for yy in y])
        pulled=r[np.arange(n)[:,None,None],ft[:,:,None],fi[:,None,:]]
        for mode in ('text-neutral','image-neutral'):
            p,q=softmax(z),softmax(w);v,gp,gq=value_grad(p,q,pulled,1.5,mode)
            a,b=push_policies(p,q,ft,fi)
            np.testing.assert_allclose(v,value_grad(a,b,r,1.5,mode)[0],rtol=0,atol=1e-14)
            terms=all_terms(p,q,r,y,ft,fi,sem,sem,1.5)
            gp+=.2*terms['aligned_anchor'][0];gq+=.2*terms['aligned_anchor'][1]
            def loss(zz,ww):
                pp,qq=softmax(zz),softmax(ww)
                anchor=all_terms(pp,qq,r,y,ft,fi,sem,sem,1.5)['aligned_anchor_value']
                return .2*anchor-value_grad(pp,qq,pulled,1.5,mode)[0].mean()
            for a,g,side in ((z,gp,0),(w,gq,1)):
                for idx in np.ndindex(a.shape):
                    up,down=a.copy(),a.copy();up[idx]+=1e-5;down[idx]-=1e-5
                    diff=loss(up,w)-loss(down,w) if side==0 else loss(z,up)-loss(z,down)
                    self.assertAlmostEqual(diff/2e-5,g[idx],places=8)

    def test_invalid_inputs_reject_and_inputs_unchanged(self):
        z,w,r=fixture();p,q=softmax(z),softmax(w);copies=[x.copy() for x in (p,q,r)]
        for mode in ('text-neutral','image-neutral'):value_grad(p,q,r,1.5,mode)
        for a,b in zip((p,q,r),copies):np.testing.assert_array_equal(a,b)
        for args in ((p,q,r,-1,'text-neutral'),(p,q,r,1,'default'),(p*2,q,r,1,'text-neutral'),(p,q,r[:,:2],1,'text-neutral'),(p,q,r*np.nan,1,'image-neutral')):
            with self.assertRaises(ValueError):value_grad(*args)


if __name__=='__main__':unittest.main()
