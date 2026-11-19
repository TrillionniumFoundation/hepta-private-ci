import unittest
import numpy as np
from model import softmax
from utility import joint_value_and_grad
from control import Command,ControlProfile,MODE
from transport import TransportProfile,TRANSPORT_MODE
from aligned import all_terms,push_policies,select_gradients

SHA='a'*64
SEM=np.arange(12)

def fixture():
    commands=(Command(2,0,0),Command(0,1,2),Command(0,0,0))
    image=np.asarray([(i+4)%12 for i in range(12)])
    profile=TransportProfile(ControlProfile(SHA,tuple(map(int,SEM)),tuple(map(int,image)),MODE),TRANSPORT_MODE)
    ft=np.asarray([profile.destinations(profile.base.text_semantics,c) for c in commands])
    fi=np.asarray([profile.destinations(profile.base.image_semantics,c) for c in commands])
    z=np.linspace(-.7,.9,36).reshape(3,12);w=np.linspace(.8,-.6,36).reshape(3,12)
    labels=np.asarray([4,1,9])
    i,j=np.indices((12,12));rewards=np.stack([.3*(i==y)+.3*(image[j]==y)+.3*((i==y)&(image[j]==y))-.35*(i!=image[j]) for y in labels])
    return z,w,rewards,labels,ft,fi,image

class AlignmentTests(unittest.TestCase):
    def test_exact_pushforward_value_identity_A_N(self):
        z,w,r,y,ft,fi,image=fixture();p,q=softmax(z),softmax(w)
        terms=all_terms(p,q,r,y,ft,fi,SEM,image,1.5);a,b=push_policies(p,q,ft,fi)
        for objective,rho in (('additive',0),('ndu',1.5)):
            np.testing.assert_allclose(terms['aligned_'+objective][0],joint_value_and_grad(a,b,r,rho)[0],rtol=1e-13,atol=1e-13)

    def test_full_aligned_objective_centered_logit_derivatives(self):
        z,w,r,y,ft,fi,image=fixture();inverse=np.argsort(image)
        for objective,rho in (('additive',0),('ndu',1.5)):
            terms=all_terms(softmax(z),softmax(w),r,y,ft,fi,SEM,image,1.5)
            gz,gw=select_gradients(terms,'aligned',objective,.2)
            def loss(zz,ww):
                a,b=push_policies(softmax(zz),softmax(ww),ft,fi)
                anchor=-np.mean(np.log(a[np.arange(3),y])+np.log(b[np.arange(3),inverse[y]]))/2
                return .2*anchor-joint_value_and_grad(a,b,r,rho)[0].mean()
            for array,gradient,slot in ((z,gz,0),(w,gw,1)):
                for index in np.ndindex(array.shape):
                    plus=array.copy();minus=array.copy();plus[index]+=1e-5;minus[index]-=1e-5
                    upper=loss(plus,w) if slot==0 else loss(z,plus)
                    lower=loss(minus,w) if slot==0 else loss(z,minus)
                    self.assertAlmostEqual((upper-lower)/2e-5,gradient[index],places=8)

    def test_keep_all_identity_semantics_matches_raw_gradient_exactly(self):
        z,w,r,y,ft,fi,image=fixture();identity=np.tile(SEM,(3,1));p,q=softmax(z),softmax(w)
        terms=all_terms(p,q,r,y,identity,identity,SEM,SEM,1.5)
        for objective in ('additive','ndu'):
            a=select_gradients(terms,'raw',objective,.2);b=select_gradients(terms,'aligned',objective,.2)
            for x,yy in zip(a,b):np.testing.assert_array_equal(x,yy)

    def test_fully_set_constant_law_has_zero_aligned_gradient(self):
        z,w,r,y,ft,fi,image=fixture();ft=np.repeat(y[:,None],12,axis=1);fi=np.repeat(np.argsort(image)[y,None],12,axis=1)
        terms=all_terms(softmax(z),softmax(w),r,y,ft,fi,SEM,image,1.5)
        for objective in ('additive','ndu'):
            for g in select_gradients(terms,'aligned',objective,.2):np.testing.assert_allclose(g,0,rtol=0,atol=1e-14)

    def test_no_target_mass_rejects_without_epsilon(self):
        z,w,r,y,ft,fi,image=fixture();ft=np.zeros((3,12),dtype=int)
        with self.assertRaises(ValueError):all_terms(softmax(z),softmax(w),r,y,ft,fi,SEM,image,1.5)

    def test_profile_map_shapes_and_modes_reject(self):
        z,w,r,y,ft,fi,image=fixture()
        with self.assertRaises(ValueError):all_terms(softmax(z),softmax(w),r,y,ft[:,:11],fi,SEM,image,1.5)
        with self.assertRaises(ValueError):select_gradients({},'default','ndu',.2)

    def test_pullback_does_not_mutate_inputs(self):
        z,w,r,y,ft,fi,image=fixture();p,q=softmax(z),softmax(w)
        values=[p,q,r,y,ft,fi,image];copies=[v.copy() for v in values]
        all_terms(p,q,r,y,ft,fi,SEM,image,1.5)
        for a,b in zip(values,copies):np.testing.assert_array_equal(a,b)

if __name__=='__main__':unittest.main()
