import unittest
import numpy as np
from exponential_score import ScoreProfile,MODE,score_rows
from global_risk import GlobalRiskProfile,MODE as GLOBAL_MODE,global_rows
from test_global_risk import fixture,softmax
from aligned import all_terms
MEASUREMENTS={}
def compute(z,w,r,y,ft,fi,ts,rho=1.5):
    t=all_terms(softmax(z),softmax(w),r,y,ft,fi,ts,ts,1.5)
    row=t['aligned_ndu' if rho else 'aligned_additive']
    return t,score_rows(ScoreProfile(rho,64,MODE),*row)
class ScoreTests(unittest.TestCase):
    def test_direct_transformed_reward_and_global_chain(self):
        z,w,r,y,ft,fi,ts=fixture();t,s=compute(z,w,r,y,ft,fi,ts)
        self.assertGreaterEqual(float(r.min()),-.35);self.assertLessEqual(float(r.max()),1.)
        pulled=r[np.arange(64)[:,None,None],ft[:,:,None],fi[:,None,:]]
        transformed=-np.expm1(-1.5*pulled)/1.5
        p,q=softmax(z),softmax(w);joint=p[:,:,None]*q[:,None,:]
        direct=(joint*transformed).sum((1,2))
        np.testing.assert_allclose(s[0],[direct.mean()],rtol=0,atol=3e-15)
        # Direct derivative of negative mean expected transformed reward, unbounded
        # by the original RGB lower reward bound: never route through bounded wrapper.
        dp=p*(direct[:,None]-(q[:,None,:]*transformed).sum(2))/64
        dq=q*(direct[:,None]-(p[:,:,None]*transformed).sum(1))/64
        np.testing.assert_allclose(s[1],dp,rtol=0,atol=3e-15);np.testing.assert_allclose(s[2],dq,rtol=0,atol=3e-15)
        g=global_rows(GlobalRiskProfile(1.5,64,GLOBAL_MODE),*t['aligned_ndu']);Z=np.exp(-1.5*t['aligned_ndu'][0]).mean()
        for score,global_grad in zip(s[1:3],g[1:3]):np.testing.assert_allclose(score,Z*global_grad,rtol=0,atol=3e-15)
        self.assertLess(float(-np.expm1(1.5*.35)/1.5),-.35)
    def test_full_anchor_and_utility_bothhead_FD(self):
        z,w,r,y,ft,fi,ts=fixture();t,s=compute(z,w,r,y,ft,fi,ts);errors=[];fullerrors=[]
        for logits,grad,anchor in ((z,s[1],t['aligned_anchor'][0]),(w,s[2],t['aligned_anchor'][1])):
            for row,col in ((0,0),(15,11),(32,3),(63,7)):
                old=logits[row,col];eps=1e-6
                logits[row,col]=old+eps;tp,sp=compute(z,w,r,y,ft,fi,ts)
                logits[row,col]=old-eps;tm,sm=compute(z,w,r,y,ft,fi,ts);logits[row,col]=old
                fd=(-sp[0][0]+sm[0][0])/(2*eps)
                full=(-sp[0][0]+.2*tp['aligned_anchor_value']+sm[0][0]-.2*tm['aligned_anchor_value'])/(2*eps)
                errors.append(float(abs(fd-grad[row,col])));fullerrors.append(float(abs(full-grad[row,col]-.2*anchor[row,col])))
        self.assertLess(max(errors),3e-8);self.assertLess(max(fullerrors),3e-8)
        self.assertGreater(float(np.max(np.abs(.2*t['aligned_anchor'][0]*(s[3][:,None]-1)))),1e-8)
        MEASUREMENTS.update(utility_FD_coordinates=8,fullanchor_FD_coordinates=8,max_utility_FD=max(errors),max_fullanchor_FD=max(fullerrors))
    def test_rhozero_constant_and_translation(self):
        f=fixture();t,s=compute(*f,rho=0)
        np.testing.assert_array_equal(s[0],[t['aligned_additive'][0].mean()])
        for got,old in zip(s[1:3],t['aligned_additive'][1:3]):np.testing.assert_array_equal(got,old)
        np.testing.assert_array_equal(s[3],np.ones(64))
        t,s=compute(*f);row=t['aligned_ndu'];profile=ScoreProfile(1.5,64,MODE)
        constant=score_rows(profile,np.full(64,.25),row[1],row[2]);np.testing.assert_array_equal(constant[3],np.full(64,np.exp(-1.5*.25)))
        self.assertFalse(np.array_equal(constant[3],np.ones(64)))
        shifted_fixture=list(f);shifted_fixture[2]=f[2]+.1
        shifted_terms,shifted_score=compute(*shifted_fixture)
        for original,shifted in zip(t['aligned_anchor'],shifted_terms['aligned_anchor']):np.testing.assert_array_equal(original,shifted)
        self.assertEqual(t['aligned_anchor_value'],shifted_terms['aligned_anchor_value'])
        shift=.1;translated=score_rows(profile,row[0]+shift,row[1],row[2]);scale=np.exp(-1.5*shift)
        for direct,translated_value in zip(shifted_score,translated):np.testing.assert_allclose(direct,translated_value,rtol=0,atol=3e-15)
        for original,shifted in zip(s[1:3],translated[1:3]):np.testing.assert_allclose(shifted,scale*original,rtol=0,atol=3e-15)
        np.testing.assert_allclose(translated[0],-np.expm1(-1.5*shift)/1.5+scale*s[0],rtol=0,atol=3e-15)
    def test_identity_refusal_and_immutability(self):
        p=ScoreProfile(1.5,64,MODE);old=GlobalRiskProfile(1.5,64,GLOBAL_MODE);self.assertNotEqual(p.key,old.key)
        c=np.arange(64)/64;d=np.zeros((64,12));before=c.copy();score_rows(p,c,d,d);np.testing.assert_array_equal(c,before)
        with self.assertRaises(ValueError):score_rows(old,c,d,d)
        with self.assertRaises(ValueError):score_rows(ScoreProfile(0.,64,MODE),np.full(64,1e308),d,d)
        for rho,n,mode in ((True,64,MODE),(float('inf'),64,MODE),(2.,64,MODE),(1.5,63,MODE),(1.5,64,GLOBAL_MODE)):
            with self.assertRaises(ValueError):ScoreProfile(rho,n,mode)
        for v,a,b in ((c[:-1],d,d),(np.tile(c,2),np.tile(d,(2,1)),np.tile(d,(2,1))),(c,d[:,:11],d),(np.full(64,np.nan),d,d),(c,np.full_like(d,np.inf),d),(np.full(64,-1e308),d,d)):
            with self.assertRaises(ValueError):score_rows(p,v,a,b)
