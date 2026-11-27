import unittest,itertools,math
import numpy as np
from control import Command,ControlProfile,MODE
from transport import TransportProfile,TRANSPORT_MODE
from coupling import CouplingProfile,COUPLING_MODE
from normalized import apply_batch,NormalizedCouplingProfile,MODE as NEW_MODE,SCHEMA as NEW_SCHEMA,precision,_law
from reference import rational_row,extended_row
from coupled_gradient import coupled_value_and_grad as old_derivative,TRAINING_MODE as OLD_MODE
from aligned import all_terms,push_policies
from utility import certainty_equivalent
from normalized import value_and_grad as derivative,MODE as TRAINING_MODE,NumericalDomainError,RESIDUAL_FLOOR,RELATIVE_BALANCE_TOL

SHA='a'*64
MEASUREMENTS={}
def softmax(z):
    e=np.exp(z-z.max(1,keepdims=True));return e/e.sum(1,keepdims=True)

def profile(ts=tuple(range(12)),ims=tuple(range(12))):
    return NormalizedCouplingProfile(CouplingProfile(TransportProfile(ControlProfile(SHA,ts,ims,MODE),TRANSPORT_MODE),COUPLING_MODE),NEW_MODE)

def fixture():
    ts=np.asarray([(i+3)%12 for i in range(12)]);ims=np.asarray([(i+7)%12 for i in range(12)])
    pr=profile(tuple(map(int,ts)),tuple(map(int,ims)))
    commands=(Command(0,0,0),Command(2,0,0),Command(0,1,2),Command(3,2,1))
    ft=np.asarray([pr.transport.destinations(ts,c) for c in commands]);fi=np.asarray([pr.transport.destinations(ims,c) for c in commands])
    z=np.stack([np.log(np.roll(np.arange(1,13,dtype=float),i)) for i in range(4)])
    w=np.stack([np.log(np.roll(np.arange(12,0,-1,dtype=float)**2,3*i+1)) for i in range(4)])
    y=np.asarray([1,4,9,10]);r=[]
    for target in y:
        ct=ts[:,None]==target;ci=ims[None,:]==target
        r.append(.3*ct+.3*ci+.3*(ct&ci)-.35*(ts[:,None]!=ims[None,:])+.04+.005*ims[None,:]/11)
    return pr,commands,z,w,np.asarray(r),y,ft,fi,ts,ims

def actual(pr,p,q,commands,reward,rho):
    law=apply_batch(pr,p,q,commands,observed_model_sha256=SHA)
    joint=law['joint']/law['cdf_total'][:,None,None]
    return certainty_equivalent(reward.reshape(len(p),-1),joint.reshape(len(p),-1),rho,axis=1)

def call(p,q,r,ft,fi,ts,ims,rho):return derivative(p,q,r,ft,fi,ts,ims,rho,mode=TRAINING_MODE)

class GradientTests(unittest.TestCase):
    def test_actual_normalized_service_value_both_risks(self):
        pr,c,z,w,r,y,ft,fi,ts,ims=fixture();p,q=softmax(z),softmax(w)
        for rho in (0.,1.5):
            v,gp,gq,d=call(p,q,r,ft,fi,ts,ims,rho)
            reference=actual(pr,p,q,c,r,rho)
            MEASUREMENTS[f'value_rho{rho}_max_abs']=float(np.max(np.abs(v-reference)))
            np.testing.assert_allclose(v,reference,rtol=0,atol=1e-13)
            self.assertEqual(d['constant_composition_rows'],1);self.assertEqual(d['smooth_rows'],3)

    def test_complete_anchor_objective_raw_logit_centered_differences(self):
        pr,c,z,w,r,y,ft,fi,ts,ims=fixture();p,q=softmax(z),softmax(w)
        constant=np.all(ft==ft[:,:1],1)&np.all(fi==fi[:,:1],1)
        def signature(pp,qq):
            law=_law(pp,qq,ft,fi,ts,ims);a,b=law[5],law[6]
            return np.sign(a[~constant]-b[~constant])
        original_signature=signature(p,q)
        for rho in (0.,1.5):
            _,gp,gq,_=call(p,q,r,ft,fi,ts,ims,rho)
            anchor=all_terms(p,q,r,y,ft,fi,ts,ims,1.5)['aligned_anchor']
            gp=gp+.2*anchor[0];gq=gq+.2*anchor[1]
            def loss(zz,ww):
                pp,qq=softmax(zz),softmax(ww)
                np.testing.assert_array_equal(signature(pp,qq),original_signature)
                av=all_terms(pp,qq,r,y,ft,fi,ts,ims,1.5)['aligned_anchor_value']
                return .2*av-actual(pr,pp,qq,c,r,rho).mean()
            for values,g,side in ((z,gp,0),(w,gq,1)):
                numeric=np.empty_like(values)
                for idx in np.ndindex(values.shape):
                    plus,minus=values.copy(),values.copy();plus[idx]+=1e-6;minus[idx]-=1e-6
                    numeric[idx]=((loss(plus,w)-loss(minus,w)) if side==0 else (loss(z,plus)-loss(z,minus)))/2e-6
                MEASUREMENTS[f'full_gradient_rho{rho}_head{side}_max_abs']=float(np.max(np.abs(g-numeric)))
                np.testing.assert_allclose(g,numeric,rtol=1e-6,atol=1e-7)

    def test_structural_constants_and_one_constant_map(self):
        pr,c,z,w,r,y,ft,fi,ts,ims=fixture();p,q=softmax(z[:1]),softmax(w[:1]);r=r[:1]
        for left,right in ((0,0),(0,1)):
            f=np.full((1,12),left);g=np.full((1,12),right)
            for rho in (0.,1.5):
                v,gp,gq,d=call(p,q,r,f,g,ts,ims,rho)
                np.testing.assert_array_equal(gp,np.zeros_like(gp));np.testing.assert_array_equal(gq,np.zeros_like(gq))
                self.assertEqual(v[0],r[0,left,right]);self.assertEqual(d['constant_composition_rows'],1)
        f=np.zeros((1,12),dtype=int);g=np.arange(12)[None,:]
        _,gp,gq,_=call(p,q,r,f,g,ts,ims,1.5)
        np.testing.assert_allclose(gp,0,rtol=0,atol=1e-14);self.assertGreater(np.max(np.abs(gq)),1e-5)

    def test_positive_ties_reject_and_have_unequal_one_sided_derivatives(self):
        base=np.full((1,12),1/16);base[0,0]+=1/4;ident=np.arange(12)[None,:];sem=np.arange(12)
        reward=np.eye(12)[None,:,:];pr=profile();commands=(Command(0,0,0),)
        for q in (base.copy(),base.copy()+np.array([[0,-1/32,1/32]+[0]*9])):
            with self.assertRaises(NumericalDomainError):call(base,q,reward,ident,ident,sem,sem,0)
            h=1e-6;plus=base.copy();minus=base.copy();plus[0,0]+=h;plus[0,3]-=h;minus[0,0]-=h;minus[0,3]+=h
            v=actual(pr,base,q,commands,reward,0)[0]
            right=(actual(pr,plus,q,commands,reward,0)[0]-v)/h
            left=(v-actual(pr,minus,q,commands,reward,0)[0])/h
            MEASUREMENTS.setdefault('tie_one_sided_derivatives',[]).append({'left':float(left),'right':float(right)})
            self.assertAlmostEqual(left,1.,places=7);self.assertAlmostEqual(right,-1.,places=7)

    def test_dyadic_small_residuals_and_fixed_floor_refusal(self):
        p=np.full((1,12),1/16);p[0,0]+=1/4;ident=np.arange(12)[None,:];sem=np.arange(12);reward=np.eye(12)[None,:,:]
        for power in (10,20,40,50):
            r=2.**-power;parts=np.asarray([r/2,r/4,r/8,r/16,r/32,r/32]);q=p.copy();q[0,::2]+=parts;q[0,1::2]-=parts
            if power==50:
                self.assertLess(r,RESIDUAL_FLOOR)
                with self.assertRaises(NumericalDomainError):call(p,q,reward,ident,ident,sem,sem,1.5)
                continue
            for rho in (0.,1.5):
                values,gp,gq,d=call(p,q,reward,ident,ident,sem,sem,rho)
                self.assertEqual(d['minimum_active_residual'],r);self.assertEqual(d['maximum_relative_balance_error'],0)
                maximum=float(max(np.max(np.abs(gp)),np.max(np.abs(gq))))
                MEASUREMENTS.setdefault('dyadic_accepted',[]).append({'rho':rho,'residual':r,'maximum_absolute_gradient':maximum})
                self.assertTrue(np.isfinite(values).all());self.assertLess(maximum,10)

    def test_explicit_normalization_differs_from_unchanged_old_mode(self):
        p=np.full((1,12),1/16);p[0,0]+=1/4;r=2.**-20;parts=np.asarray([r/2,r/4,r/8,r/16,r/32,r/32])
        q=p.copy();q[0,::2]+=parts;q[0,1::2]-=parts;q[0,0]+=2.**-40
        args=(p,q,np.eye(12)[None,:,:],np.arange(12)[None,:],np.arange(12)[None,:],np.arange(12),np.arange(12),1.5)
        with self.assertRaisesRegex(NumericalDomainError,'relative residual'):old_derivative(*args,mode=OLD_MODE)
        v,gp,gq,d=call(*args)
        exact=rational_row(p[0],q[0],args[2][0],args[3][0],args[4][0],args[5],args[6],1.5,mode='simplex')
        self.assertTrue(exact['admitted'])
        for x,y in ((gp[0],exact['gradient_p']),(gq[0],exact['gradient_q'])):np.testing.assert_allclose(x,y,rtol=0,atol=1e-12)
        self.assertLessEqual(d['maximum_relative_balance_error'],RELATIVE_BALANCE_TOL)

    def test_modality_swap_value_and_gradient_parity(self):
        pr,c,z,w,r,y,ft,fi,ts,ims=fixture();p,q=softmax(z),softmax(w)
        for rho in (0.,1.5):
            a,gp,gq,_=call(p,q,r,ft,fi,ts,ims,rho)
            b,hq,hp,_=call(q,p,r.transpose(0,2,1),fi,ft,ims,ts,rho)
            for x,y in ((a,b),(gp,hp),(gq,hq)):np.testing.assert_allclose(x,y,rtol=0,atol=1e-13)

    def test_fixed_reward_translation_preserves_gradients(self):
        pr,c,z,w,r,y,ft,fi,ts,ims=fixture();p,q=softmax(z),softmax(w)
        for rho in (0.,1.5):
            a,gp,gq,_=call(p,q,r,ft,fi,ts,ims,rho);b,hp,hq,_=call(p,q,r+.02,ft,fi,ts,ims,rho)
            np.testing.assert_allclose(b,a+.02,rtol=0,atol=1e-13)
            for x,y in ((gp,hp),(gq,hq)):np.testing.assert_allclose(x,y,rtol=0,atol=1e-13)

    def test_invalid_inputs_explicit_mode_and_immutability(self):
        pr,c,z,w,r,y,ft,fi,ts,ims=fixture();p,q=softmax(z),softmax(w);arrays=[p,q,r,ft,fi,ts,ims];copies=[x.copy() for x in arrays]
        call(p,q,r,ft,fi,ts,ims,1.5)
        for a,b in zip(arrays,copies):np.testing.assert_array_equal(a,b)
        with self.assertRaises(ValueError):derivative(p,q,r,ft,fi,ts,ims,1.5,mode='independent')
        with self.assertRaises(ValueError):call(p,q,r,ft,fi,ts,ims,.5)
        bad=p.copy();bad[0,0]=0;bad[0,1]+=p[0,0]
        with self.assertRaises(NumericalDomainError):call(bad,q,r,ft,fi,ts,ims,1.5)
        with self.assertRaises(ValueError):call(p,q,r*np.nan,ft,fi,ts,ims,1.5)
        with self.assertRaises(ValueError):call(p,q,r,ft[:,:11],fi,ts,ims,1.5)

    def test_exact_rational_scalar_and_batched_reference_parity(self):
        pr,c,z,w,r,y,ft,fi,ts,ims=fixture();p,q=softmax(z),softmax(w)
        law=apply_batch(pr,p,q,c,observed_model_sha256=SHA)
        for rho in (0.,1.5):
            values,gp,gq,_=call(p,q,r,ft,fi,ts,ims,rho)
            for i in range(4):
                exact=rational_row(p[i],q[i],r[i],ft[i],fi[i],ts,ims,rho,mode='simplex')
                scalar=extended_row(p[i],q[i],r[i],ft[i],fi[i],ts,ims,rho)
                self.assertTrue(exact['admitted'] and scalar['admitted'])
                MEASUREMENTS.setdefault('exact_reference_max_gradient_difference',0.)
                for actual,ref in ((gp[i]*4,exact['gradient_p']),(gq[i]*4,exact['gradient_q'])):
                    error=float(np.max(np.abs(actual-ref)));MEASUREMENTS['exact_reference_max_gradient_difference']=max(error,MEASUREMENTS['exact_reference_max_gradient_difference'])
                    np.testing.assert_allclose(actual,ref,rtol=0,atol=1e-12)
                np.testing.assert_allclose(law['joint'][i]/law['cdf_total'][i],exact['table'],rtol=0,atol=1e-12)
                np.testing.assert_allclose(gp[i]*4,scalar['gradient_p'],rtol=0,atol=1e-12)
                self.assertAlmostEqual(values[i],exact['value'],places=12)

    def test_explicit_profile_roundtrip_binding_and_reject_mixing(self):
        import json
        pr,c,z,w,r,y,ft,fi,ts,ims=fixture();p,q=softmax(z),softmax(w)
        again=NormalizedCouplingProfile.loads(pr.dumps(),expected_model_sha256=SHA,expected_mode=NEW_MODE)
        self.assertEqual(again.dumps(),pr.dumps());self.assertNotEqual(pr.key,pr.coupling.key)
        for wrong in (OLD_MODE,COUPLING_MODE,'independent'):
            with self.assertRaises(ValueError):NormalizedCouplingProfile.loads(pr.dumps(),expected_model_sha256=SHA,expected_mode=wrong)
        with self.assertRaises(ValueError):NormalizedCouplingProfile.loads(pr.dumps(),expected_model_sha256='b'*64,expected_mode=NEW_MODE)
        with self.assertRaises(ValueError):NormalizedCouplingProfile.loads(pr.coupling.dumps(),expected_model_sha256=SHA,expected_mode=NEW_MODE)
        with self.assertRaises(ValueError):CouplingProfile.loads(pr.dumps(),expected_model_sha256=SHA,expected_mode=COUPLING_MODE)
        doc=json.loads(pr.dumps());doc['profile']['precision']['mantissa_bits']+=1
        with self.assertRaises(ValueError):NormalizedCouplingProfile.loads(json.dumps(doc),expected_model_sha256=SHA,expected_mode=NEW_MODE)
        with self.assertRaises(ValueError):apply_batch(pr.coupling,p,q,c,observed_model_sha256=SHA)
        with self.assertRaises(ValueError):apply_batch(pr,p,q,c,observed_model_sha256='b'*64)
        for a,b in zip((p,q),(softmax(z),softmax(w))):np.testing.assert_array_equal(a,b)

    def test_no_fallback_without_genuine_extended_precision(self):
        from unittest.mock import patch
        with patch('normalized.np.longdouble',np.float64):
            with self.assertRaisesRegex(NumericalDomainError,'genuine extended'):precision()

if __name__=='__main__':unittest.main()
