import unittest
import numpy as np
from model import JointModel,softmax
from source_scene import SourceSceneModel,MODE as SOURCE_MODE
from color_spatial_source import ColorSpatialSourceModel as FactorizedSourceModel,ColorSpatialProfile as FactorProfile,PROFILE,MODE,ATTRS,project,pullback
from factorized_source import PROFILE as FULL_PROFILE,project as full_project
from aligned import all_terms
from control import Command
from transport import TransportProfile
MEASUREMENTS={}
def policies():
    z=np.sin(np.arange(48)).reshape(4,12)/3;w=np.cos(np.arange(48)).reshape(4,12)/4
    return z,w
class ColorSpatialTests(unittest.TestCase):
    def test_projection_marginals_product_idempotence_correlation(self):
        z,_=policies();p=softmax(z);original=p.copy();q=project(PROFILE,p);attrs=np.asarray(ATTRS)
        np.testing.assert_allclose(q.sum(1),1,rtol=0,atol=2e-15)
        for axis,size in enumerate((3,4)):
            for v in range(size):np.testing.assert_allclose(q[:,attrs[:,axis]==v].sum(1),p[:,attrs[:,axis]==v].sum(1),rtol=0,atol=2e-15)
        np.testing.assert_allclose(project(PROFILE,q),q,rtol=0,atol=2e-15)
        self.assertGreater(float(np.max(np.abs(q-p))),1e-4);np.testing.assert_array_equal(p,original)
        independent=(np.array([.2,.3,.5])[:,None]*np.array([.4,.1,.1,.4])[None,:]).reshape(1,12)
        np.testing.assert_allclose(project(PROFILE,independent),independent,rtol=0,atol=2e-15)
        self.assertGreater(float(np.max(np.abs(full_project(FULL_PROFILE,independent)-independent))),.01)
        # Uniform independent product is fixed; canonical ordering, not arbitrary remapping.
        np.testing.assert_allclose(project(PROFILE,np.full((1,12),1/12)),np.full((1,12),1/12),rtol=0,atol=2e-15)
    def test_virtual_logit_cotangent_fullhead_FD(self):
        z,_=policies();g=np.cos(np.arange(48)).reshape(4,12)/13;g-=g.mean(1,keepdims=True);analytic=pullback(PROFILE,softmax(z),g);errors=[]
        for row in range(4):
            for col in range(12):
                old=z[row,col];eps=1e-6
                z[row,col]=old+eps;plus=np.sum(g*np.log(project(PROFILE,softmax(z))))
                z[row,col]=old-eps;minus=np.sum(g*np.log(project(PROFILE,softmax(z))));z[row,col]=old
                errors.append(float(abs((plus-minus)/(2*eps)-analytic[row,col])))
        self.assertLess(max(errors),3e-8);np.testing.assert_allclose(analytic.sum(1),0,rtol=0,atol=2e-15)
        MEASUREMENTS['virtual_logit_cotangent_FD_coordinates']=48;MEASUREMENTS['virtual_logit_cotangent_max_FD']=max(errors)
    def test_bothhead_partial_transport_A_anchor_FD(self):
        z,w=policies();ts=tuple(range(12));commands=[Command(1,0,0),Command(0,1,0)]*2
        ft=np.asarray([TransportProfile.destinations(ts,c) for c in commands]);y=np.array([0,4,1,5]);r=(np.arange(576).reshape(4,12,12)%23)/22*1.3-.3
        def calc():return all_terms(project(PROFILE,softmax(z)),project(PROFILE,softmax(w)),r,y,ft,ft,ts,ts,1.5)
        t=calc();errors=[]
        for logits,grad,anchor in ((z,t['aligned_additive'][1],t['aligned_anchor'][0]),(w,t['aligned_additive'][2],t['aligned_anchor'][1])):
            raw=pullback(PROFILE,softmax(logits),grad+.2*anchor)
            for row,col in ((0,0),(1,11),(2,3),(3,7)):
                old=logits[row,col];eps=1e-6
                logits[row,col]=old+eps;tp=calc();plus=-tp['aligned_additive'][0].mean()+.2*tp['aligned_anchor_value']
                logits[row,col]=old-eps;tm=calc();minus=-tm['aligned_additive'][0].mean()+.2*tm['aligned_anchor_value'];logits[row,col]=old
                errors.append(float(abs((plus-minus)/(2*eps)-raw[row,col])))
        self.assertLess(max(errors),3e-8);MEASUREMENTS['A_anchor_bothhead_FD_coordinates']=8;MEASUREMENTS['A_anchor_max_FD']=max(errors)
        keep=np.asarray([TransportProfile.destinations(ts,Command(0,0,0))]*4);np.testing.assert_array_equal(keep,np.tile(np.arange(12),(4,1)))
        specified=np.asarray([TransportProfile.destinations(ts,Command(1,1,1))]*4);np.testing.assert_array_equal(specified,np.zeros((4,12),dtype=int))
        correlated=(np.array([.2,.3,.5])[:,None]*np.array([.4,.1,.1,.4])[None,:]).reshape(1,12)
        def push(prob,command):
            destinations=TransportProfile.destinations(ts,command);out=np.zeros_like(prob)
            for k,destination in enumerate(destinations):out[:,destination]+=prob[:,k]
            return out
        # Same raw policy only: fixing either spatial axis removes its correlation.
        for raw in (correlated,softmax(z)):
            cs=project(PROFILE,raw);full=full_project(FULL_PROFILE,raw)
            for color in range(4):
                for shape in range(3):
                    for position in range(3):
                        if shape or position:np.testing.assert_allclose(push(cs,Command(color,shape,position)),push(full,Command(color,shape,position)),rtol=0,atol=2e-15)
        self.assertGreater(float(np.max(np.abs(push(project(PROFILE,correlated),Command(1,0,0))-push(full_project(FULL_PROFILE,correlated),Command(1,0,0))))),.01)
        fixed=all_terms(project(PROFILE,softmax(z)),project(PROFILE,softmax(w)),r,np.zeros(4,dtype=int),specified,specified,ts,ts,1.5)
        for grad in (*fixed['aligned_additive'][1:3],*fixed['aligned_anchor']):np.testing.assert_allclose(grad,0,rtol=0,atol=2e-15)
    def test_model_encoder_heads_supervised_FD(self):
        model=FactorizedSourceModel(202,12,192,seed=17,mode=MODE);x=np.arange(404).reshape(2,202)/404;y=np.array([1,5]);pt,pi=model.forward(x);dt,di=pt.copy(),pi.copy();dt[np.arange(2),y]-=1;di[np.arange(2),y]-=1
        grads=model.gradients(x,dt/4,di/4);errors=[]
        def loss():
            p,q=model.forward(x);return -(np.log(p[np.arange(2),y])+np.log(q[np.arange(2),y])).mean()/2
        for key,index in (('encoder',(0,0)),('encoder',(195,0)),('bias',(0,)),('text',(0,1)),('text_bias',(1,)),('image',(0,5)),('image_bias',(5,))):
            old=model.params[key][index];eps=1e-6;model.params[key][index]=old+eps;plus=loss();model.params[key][index]=old-eps;minus=loss();model.params[key][index]=old
            errors.append(float(abs((plus-minus)/(2*eps)-grads[key][index])))
        self.assertLess(max(errors),2e-7);MEASUREMENTS['model_FD_coordinates']=7;MEASUREMENTS['model_max_FD']=max(errors)
        ts=tuple(range(12));ft=np.asarray([TransportProfile.destinations(ts,c) for c in (Command(1,0,0),Command(0,1,0))]);labels=np.array([0,4]);reward=(np.arange(288).reshape(2,12,12)%23)/22*1.3-.3
        def terms():
            p,q=model.forward(x);return all_terms(p,q,reward,labels,ft,ft,ts,ts,1.5)
        t=terms();grads=model.gradients(x,t['aligned_additive'][1]+.2*t['aligned_anchor'][0],t['aligned_additive'][2]+.2*t['aligned_anchor'][1]);aerrors=[]
        def aligned_loss():
            t=terms();return -t['aligned_additive'][0].mean()+.2*t['aligned_anchor_value']
        for key,index in (('encoder',(0,0)),('encoder',(195,0)),('bias',(0,)),('text',(0,1)),('text_bias',(1,)),('image',(0,5)),('image_bias',(5,))):
            old=model.params[key][index];eps=1e-6;model.params[key][index]=old+eps;plus=aligned_loss();model.params[key][index]=old-eps;minus=aligned_loss();model.params[key][index]=old
            aerrors.append(float(abs((plus-minus)/(2*eps)-grads[key][index])))
        self.assertLess(max(aerrors),2e-7);MEASUREMENTS['model_A_anchor_FD_coordinates']=7;MEASUREMENTS['model_A_anchor_max_FD']=max(aerrors)

    def test_parameter_parity_clone_mask_decoder_and_work(self):
        m=FactorizedSourceModel(202,12,192,seed=17,mode=MODE);base=SourceSceneModel(202,12,192,seed=17,mode=SOURCE_MODE)
        self.assertEqual(sum(v.size for v in m.params.values()),sum(v.size for v in base.params.values()))
        for key in m.params:np.testing.assert_array_equal(m.params[key],base.params[key])
        self.assertNotEqual(m.digest(),base.digest());x=np.arange(404).reshape(2,202)/404;before=x.copy();changed=x.copy();changed[:,-10:]+=10
        for a,b in zip(m.forward(x),m.forward(changed)):np.testing.assert_array_equal(a,b)
        np.testing.assert_array_equal(x,before);decoder={k:m.params[k].copy() for k in ('decoder','decoder_bias')};start=m.factor_operations.copy()
        m.supervised_step(x,np.array([1,5]));self.assertEqual(m.factor_operations['raw_forward_calls']-start['raw_forward_calls'],2);self.assertEqual(m.factor_operations['project_calls']-start['project_calls'],4);self.assertEqual(m.factor_operations['pullback_calls']-start['pullback_calls'],2)
        for key,v in decoder.items():np.testing.assert_array_equal(m.params[key],v)
        clone=m.clone();self.assertIs(type(clone),FactorizedSourceModel);self.assertEqual(clone.mode,MODE);self.assertEqual(clone.digest(),m.digest());self.assertEqual(clone.updates,0);self.assertEqual(clone._moments,{})
        for key in m.params:self.assertFalse(np.shares_memory(m.params[key],clone.params[key]))
        with self.assertRaises(AttributeError):clone.mode=SOURCE_MODE
        for f in (m.save,FactorizedSourceModel.load):
            with self.assertRaisesRegex(ValueError,'checkpoint unsupported'):f(object())
    def test_domain_refusals_extreme_underflow(self):
        p=np.full((2,12),1/12)
        for bad in (np.empty((0,12)),np.ones((2,11)),np.zeros((2,12)),p*2,np.full((2,12),np.nan)):
            with self.assertRaises(ValueError):project(PROFILE,bad)
        tiny=np.full((1,12),1e-300);tiny[0,0]=1.
        with self.assertRaises(ValueError):project(PROFILE,tiny)
        with self.assertRaises(ValueError):pullback(PROFILE,p,np.zeros((1,12)))
        with self.assertRaises(ValueError):pullback(PROFILE,p,np.full((2,12),np.inf))
        with self.assertRaises(ValueError):pullback(PROFILE,p,np.ones((2,12)))
        with self.assertRaises(ValueError):project(object(),p)
        with self.assertRaises(ValueError):project(FULL_PROFILE,p)
        with self.assertRaises(ValueError):FactorProfile(SOURCE_MODE)
        with self.assertRaises(ValueError):FactorProfile(MODE,ATTRS[::-1])
        for attrs in (tuple(tuple(float(v) for v in row) for row in ATTRS),tuple((bool(row[0]) if row[0] in (0,1) else row[0],row[1]) for row in ATTRS),list(ATTRS),tuple(list(row) for row in ATTRS)):
            with self.assertRaises(ValueError):FactorProfile(MODE,attrs)
        with self.assertRaises(ValueError):FactorizedSourceModel(202,12,192,mode=SOURCE_MODE)
        with self.assertRaises(ValueError):FactorizedSourceModel(192,12,192,mode=MODE)
