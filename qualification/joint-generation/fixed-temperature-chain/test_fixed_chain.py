import unittest,json
import numpy as np
from test_normalized import fixture,softmax,profile as normalized_profile,SHA
from control import Command
from calibration import TemperatureProfile,MODE as TEMP_MODE,apply_batch
from normalized import value_and_grad as old_gradient,MODE as OLD_MODE,NumericalDomainError
from aligned import all_terms
from utility import certainty_equivalent
from fixed_chain import FixedTemperatureLossProfile,MODE,value_and_grad,_law
MEASUREMENTS={}
def lossprofile(base,taus=(1.,1.)):return FixedTemperatureLossProfile(TemperatureProfile(base,*taus,TEMP_MODE),MODE)
def call(pr,p,q,r,c,rho,**extra):return value_and_grad(pr,p,q,r,c,rho,observed_model_sha256=SHA,**extra)
def signature(pr,p,q,c):
    v=_law(pr,p,q,c,SHA);active=~(np.all(v[2]==v[2][:,:1],1)&np.all(v[3]==v[3][:,:1],1));return np.sign(v[7][active]-v[8][active])
class FixedChainTests(unittest.TestCase):
    def test_actual_calibrated_CDF_values_and_tau1_gradient_parity(self):
        base,c,z,w,r,y,ft,fi,ts,ims=fixture();p,q=softmax(z),softmax(w);maximum=0.
        for taus in ((1.,1.),(.5,2.),(.125,8.),(8.,.125)):
            pr=lossprofile(base,taus)
            for rho in (0.,1.5):
                v,gp,gq,d=call(pr,p,q,r,c,rho);law=apply_batch(pr.temperature,p,q,c,observed_model_sha256=SHA);table=law['joint']/law['cdf_total'][:,None,None]
                actual=certainty_equivalent(r.reshape(4,-1),table.reshape(4,-1),rho,axis=1);maximum=max(maximum,float(np.max(np.abs(v-actual))));np.testing.assert_allclose(v,actual,rtol=0,atol=1e-12)
                if taus==(1.,1.):
                    old=old_gradient(p,q,r,ft,fi,ts,ims,rho,mode=OLD_MODE)
                    for a,b in zip((v,gp,gq),old[:3]):np.testing.assert_allclose(a,b,rtol=0,atol=1e-12)
                for grad in (gp,gq):np.testing.assert_allclose(grad.sum(1),0,rtol=0,atol=1e-12)
        MEASUREMENTS['maximum_actual_CDF_value_error']=maximum
    def test_both_heads_full_anchor_and_utility_FD_stable_branches(self):
        base,c,z,w,r,y,ft,fi,ts,ims=fixture();maximum=0.;count=0
        for taus in ((1.,1.),(.5,2.),(.125,8.),(8.,.125)):
            pr=lossprofile(base,taus)
            for rho in (0.,1.5):
                p,q=softmax(z),softmax(w);v,gp,gq,_=call(pr,p,q,r,c,rho);anchor=all_terms(p,q,r,y,ft,fi,ts,ims,1.5);branch=signature(pr,p,q,c)
                for logits,grad,ag in ((z,gp,anchor['aligned_anchor'][0]),(w,gq,anchor['aligned_anchor'][1])):
                    for row,col in ((0,0),(1,5),(2,9),(3,4)):
                        value=logits[row,col];eps=1e-6;values=[]
                        for sign in (1,-1):
                            logits[row,col]=value+sign*eps;pp,qq=softmax(z),softmax(w);np.testing.assert_array_equal(signature(pr,pp,qq,c),branch)
                            vv=call(pr,pp,qq,r,c,rho)[0];av=all_terms(pp,qq,r,y,ft,fi,ts,ims,1.5)['aligned_anchor_value'];values.append((-vv.mean(),-vv.mean()+.2*av))
                        logits[row,col]=value
                        for index,target in ((0,grad[row,col]),(1,grad[row,col]+.2*ag[row,col])):
                            error=abs((values[0][index]-values[1][index])/(2*eps)-target);maximum=max(maximum,float(error));self.assertLess(error,1e-7);count+=1
        MEASUREMENTS['finite_difference_checks']=count;MEASUREMENTS['maximum_FD_error']=maximum
    def test_fixed_support_constants_singleconstant_and_mean_normalization(self):
        base=normalized_profile();pr=lossprofile(base,(.5,2.));p=np.arange(1,13,dtype=float)[None,:];p/=p.sum();q=np.arange(12,0,-1,dtype=float)[None,:]**2;q/=q.sum();r=np.eye(12)[None,:,:];ident=np.arange(12)[None,:];zero=np.zeros((1,12),dtype=int);one=np.ones((1,12),dtype=int)
        for ft,fi in ((zero,zero),(zero,one)):
            v,gp,gq,d=call(pr,p,q,r,None,1.5,fixed_maps=(ft,fi));self.assertEqual(d['constant_composition_rows'],1);np.testing.assert_array_equal(gp,0);np.testing.assert_array_equal(gq,0);self.assertEqual(v[0],r[0,ft[0,0],fi[0,0]])
        v,gp,gq,d=call(pr,p,q,r,None,1.5,fixed_maps=(zero,ident));self.assertEqual(d['smooth_rows'],1);np.testing.assert_allclose(gp,0,atol=1e-12,rtol=0);self.assertGreater(float(np.max(np.abs(gq))),1e-8)
        commands=(Command(1,1,0),);a=call(pr,p,q,r,commands,1.5);b=call(pr,np.repeat(p,2,0),np.repeat(q,2,0),np.repeat(r,2,0),commands*2,1.5)
        np.testing.assert_allclose(b[0],np.repeat(a[0],2),rtol=0,atol=1e-12)
        for j in (1,2):np.testing.assert_allclose(b[j],np.repeat(a[j]/2,2,0),rtol=0,atol=1e-12)
    def test_transformed_positive_tie_and_residual_floor_refusal(self):
        base=normalized_profile();p=np.full((1,12),1/12);r=np.eye(12)[None,:,:];c=(Command(0,0,0),)
        with self.assertRaisesRegex(NumericalDomainError,'positive exact min tie'):call(lossprofile(base,(.125,8.)),p,p,r,c,1.5)
        sharp_p=np.full((1,12),.01/11);sharp_p[0,0]=.99;sharp_q=np.full((1,12),.02/11);sharp_q[0,0]=.98
        with self.assertRaisesRegex(NumericalDomainError,'positive exact min tie|nonconstant residual'):
            call(lossprofile(base,(8.,8.)),sharp_p,sharp_q,r,c,1.5)
        p=np.full((1,12),1/16);p[0,0]+=1/4
        for power in (20,50):
            residual=2.**-power;parts=np.asarray([residual/2,residual/4,residual/8,residual/16,residual/32,residual/32]);q=p.copy();q[0,::2]+=parts;q[0,1::2]-=parts
            if power==50:
                with self.assertRaises(NumericalDomainError):call(lossprofile(base),p,q,r,c,1.5)
            else:self.assertTrue(np.isfinite(call(lossprofile(base),p,q,r,c,1.5)[1]).all())
    def test_swap_translation_and_input_immutability(self):
        base,c,z,w,r,y,ft,fi,ts,ims=fixture();p,q=softmax(z),softmax(w);pr=lossprofile(base,(.5,2.));before=(p.copy(),q.copy(),r.copy());v,gp,gq,_=call(pr,p,q,r,c,1.5)
        other=lossprofile(normalized_profile(tuple(map(int,ims)),tuple(map(int,ts))),(2.,.5));sw=call(other,q,p,r.transpose(0,2,1),c,1.5)
        for a,b in ((v,sw[0]),(gp,sw[2]),(gq,sw[1])):np.testing.assert_allclose(a,b,rtol=0,atol=1e-12)
        shifted=call(pr,p,q,r+.01,c,1.5);np.testing.assert_allclose(shifted[0],v+.01,rtol=0,atol=1e-12)
        for a,b in zip(shifted[1:3],(gp,gq)):np.testing.assert_allclose(a,b,rtol=0,atol=1e-12)
        logitshift=call(pr,softmax(z+3.25),softmax(w-2.5),r,c,1.5)
        for a,b in zip(logitshift[:3],(v,gp,gq)):np.testing.assert_allclose(a,b,rtol=0,atol=1e-12)
        for a,b in zip((p,q,r),before):np.testing.assert_array_equal(a,b)
    def test_negative_leading_text_incentive_survives_temperature(self):
        base=normalized_profile();c=(Command(1,1,0),);p=np.asarray([[.8/6 if i%2==0 else .2/6 for i in range(12)]]);q=np.asarray([[.6/6 if i%2==0 else .4/6 for i in range(12)]]);ts=np.arange(12);ct=ts[:,None]==0;ci=ts[None,:]==0;r=(.3*ct+.3*ci+.3*(ct&ci)-.35*(ts[:,None]!=ts[None,:]))[None,:,:];direction=np.asarray([1. if i%2==0 else -1. for i in range(12)])
        for taus in ((1.,1.),(2.,.5)):
            for rho in (0.,1.5):
                # Negative CE derivative means POSITIVE minimized-loss derivative.
                v,gp,gq,_=call(lossprofile(base,taus),p,q,r,c,rho);self.assertGreater(float(np.dot(gp[0],direction)),0.)
    def test_profile_roundtrip_and_invalid_mode_tau_reward_support(self):
        base,c,z,w,r,y,ft,fi,ts,ims=fixture();pr=lossprofile(base);p,q=softmax(z),softmax(w)
        loaded=FixedTemperatureLossProfile.loads(pr.dumps(),expected_model_sha256=SHA,expected_mode=MODE);self.assertEqual(loaded.key,pr.key);self.assertNotEqual(pr.key,pr.temperature.key);self.assertNotEqual(pr.key,lossprofile(base,(.5,2.)).key)
        for payload,sha,mode in ((pr.temperature.dumps(),SHA,MODE),(pr.dumps(),'b'*64,MODE),(pr.dumps(),SHA,OLD_MODE)):
            with self.assertRaises(ValueError):FixedTemperatureLossProfile.loads(payload,expected_model_sha256=sha,expected_mode=mode)
        for tau in (0.,.124,8.001,float('nan')):
            with self.assertRaises(ValueError):lossprofile(base,(tau,1.))
        with self.assertRaises(ValueError):FixedTemperatureLossProfile(pr.temperature,OLD_MODE)
        for pp,rr in ((p*np.nan,r),(p,np.full_like(r,1.1))):
            with self.assertRaises(ValueError):call(pr,pp,q,rr,c,1.5)
        zero=p.copy();zero[:,0]=0;zero/=zero.sum(1,keepdims=True)
        with self.assertRaises(NumericalDomainError):call(pr,zero,q,r,c,1.5)
        with self.assertRaises(ValueError):call(pr,p,q,r,c,.5)
        with self.assertRaises(ValueError):call(pr,p,q,r,None,1.5,fixed_maps=(np.zeros((4,11),dtype=int),fi))
        doc=json.loads(pr.dumps());doc['loss']['precision']['mantissa_bits']+=1
        with self.assertRaises(ValueError):FixedTemperatureLossProfile.loads(json.dumps(doc),expected_model_sha256=SHA,expected_mode=MODE)
