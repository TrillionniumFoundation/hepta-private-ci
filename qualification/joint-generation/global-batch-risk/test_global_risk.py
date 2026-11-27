import unittest
import numpy as np
from global_risk import GlobalRiskProfile,MODE,global_rows
from grouped_risk import GroupRiskProfile,MODE as OLD_MODE,aggregate_rows
from test_grouped_training import fixture as oldfixture,softmax
from aligned import all_terms
from utility import certainty_equivalent
MEASUREMENTS={}
def fixture():
    z,w,r,y,ft,fi,ts,_=oldfixture()
    z=np.tile(z,(4,1))+np.sin(np.arange(768)).reshape(64,12)/7
    w=np.tile(w,(4,1))+np.cos(np.arange(768)).reshape(64,12)/9
    r=np.concatenate([r*.7+j*.04 for j in range(4)])
    return z,w,r,np.tile(y,4),np.tile(ft,(4,1)),np.tile(fi,(4,1)),ts

def compute(z,w,r,y,ft,fi,ts,rho=1.5):
    t=all_terms(softmax(z),softmax(w),r,y,ft,fi,ts,ts,1.5)
    row=t['aligned_ndu' if rho else 'aligned_additive']
    return t,global_rows(GlobalRiskProfile(rho,64,MODE),*row)
class GlobalRiskTests(unittest.TestCase):
    def test_flatten_and_two_level_chain(self):
        z,w,r,y,ft,fi,ts=fixture();t,g=compute(z,w,r,y,ft,fi,ts)
        pulled=r[np.arange(64)[:,None,None],ft[:,:,None],fi[:,None,:]]
        joint=softmax(z)[:,:,None]*softmax(w)[:,None,:]
        direct=certainty_equivalent(pulled.reshape(1,-1),joint.reshape(1,-1)/64,1.5,axis=1)
        np.testing.assert_allclose(g[0],direct,rtol=0,atol=3e-15)
        inner=aggregate_rows(GroupRiskProfile(1.5,8,OLD_MODE),*t['aligned_ndu'],np.repeat(np.arange(8),8))
        outer=np.exp(-1.5*inner[0]);outer=8*outer/outer.sum()
        two=-np.log(np.exp(-1.5*inner[0]).mean())/1.5
        np.testing.assert_allclose(g[0],[two],rtol=0,atol=3e-15)
        for gg,ig in zip(g[1:3],inner[1:3]):np.testing.assert_allclose(gg,ig*np.repeat(outer,8)[:,None],rtol=0,atol=3e-15)
        self.assertLess(float(g[0][0]),float(inner[0].mean()))
        self.assertLessEqual(float(inner[0].mean()),float(t['aligned_ndu'][0].mean())+3e-15)
        self.assertLessEqual(float(t['aligned_ndu'][0].mean()),float(t['aligned_additive'][0].mean())+3e-15)
    def test_both_head_utility_and_ordinary_anchor_FD(self):
        z,w,r,y,ft,fi,ts=fixture();t,g=compute(z,w,r,y,ft,fi,ts);errors=[];complete=[]
        for logits,grad,anchor in ((z,g[1],t['aligned_anchor'][0]),(w,g[2],t['aligned_anchor'][1])):
            for row,col in ((0,0),(15,11),(32,3),(63,7)):
                value=logits[row,col];eps=1e-6
                logits[row,col]=value+eps;tp,gp=compute(z,w,r,y,ft,fi,ts)
                logits[row,col]=value-eps;tm,gm=compute(z,w,r,y,ft,fi,ts);logits[row,col]=value
                fd=(-gp[0][0]+gm[0][0])/(2*eps)
                full=(-gp[0][0]+.2*tp['aligned_anchor_value']+gm[0][0]-.2*tm['aligned_anchor_value'])/(2*eps)
                errors.append(float(abs(fd-grad[row,col])));complete.append(float(abs(full-grad[row,col]-.2*anchor[row,col])))
        self.assertLess(max(errors),3e-8);self.assertLess(max(complete),3e-8)
        self.assertGreater(float(np.max(np.abs(.2*t['aligned_anchor'][0]*(g[3][:,None]-1)))),1e-8)
        for grad in g[1:3]:np.testing.assert_allclose(grad.sum(1),0,rtol=0,atol=3e-15)
        MEASUREMENTS.update(utility_FD_coordinates=8,complete_anchor_FD_coordinates=8,max_utility_FD=max(errors),max_complete_FD=max(complete))
    def test_zero_rho_constant_and_permutation(self):
        f=fixture();t,a=compute(*f,rho=0.)
        np.testing.assert_array_equal(a[0],[t['aligned_additive'][0].mean()])
        for got,old in zip(a[1:3],t['aligned_additive'][1:3]):np.testing.assert_array_equal(got,old)
        np.testing.assert_array_equal(a[3],np.ones(64))
        row=t['aligned_ndu'];p=GlobalRiskProfile(1.5,64,MODE)
        c=global_rows(p,np.full(64,.375),row[1],row[2]);np.testing.assert_array_equal(c[3],np.ones(64))
        order=np.arange(63,-1,-1);g=global_rows(p,*row);h=global_rows(p,row[0][order],row[1][order],row[2][order])
        np.testing.assert_allclose(g[0],h[0],rtol=0,atol=3e-15)
        for a,b in zip(g[1:],h[1:]):np.testing.assert_allclose(a[order],b,rtol=0,atol=3e-15)
    def test_identity_refusals_and_immutability(self):
        p=GlobalRiskProfile(1.5,64,MODE);old=GroupRiskProfile(1.5,8,OLD_MODE)
        self.assertNotEqual(p.key,old.key);self.assertEqual(p.key,GlobalRiskProfile(1.5,64,MODE).key)
        v=np.arange(64)/64;d=np.zeros((64,12));before=v.copy();global_rows(p,v,d,d);np.testing.assert_array_equal(v,before)
        for rho,n,mode in ((True,64,MODE),(float('nan'),64,MODE),(2.,64,MODE),(1.5,8,MODE),(1.5,64,OLD_MODE),(1.5,True,MODE)):
            with self.assertRaises(ValueError):GlobalRiskProfile(rho,n,mode)
        with self.assertRaises(ValueError):global_rows(old,v,d,d)
        for values,dt,dq in ((v[:-1],d,d),(v.reshape(8,8),d,d),(v,d[:,:11],d),(np.full(64,np.inf),d,d),(v,np.full_like(d,np.nan),d)):
            with self.assertRaises(ValueError):global_rows(p,values,dt,dq)
