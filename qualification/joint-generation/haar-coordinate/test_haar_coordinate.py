import unittest
import numpy as np
from model import JointModel
from source_scene import SourceSceneModel,MODE as SOURCE_MODE
from haar_coordinate import HaarSourceModel,HaarProfile,PROFILE,MODE,haar_pixels,haar_features,encoder_coordinates
MEASUREMENTS={}
def source():return SourceSceneModel(202,12,192,seed=17,mode=SOURCE_MODE)
def inputs():return np.arange(404,dtype=float).reshape(2,202)/404
def gradients(model,x):
    p,q=model.forward(x);y=np.array([1,5]);p[np.arange(2),y]-=1;q[np.arange(2),y]-=1
    return model.gradients(x,p/4,q/4)
class HaarTests(unittest.TestCase):
    def test_basis_involution_norm(self):
        H=haar_pixels(PROFILE,np.eye(192));np.testing.assert_array_equal(H,H.T);np.testing.assert_array_equal(H@H,np.eye(192))
        x=np.sin(np.arange(384)).reshape(2,192);original=x.copy();y=haar_pixels(PROFILE,x)
        np.testing.assert_allclose(haar_pixels(PROFILE,y),x,rtol=0,atol=2e-15);np.testing.assert_allclose((y*y).sum(1),(x*x).sum(1),rtol=2e-15,atol=2e-14);np.testing.assert_array_equal(x,original)
    def test_low_view_details_commands_and_mask(self):
        small=np.arange(96,dtype=float).reshape(2,4,4,3)/128;low=np.repeat(np.repeat(small,2,axis=1),2,axis=2);out=haar_pixels(PROFILE,low.reshape(2,192)).reshape(2,8,8,3)
        for block in (out[:,0::2,1::2],out[:,1::2,0::2],out[:,1::2,1::2]):np.testing.assert_array_equal(block,np.zeros_like(block))
        np.testing.assert_array_equal(out[:,0::2,0::2],2*small)
        x=inputs();y=haar_features(PROFILE,x);np.testing.assert_array_equal(y[:,-10:],x[:,-10:]);self.assertFalse(np.shares_memory(x,y))
        m=HaarSourceModel.from_source(source(),mode=MODE);changed=x.copy();changed[:,-10:]+=100
        for a,b in zip(m.forward(x),m.forward(changed)):np.testing.assert_array_equal(a,b)
        gx,gy=gradients(m,x),gradients(m,changed)
        for key in gx:np.testing.assert_array_equal(gx[key],gy[key])
    def test_conversion_function_decoder_count_and_clone(self):
        base=source();base.supervised_step(inputs(),np.array([1,5]));self.assertTrue(base._moments);before=base.digest();m=HaarSourceModel.from_source(base,mode=MODE);x=inputs();self.assertEqual(m._moments,{});self.assertEqual(m.updates,0)
        for a,b in zip(base.forward(x),m.forward(x)):np.testing.assert_allclose(a,b,rtol=0,atol=3e-15)
        for key in ('decoder','decoder_bias','text','text_bias','image','image_bias','bias'):np.testing.assert_array_equal(m.params[key],base.params[key])
        self.assertEqual(sum(p.size for p in m.params.values()),sum(p.size for p in base.params.values()));self.assertEqual(base.digest(),before);self.assertNotEqual(m.digest(),before);self.assertEqual(m.conversion_source_digest,before)
        clone=m.clone();self.assertIs(type(clone),HaarSourceModel);self.assertEqual(clone.mode,MODE);self.assertEqual(clone.digest(),m.digest());self.assertEqual(clone._moments,{});self.assertEqual(clone.updates,0)
        for key in m.params:self.assertFalse(np.shares_memory(clone.params[key],m.params[key]))
        self.assertEqual(m.haar_work['encoder_conversion_calls'],1);self.assertEqual(clone.haar_work['encoder_conversion_calls'],0)
        with self.assertRaises(AttributeError):clone.mode=SOURCE_MODE
    def test_gradient_FD_and_SGD_covariance(self):
        base=source();m=HaarSourceModel.from_source(base,mode=MODE);x=inputs();gb,gm=gradients(base,x),gradients(m,x)
        for key in gb:
            pulled=encoder_coordinates(PROFILE,gm[key]) if key=='encoder' else gm[key]
            np.testing.assert_allclose(pulled,gb[key],rtol=0,atol=3e-15)
        def loss():
            p,q=m.forward(x);return -(np.log(p[np.arange(2),[1,5]])+np.log(q[np.arange(2),[1,5]])).mean()/2
        errors=[]
        for key,index in (('encoder',(0,0)),('encoder',(195,0)),('bias',(0,)),('text',(0,1)),('text_bias',(1,)),('image',(0,5)),('image_bias',(5,))):
            old=m.params[key][index];eps=1e-6;m.params[key][index]=old+eps;plus=loss();m.params[key][index]=old-eps;minus=loss();m.params[key][index]=old
            errors.append(float(abs((plus-minus)/(2*eps)-gm[key][index])))
        self.assertLess(max(errors),2e-7);MEASUREMENTS['model_FD_coordinates']=7;MEASUREMENTS['model_max_FD']=max(errors)
        for key in gb:base.params[key]-=.01*gb[key];m.params[key]-=.01*gm[key]
        converted=HaarSourceModel.from_source(base,mode=MODE)
        for key in m.params:np.testing.assert_allclose(m.params[key],converted.params[key],rtol=0,atol=3e-15)
    def test_constructed_Adam_non_covariance(self):
        base=source();m=HaarSourceModel.from_source(base,mode=MODE);g=np.zeros((202,32));g[0,0]=1.;g[3,0]=2.
        base.apply_gradients({'encoder':g},.01);m.apply_gradients({'encoder':encoder_coordinates(PROFILE,g)},.01)
        mapped=encoder_coordinates(PROFILE,base.params['encoder']);difference=float(np.max(np.abs(m.params['encoder']-mapped)));self.assertGreater(difference,.001)
        MEASUREMENTS['literal_Adam_coordinate_difference']=difference
        # A mathematical optimizer witness only, not any scientific quality metric.
    def test_refusals_nonfinite_overflow_wrongmode(self):
        for bad in (np.empty((0,192)),np.zeros((2,191)),np.full((2,192),np.nan),np.full((2,192),1e308)):
            with self.assertRaises(ValueError):haar_pixels(PROFILE,bad)
        with self.assertRaises(ValueError):haar_pixels(object(),np.zeros((1,192)))
        with self.assertRaises(ValueError):haar_features(PROFILE,np.zeros((1,192)))
        with self.assertRaises(ValueError):encoder_coordinates(PROFILE,np.zeros((192,32)))
        with self.assertRaises(ValueError):HaarProfile(SOURCE_MODE)
        with self.assertRaises(ValueError):HaarSourceModel.from_source(JointModel(202,12,192),mode=MODE)
        m=HaarSourceModel.from_source(source(),mode=MODE)
        with self.assertRaises(ValueError):HaarSourceModel.from_source(m,mode=MODE)
        with self.assertRaises(ValueError):HaarSourceModel.from_source(source(),mode=SOURCE_MODE)
        for fun in (m.save,HaarSourceModel.load):
            with self.assertRaisesRegex(ValueError,'checkpoint unsupported'):fun(object())
