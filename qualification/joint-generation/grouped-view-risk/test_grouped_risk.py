import unittest
import numpy as np
from utility import joint_value_and_grad,certainty_equivalent
from grouped_risk import GroupRiskProfile,MODE,aggregate_rows,joint_group_value_and_grad
MEASUREMENTS={}
def softmax(z):
    a=np.exp(z-z.max(1,keepdims=True));return a/a.sum(1,keepdims=True)
def fixture():
    z=np.arange(48,dtype=float).reshape(4,12)/31;w=np.sin(np.arange(48,dtype=float)).reshape(4,12)/3
    r=((np.arange(4*144).reshape(4,12,12)%29)/28)*1.3-.3
    return z,w,r,np.array([0,0,1,1])
class GroupRiskTests(unittest.TestCase):
    def test_finite_difference_both_heads(self):
        z,w,r,groups=fixture();profile=GroupRiskProfile(1.5,2,MODE)
        ce,dp,dq,_=joint_group_value_and_grad(profile,softmax(z),softmax(w),r,groups);errors=[]
        for logits,gradient in ((z,dp),(w,dq)):
            for row,col in ((0,0),(1,11),(2,3),(3,7)):
                value=logits[row,col];eps=1e-6
                logits[row,col]=value+eps;plus=-joint_group_value_and_grad(profile,softmax(z),softmax(w),r,groups)[0].mean()
                logits[row,col]=value-eps;minus=-joint_group_value_and_grad(profile,softmax(z),softmax(w),r,groups)[0].mean();logits[row,col]=value
                error=abs((plus-minus)/(2*eps)-gradient[row,col]);errors.append(float(error));self.assertLess(error,2e-8)
        MEASUREMENTS['finite_difference_coordinates']=len(errors);MEASUREMENTS['max_FD_error']=max(errors)
    def test_direct_flattened_view_output_law_and_chain(self):
        z,w,r,groups=fixture();p,q=softmax(z),softmax(w);profile=GroupRiskProfile(1.5,2,MODE)
        original_r=r.copy();ce,dp,dq,scale=joint_group_value_and_grad(profile,p,q,r,groups);np.testing.assert_array_equal(r,original_r)
        joint=p[:,:,None]*q[:,None,:];prob=joint.reshape(2,-1)/2
        flat=certainty_equivalent(r.reshape(2,-1),prob,1.5,axis=1);np.testing.assert_allclose(ce,flat,rtol=0,atol=2e-15)
        logjoint=np.log(joint).reshape(2,2,12,12)-1.5*r.reshape(2,2,12,12);tilt=np.exp(logjoint-logjoint.max((1,2,3),keepdims=True));tilt/=tilt.sum((1,2,3),keepdims=True)
        view=tilt.sum((2,3));directp=(tilt.sum(3)-view[:,:,None]*p.reshape(2,2,12))/(1.5*2);directq=(tilt.sum(2)-view[:,:,None]*q.reshape(2,2,12))/(1.5*2)
        np.testing.assert_allclose(dp,directp.reshape(4,12),rtol=0,atol=2e-15);np.testing.assert_allclose(dq,directq.reshape(4,12),rtol=0,atol=2e-15)
        rowce,rp,rq=joint_value_and_grad(p,q,r,1.5);weight=np.exp(-1.5*rowce.reshape(2,2));weight=2*weight/weight.sum(1,keepdims=True)
        np.testing.assert_allclose(scale,weight.ravel(),rtol=0,atol=1e-15);np.testing.assert_allclose(dp,rp*weight.reshape(4,1),rtol=0,atol=1e-15)
    def test_rho_zero_and_K1_exact_gradient_parity(self):
        z,w,r,groups=fixture();p,q=softmax(z),softmax(w)
        for rho,k,labels in ((0.,2,groups),(1.5,1,np.arange(4)),(0.,1,np.arange(4))):
            old=joint_value_and_grad(p,q,r,rho);new=joint_group_value_and_grad(GroupRiskProfile(rho,k,MODE),p,q,r,labels)
            np.testing.assert_array_equal(new[1],old[1]);np.testing.assert_array_equal(new[2],old[2]);np.testing.assert_array_equal(new[3],np.ones(4))
            np.testing.assert_array_equal(new[0],old[0].reshape(4//k,k).mean(1))
    def test_equal_rows_constant_reward_zero_sum(self):
        z,w,r,groups=fixture();p,q=softmax(z),softmax(w);p=np.repeat(p[::2],2,axis=0);q=np.repeat(q[::2],2,axis=0);r=np.repeat(r[::2],2,axis=0)
        old=joint_value_and_grad(p,q,r,1.5);new=joint_group_value_and_grad(GroupRiskProfile(1.5,2,MODE),p,q,r,groups)
        np.testing.assert_allclose(new[0],old[0][::2],rtol=0,atol=2e-15);np.testing.assert_array_equal(new[1],old[1]);np.testing.assert_array_equal(new[2],old[2])
        for grad in new[1:3]:np.testing.assert_allclose(grad.sum(1),0,rtol=0,atol=2e-15)
        constant=np.full((4,12,12),.375);v=joint_group_value_and_grad(GroupRiskProfile(1.5,2,MODE),p,q,constant,groups)
        np.testing.assert_allclose(v[0],.375,rtol=0,atol=2e-15)
        for grad in v[1:3]:np.testing.assert_allclose(grad,0,rtol=0,atol=2e-15)
    def test_group_and_view_permutation_equivariance(self):
        z,w,r,groups=fixture();p,q=softmax(z),softmax(w);profile=GroupRiskProfile(1.5,2,MODE);old=joint_group_value_and_grad(profile,p,q,r,groups)
        order=np.array([3,2,1,0]);new=joint_group_value_and_grad(profile,p[order],q[order],r[order],groups)
        np.testing.assert_allclose(new[0],old[0][::-1],rtol=0,atol=2e-15)
        for index in (1,2,3):np.testing.assert_allclose(new[index],old[index][order],rtol=0,atol=2e-15)
    def test_bad_groups_mode_nonfinite_and_identity(self):
        z,w,r,groups=fixture();p,q=softmax(z),softmax(w);profile=GroupRiskProfile(1.5,2,MODE)
        self.assertNotEqual(profile.key,GroupRiskProfile(1.5,1,MODE).key);self.assertNotEqual(profile.key,GroupRiskProfile(0.,2,MODE).key)
        for labels in ([0,0,0,1],[0,1,0,1],[1,1,2,2],[0.,0.,1.,1.],[True,True,False,False],[]):
            with self.assertRaises(ValueError):joint_group_value_and_grad(profile,p,q,r,labels)
        for rho,k,mode in ((1.5,2,'old-row'),(float('nan'),2,MODE),(1.5,True,MODE),(1.5,0,MODE),(.5,2,MODE)):
            with self.assertRaises(ValueError):GroupRiskProfile(rho,k,mode)
        for badp,badr in ((p*np.nan,r),(p,r*np.inf),(p,np.full_like(r,1.1))):
            with self.assertRaises(ValueError):joint_group_value_and_grad(profile,badp,q,badr,groups)
        with self.assertRaises(ValueError):joint_group_value_and_grad(profile,p[:0],q[:0],r[:0],[])
        with self.assertRaises(ValueError):aggregate_rows(profile,np.full(4,np.nan),p,q,groups)
        with self.assertRaises(ValueError):joint_group_value_and_grad(None,p,q,r,groups)
