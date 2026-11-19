import unittest
import numpy as np
from aligned import all_terms
from grouped_training import group_schedule,grouped_terms,select_group_gradients
from control import Command
from transport import TransportProfile
from utility import certainty_equivalent
MEASUREMENTS={}
def softmax(z):
    e=np.exp(z-z.max(1,keepdims=True));return e/e.sum(1,keepdims=True)
def fixture():
    ts=tuple(range(12));z=np.sin(np.arange(192,dtype=float)).reshape(16,12)/3;w=np.cos(np.arange(192,dtype=float)).reshape(16,12)/4
    commands=[Command(1,0,0)]*8+[Command(0,1,0)]*8
    ft=np.asarray([TransportProfile.destinations(ts,c) for c in commands]);fi=ft.copy();labels=np.array([0]*8+[4]*8)
    reward0=(np.arange(144).reshape(12,12)%23)/22*1.3-.3;reward1=np.flip(reward0,axis=0).copy();rewards=np.repeat(np.stack([reward0,reward1]),8,axis=0)
    return z,w,rewards,labels,ft,fi,ts,np.repeat(np.arange(2),8)
class GroupedTrainingTests(unittest.TestCase):
    def test_aligned_K8_and_anchor_finite_differences(self):
        z,w,r,y,ft,fi,ts,groups=fixture()
        def compute():
            t=all_terms(softmax(z),softmax(w),r,y,ft,fi,ts,ts,1.5);g=grouped_terms(t,groups);return t,g
        t,g=compute();dp,dq=select_group_gradients(t,g,'group_ndu');errors=[];utility_errors=[]
        for logits,gradient,utility_gradient in ((z,dp,g['group_ndu'][1]),(w,dq,g['group_ndu'][2])):
            for row,col in ((0,0),(7,11),(8,3),(15,7)):
                value=logits[row,col];eps=1e-6
                logits[row,col]=value+eps;tp,gp=compute();plus=-gp['group_ndu'][0].mean()+.2*tp['aligned_anchor_value']
                logits[row,col]=value-eps;tm,gm=compute();minus=-gm['group_ndu'][0].mean()+.2*tm['aligned_anchor_value'];logits[row,col]=value
                error=abs((plus-minus)/(2*eps)-gradient[row,col]);errors.append(float(error));self.assertLess(error,3e-8)
                utility_error=abs((-gp['group_ndu'][0].mean()+gm['group_ndu'][0].mean())/(2*eps)-utility_gradient[row,col]);utility_errors.append(float(utility_error));self.assertLess(utility_error,3e-8)
        MEASUREMENTS['aligned_group_utility_FD_coordinates']=8;MEASUREMENTS['maximum_aligned_group_utility_FD_error']=max(utility_errors);MEASUREMENTS['aligned_anchor_FD_coordinates']=8;MEASUREMENTS['maximum_aligned_anchor_FD_error']=max(errors)
        for got,utility,anchor in zip((dp,dq),g['group_ndu'][1:3],t['aligned_anchor']):np.testing.assert_array_equal(got,utility+.2*anchor)
        # Nonuniform utility tilt must NOT multiply the anchor gradient.
        wrong=g['group_ndu'][1]+.2*t['aligned_anchor'][0]*g['group_ndu'][3][:,None]
        self.assertGreater(float(np.max(np.abs(dp-wrong))),1e-8)
    def test_aligned_group_value_direct_flatten_and_A_parity(self):
        z,w,r,y,ft,fi,ts,groups=fixture();p,q=softmax(z),softmax(w);t=all_terms(p,q,r,y,ft,fi,ts,ts,1.5);g=grouped_terms(t,groups)
        pulled=r[np.arange(16)[:,None,None],ft[:,:,None],fi[:,None,:]];joint=p[:,:,None]*q[:,None,:]
        direct=certainty_equivalent(pulled.reshape(2,-1),joint.reshape(2,-1)/8,1.5,axis=1)
        np.testing.assert_allclose(g['group_ndu'][0],direct,rtol=0,atol=2e-15)
        for got,original in zip(g['group_additive'][1:3],t['aligned_additive'][1:3]):np.testing.assert_array_equal(got,original)
        a=select_group_gradients(t,g,'additive')
        for got,original,anchor in zip(a,t['aligned_additive'][1:3],t['aligned_anchor']):np.testing.assert_array_equal(got,original+.2*anchor)
    def test_sampler_inventory_determinism_and_no_mutation(self):
        ids=[f'content-{i}' for i in range(130) for _ in range(6)];before=ids.copy();schedule=group_schedule(ids,9103,steps=3)
        self.assertEqual(schedule,group_schedule(ids,9103,steps=3));self.assertEqual(ids,before)
        for rows,full,groups in schedule:
            self.assertEqual(len(rows),64);self.assertEqual(sum(full),32);self.assertEqual(groups,tuple(np.repeat(np.arange(8),8)))
            chosen=[]
            for block in range(8):
                rr=rows[block*8:(block+1)*8];ff=full[block*8:(block+1)*8];chosen.append(rr[0]//6)
                self.assertEqual(len({x//6 for x in rr}),1);self.assertEqual(len({x%6 for x in rr}),4)
                for variant in set(rr):self.assertEqual(sorted(ff[j] for j,row in enumerate(rr) if row==variant),[False,True])
            self.assertEqual(len(set(chosen)),8)
        for bad in ([],ids[:-1],['same']*780):
            with self.assertRaises(ValueError):group_schedule(bad,9103)
        with self.assertRaises(ValueError):group_schedule(ids,True)
