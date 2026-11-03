import unittest
import numpy as np
from source_scene import SourceSceneModel,MODE as SOURCE_MODE
from haar_coordinate import HaarSourceModel,PROFILE,MODE as HAAR_MODE,encoder_coordinates
from matched_haar import MatchedHaarModel,MODE
from aligned import all_terms
from transport import TransportProfile
from control import Command
MEASUREMENTS={}
def source():return SourceSceneModel(202,12,192,seed=17,mode=SOURCE_MODE)
def inputs():return np.arange(404,dtype=float).reshape(2,202)/404
def terms(model):
    p,q=model.forward(inputs());ts=tuple(range(12));ft=np.asarray([TransportProfile.destinations(ts,c) for c in (Command(1,0,0),Command(0,1,0))]);r=(np.arange(288).reshape(2,12,12)%23)/22*1.3-.3
    return all_terms(p,q,r,np.array([0,4]),ft,ft,ts,ts,1.5)
def gradients(model):
    t=terms(model);return model.gradients(inputs(),t['aligned_additive'][1]+.2*t['aligned_anchor'][0],t['aligned_additive'][2]+.2*t['aligned_anchor'][1])
class MatchedHaarTests(unittest.TestCase):
    def test_reference_forward_gradient_and_Adamstep_parity(self):
        for rep in ('raw','haar'):
            base=source();ref=base.clone() if rep=='raw' else HaarSourceModel.from_source(base,mode=HAAR_MODE);new=MatchedHaarModel.from_source(base,representation=rep,mode=MODE)
            for a,b in zip(ref.forward(inputs()),new.forward(inputs())):np.testing.assert_array_equal(a,b)
            self.assertEqual(ref.supervised_step(inputs(),np.array([1,5])),new.supervised_step(inputs(),np.array([1,5])))
            for k in ref.params:np.testing.assert_array_equal(ref.params[k],new.params[k])
            a,b=gradients(ref),gradients(new)
            for k in a:np.testing.assert_array_equal(a[k],b[k])
            ref.apply_gradients(a,.003);new.apply_gradients(b,.003)
            for k in ref.params:np.testing.assert_array_equal(ref.params[k],new.params[k])
            self.assertEqual(ref.digest(),new.digest())
    def test_A_anchor_covariance_and_modelFD(self):
        base=source();raw=MatchedHaarModel.from_source(base,representation='raw',mode=MODE);haar=MatchedHaarModel.from_source(base,representation='haar',mode=MODE);gr,gh=gradients(raw),gradients(haar)
        for k in gr:np.testing.assert_allclose(gr[k],encoder_coordinates(PROFILE,gh[k]) if k=='encoder' else gh[k],rtol=0,atol=3e-15)
        def loss():
            t=terms(haar);return -t['aligned_additive'][0].mean()+.2*t['aligned_anchor_value']
        errors=[]
        for k,index in (('encoder',(0,0)),('encoder',(195,0)),('bias',(0,)),('text',(0,1)),('text_bias',(1,)),('image',(0,5)),('image_bias',(5,))):
            old=haar.params[k][index];eps=1e-6;haar.params[k][index]=old+eps;plus=loss();haar.params[k][index]=old-eps;minus=loss();haar.params[k][index]=old;errors.append(float(abs((plus-minus)/(2*eps)-gh[k][index])))
        self.assertLess(max(errors),2e-7);MEASUREMENTS['A_anchor_model_FD_coordinates']=7;MEASUREMENTS['A_anchor_model_max_FD']=max(errors)
    def test_active_global_norm_clipped_SGD_covariance(self):
        base=source();raw=MatchedHaarModel.from_source(base,representation='raw',mode=MODE);haar=MatchedHaarModel.from_source(base,representation='haar',mode=MODE);gr,gh=gradients(raw),gradients(haar)
        for grads,model in ((gr,raw),(gh,haar)):
            scaled={k:1000*v for k,v in grads.items()};norm=np.sqrt(sum(float(np.sum(v*v)) for v in scaled.values()));self.assertGreater(norm,5.)
            for k,v in scaled.items():model.params[k]-=.01*(5./norm)*v
        for k in raw.params:np.testing.assert_allclose(raw.params[k],encoder_coordinates(PROFILE,haar.params[k]) if k=='encoder' else haar.params[k],rtol=0,atol=2e-14)
    def test_identity_conversion_and_equal_auxiliary_work(self):
        base=source();counts=[]
        for rep in ('raw','haar'):
            model=MatchedHaarModel.from_source(base,representation=rep,mode=MODE);model.forward(inputs());gradients(model);counts.append(model.coordinate_work.copy());clone=model.clone()
            self.assertEqual(clone.identity(),model.identity());self.assertEqual(clone.digest(),model.digest());self.assertEqual(clone._moments,{});self.assertEqual(clone.updates,0);self.assertEqual(clone.coordinate_work,{})
            for k in model.params:self.assertFalse(np.shares_memory(clone.params[k],model.params[k]))
            for f in (clone.save,MatchedHaarModel.load):
                with self.assertRaises(ValueError):f(object())
            with self.assertRaises(ValueError):MatchedHaarModel.from_source(model,representation=rep,mode=MODE)
        self.assertEqual(counts[0],counts[1]);self.assertEqual(counts[0],{'encoder_transform_calls':1,'encoder_transform_rows':32,'input_transform_calls':3,'input_transform_rows':6})
        with self.assertRaises(ValueError):MatchedHaarModel.from_source(base,representation='other',mode=MODE)
        with self.assertRaises(ValueError):MatchedHaarModel.from_source(base,representation='raw',mode='old')
