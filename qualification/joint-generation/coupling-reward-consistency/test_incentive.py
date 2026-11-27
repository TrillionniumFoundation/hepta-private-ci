import unittest
import numpy as np
from control import Command,ControlProfile,MODE as CONTROL_MODE
from transport import TransportProfile,TRANSPORT_MODE
from coupling import CouplingProfile,COUPLING_MODE
from normalized import NormalizedCouplingProfile,MODE as NUMERIC_MODE,value_and_grad,apply_batch
from utility import joint_value_and_grad,certainty_equivalent
from reward_consistency import repair_rewards,MODE as REPAIR_MODE

MEASUREMENTS={};SHA='a'*64;SEM=np.arange(12)
PAIRS=((.8,.6),(.6,.4),(.4,.2),(.2,.4),(.4,.6),(.6,.8))
QUALITIES=((1.,0.),(1.,.5),(.5,.5))

def fixture(p,q,quality):
    command=Command(1,1,0)
    profile=NormalizedCouplingProfile(CouplingProfile(TransportProfile(ControlProfile(SHA,tuple(range(12)),tuple(range(12)),CONTROL_MODE),TRANSPORT_MODE),COUPLING_MODE),NUMERIC_MODE)
    f=np.asarray(profile.transport.destinations(SEM,command));support=sorted(set(f.tolist()));assert len(support)==2
    target,wrong=support;mask=f==target
    def policy(v):return np.where(mask,v/mask.sum(),(1-v)/(~mask).sum())[None,:]
    ct=SEM[:,None]==target;ci=SEM[None,:]==target
    qual=np.where(SEM==target,quality[0],quality[1])
    reward=(.3*ct+.3*ci+.3*(ct&ci)+.1*qual[None,:]-.35*(SEM[:,None]!=SEM[None,:]))[None,:,:]
    return profile,(command,),f[None,:],target,wrong,mask,policy(p),policy(q),reward,policy

def call(p,q,r,f,rho):return value_and_grad(p,q,r,f,f,SEM,SEM,rho,mode=NUMERIC_MODE)

def closed(p,q,r,target,wrong,rho):
    r00=r[0,wrong,wrong];r10=r[0,target,wrong];r01=r[0,wrong,target];r11=r[0,target,target]
    if p>q:weights=np.asarray([1-p,p-q,q]);rewards=np.asarray([r00,r10,r11]);dp=np.asarray([-1,1,0]);dq=np.asarray([0,-1,1])
    else:weights=np.asarray([1-q,q-p,p]);rewards=np.asarray([r00,r01,r11]);dp=np.asarray([0,-1,1]);dq=np.asarray([-1,1,0])
    if rho==0:return float(weights@rewards),float(dp@rewards),float(dq@rewards)
    h=np.exp(-rho*rewards);z=weights@h
    return float(-np.log(z)/rho),float(-(dp@h)/(rho*z)),float(-(dq@h)/(rho*z))

class IncentiveTests(unittest.TestCase):
    def test_fixed_grid_original_negative_dominant_text_vs_independent(self):
        records=[]
        for p,q in PAIRS:
            for quality in QUALITIES:
                pr,c,f,t,w,m,a,b,r,policy=fixture(p,q,quality)
                pulled=r[np.arange(1)[:,None,None],f[:,:,None],f[:,None,:]]
                for rho in (0.,1.5):
                    v,gp,gq,_=call(a,b,r,f,rho);_,ip,iq=joint_value_and_grad(a,b,pulled,rho)
                    derivative=-float(gp[0,m].sum())/(p*(1-p));independent=-float(ip[0,m].sum())/(p*(1-p))
                    cv,cp,cq=closed(p,q,r,t,w,rho)
                    self.assertAlmostEqual(derivative,cp,places=12);self.assertAlmostEqual(v[0],cv,places=12)
                    self.assertGreater(independent,0)
                    if p>q:
                        self.assertLess(derivative,0)
                        if rho==0:self.assertAlmostEqual(derivative,-.05,places=12)
                    else:self.assertGreater(derivative,0)
                    records.append(dict(p=p,q=q,quality=quality,rho=rho,coupled_text_derivative=derivative,independent_text_derivative=independent,dominant_text=p>q))
        MEASUREMENTS['fixed_grid']=records
        self.assertEqual(len(records),36);self.assertEqual(sum(x['dominant_text'] for x in records),18)

    def test_minimal_class_credit_repair_and_explicit_mode(self):
        for target in range(12):
            ct=SEM[:,None]==target;ci=SEM[None,:]==target
            quality=.1*np.arange(12)[None,:]/11
            class_part=.3*ct+.3*ci+.3*(ct&ci)-.35*(SEM[:,None]!=SEM[None,:])
            original=(class_part+quality)[None,:,:];copy=original.copy()
            fixed=repair_rewards(original,np.asarray([target]),SEM,SEM,mode=REPAIR_MODE)[0]
            corrected_class=fixed-quality
            np.testing.assert_array_equal(original,copy)
            np.testing.assert_allclose(corrected_class[ct^ci],0,rtol=0,atol=1e-15)
            np.testing.assert_allclose(fixed[~(ct^ci)],original[0][~(ct^ci)],rtol=0,atol=0)
            for wrong in range(12):
                if wrong==target:continue
                self.assertAlmostEqual(class_part[wrong,wrong],0,places=15)
                self.assertAlmostEqual(fixed[target,wrong]-original[0,target,wrong],.35-.3,places=15)
                self.assertGreaterEqual(corrected_class[target,wrong]+1e-15,corrected_class[wrong,wrong])
                self.assertGreaterEqual(corrected_class[wrong,target]+1e-15,corrected_class[wrong,wrong])
        with self.assertRaises(ValueError):repair_rewards(original,np.asarray([target]),SEM,SEM,mode='old')
        with self.assertRaises(ValueError):repair_rewards(original+.2,np.asarray([target]),SEM,SEM,mode=REPAIR_MODE)

    def test_repaired_dominant_text_zero_not_claimed_positive_gain(self):
        maxima=[]
        for p,q in PAIRS:
            for quality in QUALITIES:
                pr,c,f,t,w,m,a,b,r,policy=fixture(p,q,quality);fixed=repair_rewards(r,np.asarray([t]),SEM,SEM,mode=REPAIR_MODE)
                for rho in (0.,1.5):
                    v,gp,gq,_=call(a,b,fixed,f,rho);dp=-float(gp[0,m].sum())/(p*(1-p));dq=-float(gq[0,m].sum())/(q*(1-q))
                    cv,cp,cq=closed(p,q,fixed,t,w,rho)
                    self.assertAlmostEqual(dp,cp,places=12);self.assertAlmostEqual(dq,cq,places=12)
                    if p>q:self.assertAlmostEqual(dp,0,places=12);maxima.append(abs(dp))
                    else:self.assertGreater(dp,0);self.assertGreaterEqual(dq,-1e-12)
        MEASUREMENTS['repaired_dominant_text_max_absolute_derivative']=max(maxima)

    def test_actual_cdf_both_heads_old_and_repaired_centered_differences(self):
        maximum=0.
        for p,q in PAIRS:
            for quality in QUALITIES:
                pr,c,f,t,w,m,a,b,r,policy=fixture(p,q,quality)
                for reward in (r,repair_rewards(r,np.asarray([t]),SEM,SEM,mode=REPAIR_MODE)):
                    for rho in (0.,1.5):
                        _,gp,gq,_=call(a,b,reward,f,rho)
                        def actual(pp,qq):
                            law=apply_batch(pr,policy(pp),policy(qq),c,observed_model_sha256=SHA)
                            table=law['joint']/law['cdf_total'][:,None,None]
                            return certainty_equivalent(reward.reshape(1,-1),table.reshape(1,-1),rho,axis=1)[0]
                        analytic=(-float(gp[0,m].sum())/(p*(1-p)),-float(gq[0,m].sum())/(q*(1-q)))
                        numeric=((actual(p+1e-6,q)-actual(p-1e-6,q))/2e-6,(actual(p,q+1e-6)-actual(p,q-1e-6))/2e-6)
                        self.assertEqual(np.sign(p-q),np.sign(p+1e-6-q));self.assertEqual(np.sign(p-q),np.sign(p-1e-6-q))
                        for x,y in zip(analytic,numeric):self.assertLessEqual(abs(x-y),1e-7);maximum=max(maximum,abs(x-y))
        MEASUREMENTS['actual_CDF_derivative_max_abs_error']=maximum

if __name__=='__main__':unittest.main()
